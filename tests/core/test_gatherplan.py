import subprocess
from pathlib import Path

import pytest

from bastet.core.collect import parse_sections
from bastet.core.facts import extract
from bastet.core.frontmatter import parse_document
from bastet.core.gatherplan import plan_update
from bastet.core.gitrepo import GitRepo
from bastet.core.hosttypes import load_host_types
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


def plan(p: Path, outputs, repo, type_name, take=(), hostkey=None):
    doc = parse_document(p.read_text(), p)
    ex = extract(parse_sections(stdout_for(outputs)))
    return plan_update(doc, ex, TYPES[type_name], repo, take=set(take), hostkey=hostkey)


def test_new_facts_added_and_section_appended(repo):
    p = host(repo, "---\nbastet: host\ntype: laptop\nconnection: local\n---\n# h\nmy notes\n")
    up = plan(p, LAPTOP, repo, "laptop")
    after = up.change.after
    assert "connection: local\nhostname: hp-13\n" in after
    assert "ram: 16 GB" in after and "interfaces:\n  - name: wlan0\n" in after
    assert after.endswith("my notes\n\n## Hardware\n\n![[hardware-here.base]]\n")
    assert up.notes == []


def test_no_change_when_up_to_date(repo):
    p = host(repo, "---\nbastet: host\ntype: laptop\n---\n# h\n")
    first = plan(p, LAPTOP, repo, "laptop")
    p.write_text(first.change.after)
    repo.commit([p], "gather", as_bastet=True)
    assert plan(p, LAPTOP, repo, "laptop").change is None


def test_hand_set_physical_value_kept_with_warning(repo):
    p = host(repo, "---\nbastet: host\ntype: laptop\nram: 32 GB\n---\n# h\n")
    up = plan(p, LAPTOP, repo, "laptop")
    assert "ram: 32 GB" in up.change.after
    [n] = [n for n in up.notes if "ram" in n.message]
    assert n.severity == "warn" and "Tester" in n.message and "--take ram" in n.message


def test_take_overrides(repo):
    p = host(repo, "---\nbastet: host\ntype: laptop\nram: 32 GB\n---\n# h\n")
    up = plan(p, LAPTOP, repo, "laptop", take={"ram"})
    assert "ram: 16 GB" in up.change.after


def test_bastet_set_value_is_updated(repo):
    p = host(repo, "---\nbastet: host\ntype: laptop\nram: 8 GB\n---\n# h\n\n## Hardware\n\n![[hardware-here.base]]\n", as_bastet=True)
    up = plan(p, LAPTOP, repo, "laptop")
    assert "ram: 16 GB" in up.change.after and not [n for n in up.notes if "ram" in n.message]


def test_virtual_host_mismatch_is_info(repo):
    p = host(repo, "---\nbastet: host\ntype: vps\nprovider: linode\nip: 203.0.113.10\nos: Debian 12\n---\n# v\n")
    up = plan(p, VPS, repo, "vps")
    [n] = [n for n in up.notes if "os" in n.message]
    assert n.severity == "info"


def test_desired_field_reported_not_written(repo):
    p = host(repo, '---\nbastet: host\ntype: lxc\nruns_on: "[[pve1]]"\nip: 10.0.20.21\nram: 2 GB\n---\n# c\n')
    up = plan(p, VPS, repo, "lxc")
    assert "ram: 2 GB" in up.change.after
    assert any("ram" in n.message and "desired" in n.message for n in up.notes)


def test_unknown_type_gets_proposal_others_get_note(repo):
    p = host(repo, "---\nbastet: host\ntype: unknown\n---\n# u\n")
    assert "type: vps" in plan(p, VPS, repo, "unknown").change.after
    p2 = host(repo, "---\nbastet: host\ntype: server\nip: 203.0.113.10\n---\n# s\n")
    up = plan(p2, VPS, repo, "server")
    assert "type: server" in up.change.after and any("looks like a vps" in n.message for n in up.notes)


def test_hostkey_recorded(repo):
    p = host(repo, "---\nbastet: host\ntype: vps\nprovider: linode\nip: 203.0.113.10\n---\n# v\n")
    up = plan(p, VPS, repo, "vps", hostkey="ssh-ed25519 SHA256:abc")
    assert 'ssh_host_key: ssh-ed25519 SHA256:abc' in up.change.after
