import subprocess
from pathlib import Path

import pytest

from bastet.core.changes import write_changes
from bastet.core.collect import parse_sections
from bastet.core.facts import extract
from bastet.core.gitrepo import GitRepo
from bastet.core.hardware import observe_hardware, plan_hardware
from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from gather_fixtures import SERVER, stdout_for

TYPES = load_host_types()


@pytest.fixture
def repo(tmp_path) -> GitRepo:
    r = GitRepo(tmp_path)
    r.init()
    for k, v in (("user.name", "Tester"), ("user.email", "t@example.com")):
        subprocess.run(["git", "-C", str(tmp_path), "config", k, v], check=True)
    for name in ("pve1", "pve2"):
        p = tmp_path / "hosts" / f"{name}.md"
        p.parent.mkdir(exist_ok=True)
        p.write_text(f"---\nbastet: host\ntype: proxmox-node\nip: 10.0.10.{11 if name == 'pve1' else 12}\n---\n# {name}\n")
    r.commit([tmp_path / "hosts" / "pve1.md", tmp_path / "hosts" / "pve2.md"], "hosts", as_bastet=False)
    return r


def run(repo: GitRepo, host: str, outputs=SERVER, take=()):
    inv = load_inventory(repo.root, TYPES)
    results = parse_sections(stdout_for(outputs))
    v = observe_hardware(host, results, extract(results))
    return plan_hardware(inv, inv.get(host), v, repo, take=set(take))


def apply(repo: GitRepo, changes, *, as_bastet=True):
    write_changes(changes)
    repo.commit([c.path for c in changes], "gather", as_bastet=as_bastet)


def test_first_gather_creates_files(repo):
    changes, notes = run(repo, "pve1")
    names = sorted(c.path.name for c in changes)
    assert names == [
        "Samsung SSD 970 EVO Plus 1TB S4EWNX0R123456.md", "Supermicro SYS-5019C-MR S123456X.md",
        "WDC WD40EFRX-68N32N0 WD-WCC4E1234567.md", "WDC WD40EFRX-68N32N0 WD-WCC4E7654321.md",
        "pve1 Ethernet Converged Network Adapter X710-2.md",
    ]
    assert all(c.before is None and c.path.parent == repo.root / "hardware" for c in changes)
    assert notes == []


def test_second_gather_changes_nothing(repo):
    changes, _ = run(repo, "pve1")
    apply(repo, changes)
    again, notes = run(repo, "pve1")
    assert again == [] and notes == []


def test_moved_drive_updates_installed_in(repo):
    changes, _ = run(repo, "pve1")
    apply(repo, changes)
    changes2, notes = run(repo, "pve2")
    moved = [c for c in changes2 if c.path.name == "WDC WD40EFRX-68N32N0 WD-WCC4E1234567.md"]
    assert len(moved) == 1 and moved[0].before is not None
    assert 'installed_in: "[[pve2]]"' in moved[0].after
    assert any("moved from [[pve1]] to [[pve2]]" in n.message for n in notes)


def test_missing_drive_is_warned_not_changed(repo):
    changes, _ = run(repo, "pve1")
    apply(repo, changes)
    import json
    blk = json.loads(SERVER["lsblk"])
    blk["blockdevices"] = [d for d in blk["blockdevices"] if d.get("serial") != "WD-WCC4E7654321"]
    changes2, notes = run(repo, "pve1", dict(SERVER, lsblk=json.dumps(blk)))
    assert not [c for c in changes2 if "WD-WCC4E7654321" in c.path.name]
    [n] = [n for n in notes if "WD-WCC4E7654321" in n.message]
    assert n.severity == "warn" and "wasn't seen" in n.message


def test_hand_set_fact_on_hardware_kept(repo):
    changes, _ = run(repo, "pve1")
    apply(repo, changes)
    p = repo.root / "hardware" / "WDC WD40EFRX-68N32N0 WD-WCC4E1234567.md"
    p.write_text(p.read_text().replace("firmware: 82.00A82", "firmware: 81.00A81"))
    repo.commit([p], "fw", as_bastet=False)
    changes2, notes = run(repo, "pve1")
    assert not [c for c in changes2 if c.path == p]
    assert any("firmware" in n.message and "Tester" in n.message for n in notes)
    changes3, _ = run(repo, "pve1", take={"firmware"})
    assert any(c.path == p and "firmware: 82.00A82" in c.after for c in changes3)


def test_yours_fields_untouched_and_name_collision(repo):
    note = repo.root / "notes" / "Supermicro SYS-5019C-MR S123456X.md"
    note.parent.mkdir()
    note.write_text("# my own note\n")
    changes, _ = run(repo, "pve1")
    machine = [c for c in changes if "Supermicro" in c.path.name]
    assert machine[0].path.name == "Supermicro SYS-5019C-MR S123456X 2.md"
    apply(repo, changes)
    p = machine[0].path
    p.write_text(p.read_text().replace("status: in-service", "status: spare\npurchased: 2023-04-02"))
    repo.commit([p], "mine", as_bastet=False)
    changes2, notes = run(repo, "pve1")
    assert not [c for c in changes2 if c.path == p]
    assert any("status 'spare'" in n.message for n in notes)
