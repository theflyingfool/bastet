import subprocess
from pathlib import Path

import pytest

from bastet.core.changes import write_changes
from bastet.core.frontmatter import parse_document
from bastet.core.gitrepo import GitRepo
from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from bastet.core.render import (
    DASHBOARD_PATH, dashboard, generated_changes, hardware_summary, host_summary, short_cpu, summary_path,
)

TYPES = load_host_types()

FILES = {
    "Homelab.md": "---\nbastet: lab\nname: Homelab\ndomains:\n  public: example.com\n---\n# Homelab\n",
    "locations/Closet.md": "---\nbastet: location\n---\n# Closet\n",
    "locations/Linode.md": "---\nbastet: location\n---\n# Linode\n",
    "hosts/pve1.md": (
        "---\nbastet: host\ntype: proxmox-node\nip: 10.0.10.11\nlocation: \"[[Closet]]\"\nos: Debian GNU/Linux 13 (trixie)\n"
        "kernel: 6.14.8-2-pve\ncpu: Intel(R) Xeon(R) E-2236 CPU @ 3.40GHz\ncpu_cores: 6\ncpu_threads: 12\nram: 64 GB\n"
        "storage: 9 TB\ngateway: 10.0.10.1\nchassis: server\n---\n# pve1\n"
    ),
    "hosts/git1.md": "---\nbastet: host\ntype: lxc\nruns_on: \"[[pve1]]\"\nip: 10.0.20.21\nos: Debian 13\n---\n# git1\n",
    "hosts/vps1.md": (
        "---\nbastet: host\ntype: vps\nprovider: linode\nip: 203.0.113.10\nlocation: \"[[Linode]]\"\nos: Arch Linux\n"
        "ram: 1 GB\nvirtualization: kvm\nchassis: vm\n---\n# vps1\n"
    ),
    "hardware/Supermicro SYS-5019C-MR S123456X.md": (
        "---\nbastet: hardware\ncategory: server\nmake: Supermicro\nmodel: SYS-5019C-MR\nserial: S123456X\nstatus: in-service\n"
        "installed_in: \"[[pve1]]\"\nboard: Supermicro X11SCM-F\nbios: AMI 3.4 (03/21/2023)\nmemory_slots: 2 of 4 used\n"
        "memory:\n  - slot: DIMMA1\n    size: 32 GB\n  - slot: DIMMB1\n    size: 32 GB\noob_address: 10.0.10.9\n"
        "oob:\n  type: ipmi\n  address: 10.0.10.9\n---\n# m\n"
    ),
    "hardware/WDC WD40EFRX WD-1.md": (
        "---\nbastet: hardware\ncategory: drive\nmodel: WDC WD40EFRX\nserial: WD-1\nsize: 4 TB\nmedia: hdd\ninterface: sata\n"
        "health: passed\nfirmware: 82.00A82\npool: tank\nstatus: in-service\ninstalled_in: \"[[pve1]]\"\n---\n# d\n"
    ),
    "hardware/Spare WD.md": (
        "---\nbastet: hardware\ncategory: drive\nmodel: WDC WD40EFRX\nserial: WD-2\nsize: 4 TB\nstatus: spare\n"
        "location: \"[[Closet]]\"\nwarranty_until: 2026-11-01\n---\n# s\n"
    ),
}


@pytest.fixture
def repo(tmp_path) -> GitRepo:
    for rel, text in FILES.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    r = GitRepo(tmp_path)
    r.init()
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    r.commit([tmp_path / rel for rel in FILES], "gather: pve1", as_bastet=True)
    return r


def inv(repo):
    return load_inventory(repo.root, TYPES)


def test_short_cpu():
    assert short_cpu("Intel(R) Core(TM) i7-7500U CPU @ 2.70GHz") == "Intel Core i7-7500U"
    assert short_cpu("AMD EPYC 7713 64-Core Processor") == "AMD EPYC 7713 64-Core"


def test_host_summary_cards_and_warnings(repo):
    i = inv(repo)
    text = host_summary(i, i.get("pve1"), TYPES, ["ram: file says 128 GB, observed 64 GB"])
    doc = parse_document(text, Path("x.md"))
    assert doc.data["generated"] is True and doc.data["warnings"] == ["ram: file says 128 GB, observed 64 GB"]
    for card in ("[!stat] OS", "[!stat] CPU", "[!stat] RAM", "[!stat] Storage", "[!stat] Network",
                 "[!stat] Machine", "[!stat] Out-of-band", "[!stat] Guests"):
        assert card in text, card
    assert "**Intel Xeon E-2236**" in text and "6 cores · 12 threads" in text
    assert "2 of 4 used" in text and "10.0.10.9" in text and "[[git1]]" in text
    assert "[!warning]" in text and "128 GB" in text


def test_virtual_host_has_no_machine_cards(repo):
    i = inv(repo)
    text = host_summary(i, i.get("vps1"), TYPES, [])
    assert "[!stat] Machine" not in text and "[!stat] Guests" not in text and "[!warning]" not in text
    assert "kvm" in text


def test_hardware_summaries(repo):
    i = inv(repo)
    machine = hardware_summary(i, i.get("Supermicro SYS-5019C-MR S123456X"))
    assert "[!stat] Memory" in machine and "64 GB" in machine and "[!stat] Out-of-band" in machine
    drive = hardware_summary(i, i.get("WDC WD40EFRX WD-1"))
    assert "[!stat] Health" in drive and "passed" in drive and "tank" in drive and "[[pve1]]" in drive


def test_dashboard(repo):
    i = inv(repo)
    text = dashboard(i, TYPES, {"pve1": ["ram mismatch"]}, ["`2026-10-01` gather: pve1"])
    assert "[!stat] Hosts" in text and "**3**" in text
    assert "## Needs attention" in text and "ram mismatch" in text
    assert "```mermaid" in text and 'subgraph loc_Closet["📍 Closet"]' in text
    assert "pve1 --> git1" in text
    assert "example.com" in text and "Spare WD" in text and "10.0.10.9" in text
    assert "gather: pve1" in text


def test_generated_changes_idempotent_and_keep_warnings(repo):
    first = generated_changes(inv(repo), TYPES, repo, warnings={"pve1": ["ram mismatch"]})
    paths = {c.path for c in first}
    assert summary_path(repo.root, "pve1") in paths and repo.root / DASHBOARD_PATH in paths
    assert summary_path(repo.root, "Spare WD") in paths
    write_changes(first)
    repo.commit([c.path for c in first], "refresh: views")
    assert generated_changes(inv(repo), TYPES, repo) == []
    kept = parse_document(summary_path(repo.root, "pve1").read_text(), Path("x"))
    assert kept.data["warnings"] == ["ram mismatch"]


def test_recent_changes_ignore_refresh_commits(repo):
    first = generated_changes(inv(repo), TYPES, repo)
    write_changes(first)
    repo.commit([c.path for c in first], "refresh: views")
    text = (repo.root / DASHBOARD_PATH).read_text()
    assert "gather: pve1" in text and "refresh:" not in text


def test_guide_generated_and_linked(repo):
    changes = {c.path: c for c in generated_changes(inv(repo), TYPES, repo)}
    guide = changes[repo.root / "_bastet" / "Bastet guide.md"].after
    assert "generated: true" in guide and "bastet gather" in guide and "bastet refresh" in guide
    assert "[[Bastet guide]]" in changes[repo.root / DASHBOARD_PATH].after
