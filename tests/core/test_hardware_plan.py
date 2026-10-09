import subprocess
from pathlib import Path

import pytest

from bastet.core.changes import write_changes
from bastet.core.shell import parse_sections
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
        p.write_text(f"---\nbastet: host\ntype: proxmox\nip: 10.0.10.{11 if name == 'pve1' else 12}\n---\n# {name}\n")
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
        "ConBee II DE2412345.md", "M391A4G43MB1-CTD 40A1B2C3.md", "M391A4G43MB1-CTD 40A1B2C4.md",
        "PWS-504P-1R P504PCH12AB3456.md",
        "Samsung SSD 970 EVO Plus 1TB S4EWNX0R123456.md", "Supermicro SYS-5019C-MR S123456X.md",
        "WDC WD40EFRX-68N32N0 WD-WCC4E1234567.md", "WDC WD40EFRX-68N32N0 WD-WCC4E7654321.md",
        "pve1 Ethernet Converged Network Adapter X710-2.md", "pve1 Intel Xeon E-2236 CPU.md",
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


def test_serial_learned_later_updates_the_same_machine_file(repo):
    no_root = dict(SERVER, privilege="none", dmidecode=(126, ""), smart=(126, ""), ipmi=(126, ""), pve_guests=(126, ""))
    changes, _ = run(repo, "pve1", no_root)
    apply(repo, changes)
    changes2, _ = run(repo, "pve1")
    machine = [c for c in changes2 if "Supermicro" in c.path.name]
    assert len(machine) == 1 and machine[0].before is not None
    assert machine[0].path.name == "pve1 Supermicro SYS-5019C-MR.md" and "serial: S123456X" in machine[0].after


def test_machine_with_serial_not_duplicated_by_later_no_root_gather(repo):
    changes, _ = run(repo, "pve1")
    apply(repo, changes)
    no_root = dict(SERVER, privilege="none", dmidecode=(126, ""), smart=(126, ""), ipmi=(126, ""), pve_guests=(126, ""))
    changes2, _ = run(repo, "pve1", no_root)
    assert not [c for c in changes2 if c.before is None and "Supermicro" in c.path.name]


def test_card_survives_bus_renumbering(repo):
    changes, _ = run(repo, "pve1")
    apply(repo, changes)
    renum = dict(SERVER, lspci=SERVER["lspci"].replace("0000:01:00", "0000:02:00"),
                 net_sysfs=SERVER["net_sysfs"].replace("0000:01:00", "0000:02:00"),
                 dmidecode=SERVER["dmidecode"].replace("0000:01:00.0", "0000:02:00.0"))
    changes2, notes = run(repo, "pve1", renum)
    card = [c for c in changes2 if "X710" in c.path.name]
    assert len(card) == 1 and card[0].before is not None and "pci: 0000:02:00" in card[0].after
    assert not [n for n in notes if "wasn't seen" in n.message]


def test_same_key_twice_in_one_run_is_claimed_once(repo):
    from bastet.core.hardware import RunState
    state = RunState()
    inv = load_inventory(repo.root, TYPES)
    results = parse_sections(stdout_for(SERVER))
    v = observe_hardware("pve1", results, extract(results))
    first, _ = plan_hardware(inv, inv.get("pve1"), v, repo, take=set(), run=state)
    v2 = observe_hardware("pve2", results, extract(results))
    second, notes = plan_hardware(inv, inv.get("pve2"), v2, repo, take=set(), run=state)
    assert len(first) == 10 and [c for c in second if c.before is None and "WD-WCC4E" in c.path.name] == []
    assert any("also seen" in n.message for n in notes)


def test_hardware_files_get_summary_and_existing_ones_get_it_once(repo):
    changes, _ = run(repo, "pve1")
    assert all(f"![[{c.path.stem} summary]]" in c.after and "bastet-host" in c.after for c in changes)
    machine = [c for c in changes if "Supermicro" in c.path.name][0]
    assert "oob_address: 10.0.10.9" in machine.after
    old = [c for c in changes if "WD-WCC4E1234567" in c.path.name][0]
    old.after = old.after.replace(f"\n![[{old.path.stem} summary]]\n", "")
    apply(repo, changes)
    again, _ = run(repo, "pve1")
    assert [c.path for c in again] == [old.path] and f"![[{old.path.stem} summary]]" in again[0].after


def test_removed_parts_are_warned_only_when_their_probe_ran(repo):
    changes, _ = run(repo, "pve1")
    apply(repo, changes)
    no_stick = SERVER["usb"].replace("1-1\t1cf1\t0030\t00\tremovable\tdresden elektronik ingenieurtechnik GmbH\tConBee II\tDE2412345\n", "")
    _, notes = run(repo, "pve1", dict(SERVER, usb=no_stick))
    assert [n.message for n in notes if "wasn't seen" in n.message and "ConBee" in n.message]
    _, notes = run(repo, "pve1", dict(SERVER, usb=(1, ""), ipmi_fru=(126, "")))
    assert not [n for n in notes if "wasn't seen" in n.message]


def test_psu_not_warned_when_only_fru_knew_it_and_ipmitool_is_gone(repo):
    no_dmi_psu = SERVER["dmidecode"].split("Handle 0x0050")[0]
    changes, _ = run(repo, "pve1", dict(SERVER, dmidecode=no_dmi_psu))
    apply(repo, changes)
    _, notes = run(repo, "pve1", dict(SERVER, dmidecode=no_dmi_psu, ipmi_fru=(127, "")))
    assert not [n for n in notes if "wasn't seen" in n.message]


def test_psu_serial_coming_and_going_keeps_one_file(repo):
    dmi_no_serial = SERVER["dmidecode"].replace("\tSerial Number: P504PCH12AB3456\n", "")
    changes, _ = run(repo, "pve1", dict(SERVER, dmidecode=dmi_no_serial))
    apply(repo, changes)
    again, notes = run(repo, "pve1", dict(SERVER, dmidecode=dmi_no_serial, ipmi_fru=(127, "")))
    assert [c for c in again if c.before is None] == []
    assert not [n for n in notes if "wasn't seen" in n.message]


def test_hand_filled_serial_keeps_file_and_swapped_dimm_gets_new_one(repo):
    import re
    changes, _ = run(repo, "pve1")
    apply(repo, changes)
    cpu = repo.root / "hardware" / "pve1 Intel Xeon E-2236 CPU.md"
    cpu.write_text(cpu.read_text().replace("socket: CPU\n", "socket: CPU\nserial: LABEL123\n"))
    repo.commit([cpu], "hand edit", as_bastet=False)
    again, notes = run(repo, "pve1")
    assert [c for c in again if c.before is None] == []
    assert not [n for n in notes if "wasn't seen" in n.message]
    swapped = SERVER["dmidecode"].replace("Serial Number: 40A1B2C3", "Serial Number: 99Z9Z9Z9")
    third, _ = run(repo, "pve1", dict(SERVER, dmidecode=swapped))
    assert [c.path.name for c in third if c.before is None] == ["M391A4G43MB1-CTD 99Z9Z9Z9.md"]
    assert re.search(r"serial: 40A1B2C3", (repo.root / "hardware" / "M391A4G43MB1-CTD 40A1B2C3.md").read_text())
