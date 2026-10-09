import subprocess
from pathlib import Path

import pytest

from bastet.core.shell import parse_sections
from bastet.core.facts import extract
from bastet.core.factsnote import facts_path
from bastet.core.frontmatter import parse_document
from bastet.core.gatherplan import plan_facts
from bastet.core.gitrepo import GitRepo
from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from gather_fixtures import LAPTOP, VPS, stdout_for

TYPES = load_host_types()


@pytest.fixture
def repo(tmp_path) -> GitRepo:
    r = GitRepo(tmp_path)
    r.init()
    for k, v in (("user.name", "Tester"), ("user.email", "t@example.com")):
        subprocess.run(["git", "-C", str(tmp_path), "config", k, v], check=True)
    return r


def host(repo: GitRepo, text: str, *, as_bastet: bool = False) -> Path:
    p = repo.root / "hosts" / "h.md"
    p.parent.mkdir(exist_ok=True)
    p.write_text(text)
    repo.commit([p], "seed", as_bastet=as_bastet)
    return p


def plan(root: Path, outputs, type_name: str, *, hostkey=None, gathered="2026-10-06T10:00:00Z"):
    inv = load_inventory(root, TYPES)
    doc = inv.get("h")
    ex = extract(parse_sections(stdout_for(outputs)))
    return plan_facts(doc, ex, TYPES[type_name], inv, hostkey=hostkey, gathered=gathered, types=TYPES)


def write_facts(up) -> None:
    up.change.path.parent.mkdir(parents=True, exist_ok=True)
    up.change.path.write_text(up.change.after)


def test_facts_written_never_the_host_note(repo):
    host(repo, "---\nbastet: host\ntype: laptop\nconnection: local\n---\n# h\nmy notes\n")
    up = plan(repo.root, LAPTOP, "laptop")
    assert up.change is not None
    assert up.change.path == facts_path(repo.root, "h")
    assert "ram: 16 GB" in up.change.after and "hostname: hp-13" in up.change.after
    assert "bastet: facts" in up.change.after
    assert [n.message for n in up.notes] == [
        "hosts/h.md has no summary embed; add ![[h summary]] (bastet add host does this for new hosts)"
    ]


def test_no_change_when_up_to_date(repo):
    host(repo, "---\nbastet: host\ntype: laptop\nconnection: local\n---\n# h\n![[h summary]]\n")
    first = plan(repo.root, LAPTOP, "laptop")
    write_facts(first)
    assert plan(repo.root, LAPTOP, "laptop", gathered="2026-10-06T11:00:00Z").change is None


def test_hostkey_recorded_in_facts_note(repo):
    host(repo, "---\nbastet: host\ntype: vps\nprovider: linode\nip: 203.0.113.10\n---\n# v\n")
    up = plan(repo.root, VPS, "vps", hostkey="ssh-ed25519 SHA256:abc")
    assert "ssh_host_key: ssh-ed25519 SHA256:abc" in up.change.after


def test_matching_hand_pinned_key_gives_no_note(repo):
    host(
        repo,
        "---\nbastet: host\ntype: vps\nprovider: linode\nip: 203.0.113.10\n"
        "ssh_host_key: ecdsa-sha2-nistp256 SHA256:x\n---\n# v\n![[h summary]]\n",
    )
    up = plan(repo.root, VPS, "vps", hostkey="ecdsa-sha2-nistp256 SHA256:x")
    assert not [n for n in up.notes if "ssh_host_key" in n.message]


def test_dhcp_host_keeps_no_addresses_or_gateway(repo):
    host(repo, "---\nbastet: host\ntype: laptop\nip: dhcp\nconnection: local\n---\n# h\n")
    after = plan(repo.root, LAPTOP, "laptop").change.after
    assert "10.0.10.50" not in after and "gateway" not in after
    assert "  - name: wlan0\n    mac: aa:bb:cc:dd:ee:10\n" in after


def test_desired_field_drift_is_an_info_note_and_observed_value_is_kept(repo):
    host(repo, '---\nbastet: host\ntype: lxc\nruns_on: "[[pve1]]"\nip: 10.0.20.21\nram: 2 GB\n---\n# c\n![[h summary]]\n')
    up = plan(repo.root, VPS, "lxc")
    assert any("ram" in n.message and "desired" in n.message and n.severity == "info" for n in up.notes)
    assert "ram: 4 GB" in up.change.after  # the observed value, not the declared one


def test_yours_field_drift_is_an_info_note_with_its_own_wording(repo):
    """A `yours` field (e.g. hostname) isn't something apply will ever reconcile, unlike `desired` --
    so its drift note must not promise that, the way a `desired` field's does."""
    host(repo, "---\nbastet: host\ntype: laptop\nconnection: local\nhostname: custom\n---\n# h\n![[h summary]]\n")
    up = plan(repo.root, LAPTOP, "laptop")
    assert any("hostname" in n.message and "custom" in n.message and "hp-13" in n.message for n in up.notes)
    assert not any("apply will handle" in n.message for n in up.notes)
    assert "hostname: hp-13" in up.change.after


def test_fact_nature_mismatch_on_host_note_gives_no_gather_note(repo):
    """A stale fact left on the host note is Task 2's problem to report, not gather's."""
    host(repo, "---\nbastet: host\ntype: vps\nprovider: linode\nip: 203.0.113.10\nos: Debian 12\n---\n# v\n![[h summary]]\n")
    up = plan(repo.root, VPS, "vps")
    assert not [n for n in up.notes if "os" in n.message]
    assert "os: Debian GNU/Linux 13 (trixie)" in up.change.after


def test_unknown_type_gets_a_note_only_never_a_write(repo):
    host(repo, "---\nbastet: host\ntype: unknown\nprovider: linode\nip: 203.0.113.10\n---\n# u\n![[h summary]]\n")
    up = plan(repo.root, VPS, "unknown")
    assert any(n.message == "this host looks like a vps; set type: vps" for n in up.notes)
    assert "type: vps" not in up.change.after


def test_type_mismatch_still_gets_an_info_note(repo):
    host(repo, "---\nbastet: host\ntype: server\nip: 203.0.113.10\n---\n# s\n![[h summary]]\n")
    up = plan(repo.root, VPS, "server")
    assert any("looks like a vps" in n.message for n in up.notes)


def test_unknown_type_note_lists_missing_minimal_fields(repo):
    host(repo, "---\nbastet: host\ntype: unknown\naddress: v.example.com\n---\n# u\n![[h summary]]\n")
    up = plan(repo.root, VPS, "unknown")
    assert any("looks like a vps" in n.message and "provider" in n.message for n in up.notes)


def test_missing_summary_embed_note(repo):
    host(repo, "---\nbastet: host\ntype: laptop\nconnection: local\n---\n# h\nno embed here\n")
    up = plan(repo.root, LAPTOP, "laptop")
    assert any(
        n.message == "hosts/h.md has no summary embed; add ![[h summary]] (bastet add host does this for new hosts)"
        for n in up.notes
    )


def test_summary_embed_present_gives_no_note(repo):
    host(repo, "---\nbastet: host\ntype: laptop\nconnection: local\n---\n# h\n![[h summary]]\n")
    up = plan(repo.root, LAPTOP, "laptop")
    assert not [n for n in up.notes if "summary embed" in n.message]
