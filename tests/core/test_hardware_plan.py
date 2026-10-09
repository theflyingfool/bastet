import subprocess

import pytest

from bastet.core.changes import write_changes
from bastet.core.factsnote import hardware_facts_change, hardware_facts_path
from bastet.core.shell import parse_sections
from bastet.core.facts import extract
from bastet.core.frontmatter import parse_document
from bastet.core.gitrepo import GitRepo
from bastet.core.hardware import RunState, missing_hardware, observe_hardware, plan_hardware
from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from gather_fixtures import SERVER, stdout_for

TYPES = load_host_types()
GATHERED = "2026-10-06T10:00:00Z"


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


def run(repo: GitRepo, host: str, outputs=SERVER, state: RunState | None = None, gathered: str = GATHERED,
        sweep: bool = True):
    """One host's hardware plan, plus (by default) the end-of-run missing-hardware sweep and the
    facts-note Changes built from the run accumulator -- i.e. everything `_gather` would do for hardware."""
    inv = load_inventory(repo.root, TYPES)
    results = parse_sections(stdout_for(outputs))
    v = observe_hardware(host, results, extract(results))
    run_state = state if state is not None else RunState()
    changes, notes, _touched = plan_hardware(inv, inv.get(host), v, run=run_state, gathered=gathered)
    if sweep:
        notes = [*notes, *missing_hardware(inv, run_state, gathered)]
    for name, facts in run_state.hw_facts.values():
        c = hardware_facts_change(repo.root, name, facts, gathered)
        if c is not None:
            changes.append(c)
    return changes, notes


def apply(repo: GitRepo, changes, *, as_bastet=True):
    write_changes(changes)
    repo.commit([c.path for c in changes], "gather", as_bastet=as_bastet)


def yours(changes):
    return [c for c in changes if c.path.parent.name == "hardware"]


def facts(changes):
    return [c for c in changes if "_bastet" in c.path.parts and c.path.parent.name == "facts"]


NAMES = [
    "ConBee II DE2412345", "M391A4G43MB1-CTD 40A1B2C3", "M391A4G43MB1-CTD 40A1B2C4",
    "PWS-504P-1R P504PCH12AB3456",
    "Samsung SSD 970 EVO Plus 1TB S4EWNX0R123456",
    "Supermicro SYS-5019C-MR S123456X",
    "WDC WD40EFRX-68N32N0 WD-WCC4E1234567", "WDC WD40EFRX-68N32N0 WD-WCC4E7654321",
    "pve1 Ethernet Converged Network Adapter X710-2", "pve1 Intel Xeon E-2236 CPU",
]


def test_first_gather_creates_both_notes_for_each_item(repo):
    changes, notes = run(repo, "pve1")
    new_yours = sorted(c.path.stem for c in yours(changes) if c.before is None)
    new_facts = sorted(c.path.stem for c in facts(changes) if c.before is None)
    assert new_yours == sorted(NAMES)
    assert new_facts == sorted(f"{n} facts" for n in NAMES)
    assert all(c.before is None and c.path.parent == repo.root / "hardware" for c in yours(changes))
    assert notes == []


def test_new_hardware_note_has_empty_yours_fields(repo):
    changes, _ = run(repo, "pve1")
    machine = [c for c in yours(changes) if "Supermicro" in c.path.name][0]
    for key in ("price", "vendor", "purchased", "location", "warranty_until", "status", "notes"):
        assert f"{key}:" in machine.after or f'{key}: ""' in machine.after
    assert "bastet: hardware" in machine.after and "category: server" in machine.after
    assert "serial" not in machine.after and "make" not in machine.after


def test_second_gather_changes_nothing(repo):
    changes, _ = run(repo, "pve1")
    apply(repo, changes)
    again, notes = run(repo, "pve1")
    assert again == [] and notes == []


def test_moved_drive_updates_facts_note_installed_in(repo):
    changes, _ = run(repo, "pve1")
    apply(repo, changes)
    changes2, notes = run(repo, "pve2")
    moved = [c for c in facts(changes2) if "WD-WCC4E1234567" in c.path.name]
    assert len(moved) == 1 and moved[0].before is not None
    assert 'installed_in: "[[pve2]]"' in moved[0].after
    assert not [c for c in yours(changes2) if "WD-WCC4E1234567" in c.path.name]
    assert any("moved from [[pve1]] to [[pve2]]" in n.message for n in notes)


def test_missing_drive_sets_missing_since_and_warns(repo):
    changes, _ = run(repo, "pve1")
    apply(repo, changes)
    import json
    blk = json.loads(SERVER["lsblk"])
    blk["blockdevices"] = [d for d in blk["blockdevices"] if d.get("serial") != "WD-WCC4E7654321"]
    changes2, notes = run(repo, "pve1", dict(SERVER, lsblk=json.dumps(blk)))
    missing = [c for c in facts(changes2) if "WD-WCC4E7654321" in c.path.name]
    assert len(missing) == 1 and "missing_since: " in missing[0].after
    [n] = [n for n in notes if "WD-WCC4E7654321" in n.message]
    assert n.severity == "warn" and "wasn't seen" in n.message


def test_missing_hardware_clears_once_seen_again(repo):
    changes, _ = run(repo, "pve1")
    apply(repo, changes)
    import json
    blk = json.loads(SERVER["lsblk"])
    full = blk["blockdevices"]
    missing_blk = {**blk, "blockdevices": [d for d in full if d.get("serial") != "WD-WCC4E7654321"]}
    changes2, _ = run(repo, "pve1", dict(SERVER, lsblk=json.dumps(missing_blk)))
    apply(repo, changes2)
    changes3, notes3 = run(repo, "pve1")
    seen_again = [c for c in facts(changes3) if "WD-WCC4E7654321" in c.path.name]
    assert len(seen_again) == 1 and "missing_since" not in seen_again[0].after
    assert not [n for n in notes3 if "WD-WCC4E7654321" in n.message]


def test_missing_hardware_survives_a_second_gather_still_missing(repo):
    changes, _ = run(repo, "pve1")
    apply(repo, changes)
    import json
    blk = json.loads(SERVER["lsblk"])
    missing_blk = {**blk, "blockdevices": [d for d in blk["blockdevices"] if d.get("serial") != "WD-WCC4E7654321"]}
    changes2, _ = run(repo, "pve1", dict(SERVER, lsblk=json.dumps(missing_blk)), gathered="2026-10-06T10:00:00Z")
    apply(repo, changes2)
    first_date = hardware_facts_path(repo.root, "WDC WD40EFRX-68N32N0 WD-WCC4E7654321").read_text()
    assert 'missing_since: "2026-10-06"' in first_date
    changes3, notes3 = run(
        repo, "pve1", dict(SERVER, lsblk=json.dumps(missing_blk)), gathered="2026-10-07T10:00:00Z"
    )
    assert not [c for c in facts(changes3) if "WD-WCC4E7654321" in c.path.name]  # date kept, no new write
    assert [n for n in notes3 if "WD-WCC4E7654321" in n.message and "wasn't seen" in n.message]


def test_missing_hardware_clears_when_status_set_to_failed(repo):
    changes, _ = run(repo, "pve1")
    apply(repo, changes)
    missing_path = repo.root / "hardware" / "WDC WD40EFRX-68N32N0 WD-WCC4E7654321.md"
    missing_path.write_text(missing_path.read_text().replace('status: ""', "status: failed"))
    repo.commit([missing_path], "fail it", as_bastet=False)
    import json
    blk = json.loads(SERVER["lsblk"])
    no_drive = dict(SERVER, lsblk=json.dumps({**blk, "blockdevices": [d for d in blk["blockdevices"] if d.get("serial") != "WD-WCC4E7654321"]}))
    changes2, notes2 = run(repo, "pve1", no_drive)
    assert not [c for c in facts(changes2) if "WD-WCC4E7654321" in c.path.name]
    assert not [n for n in notes2 if "WD-WCC4E7654321" in n.message]


def test_moved_within_one_run_is_not_marked_missing(repo):
    """Both hosts planned in the same run, pve2 (where it now lives) processed first."""
    state = RunState()
    changes1, _ = run(repo, "pve2", state=state, sweep=False)
    changes2, notes2 = run(repo, "pve1", state=state, sweep=True)
    assert not [n for n in notes2 if "WD-WCC4E1234567" in n.message and "wasn't seen" in n.message]


def test_hand_set_yours_fields_never_touched(repo):
    changes, _ = run(repo, "pve1")
    apply(repo, changes)
    p = repo.root / "hardware" / "WDC WD40EFRX-68N32N0 WD-WCC4E1234567.md"
    p.write_text(p.read_text().replace('status: ""', "status: spare\nprice: 50"))
    repo.commit([p], "mine", as_bastet=False)
    before = p.read_text()
    changes2, _ = run(repo, "pve1")
    apply(repo, changes2)
    assert p.read_text() == before


def test_stale_gathered_key_on_yours_note_is_ignored_and_reported(repo):
    from bastet.core.hostview import stale_hardware_keys

    changes, _ = run(repo, "pve1")
    apply(repo, changes)
    p = repo.root / "hardware" / "WDC WD40EFRX-68N32N0 WD-WCC4E1234567.md"
    p.write_text(p.read_text().replace("category: drive\n", "category: drive\nfirmware: 81.00A81\n"))
    repo.commit([p], "stale key", as_bastet=False)
    inv = load_inventory(repo.root, TYPES)
    doc = inv.get("WDC WD40EFRX-68N32N0 WD-WCC4E1234567")
    assert stale_hardware_keys(doc) == ["firmware"]
    changes2, _ = run(repo, "pve1")
    assert not [c for c in yours(changes2) if c.path == p]  # gather never touches it
    fact = [c for c in facts(changes2) if "WD-WCC4E1234567" in c.path.name]
    assert not fact or "firmware: 82.00A82" in fact[0].after  # the real value stays in the facts note


def test_yours_name_collision(repo):
    note = repo.root / "notes" / "Supermicro SYS-5019C-MR S123456X.md"
    note.parent.mkdir()
    note.write_text("# my own note\n")
    changes, _ = run(repo, "pve1")
    machine = [c for c in yours(changes) if "Supermicro" in c.path.name]
    assert machine[0].path.name == "Supermicro SYS-5019C-MR S123456X 2.md"


def test_serial_learned_later_updates_the_same_machine_facts_note(repo):
    no_root = dict(SERVER, privilege="none", dmidecode=(126, ""), smart=(126, ""), ipmi=(126, ""), pve_guests=(126, ""))
    changes, _ = run(repo, "pve1", no_root)
    apply(repo, changes)
    changes2, _ = run(repo, "pve1")
    machine_yours = [c for c in yours(changes2) if "Supermicro" in c.path.name]
    assert machine_yours == []  # the yours note (no serial key at all) is never touched
    machine_facts = [c for c in facts(changes2) if "Supermicro" in c.path.name]
    assert len(machine_facts) == 1 and machine_facts[0].before is not None and "serial: S123456X" in machine_facts[0].after


def test_machine_with_serial_not_duplicated_by_later_no_root_gather(repo):
    changes, _ = run(repo, "pve1")
    apply(repo, changes)
    no_root = dict(SERVER, privilege="none", dmidecode=(126, ""), smart=(126, ""), ipmi=(126, ""), pve_guests=(126, ""))
    changes2, _ = run(repo, "pve1", no_root)
    assert not [c for c in yours(changes2) if c.before is None and "Supermicro" in c.path.name]


def test_card_survives_bus_renumbering(repo):
    changes, _ = run(repo, "pve1")
    apply(repo, changes)
    renum = dict(SERVER, lspci=SERVER["lspci"].replace("0000:01:00", "0000:02:00"),
                 net_sysfs=SERVER["net_sysfs"].replace("0000:01:00", "0000:02:00"),
                 dmidecode=SERVER["dmidecode"].replace("0000:01:00.0", "0000:02:00.0"))
    changes2, notes = run(repo, "pve1", renum)
    card = [c for c in facts(changes2) if "X710" in c.path.name]
    assert len(card) == 1 and card[0].before is not None and "pci: 0000:02:00" in card[0].after
    assert not [n for n in notes if "wasn't seen" in n.message]


def test_same_key_twice_in_one_run_is_claimed_once(repo):
    state = RunState()
    changes1, _ = run(repo, "pve1", state=state, sweep=False)
    changes2, notes = run(repo, "pve2", state=state, sweep=False)
    new_drive = [c for c in yours(changes2) if c.before is None and "WD-WCC4E" in c.path.name]
    assert new_drive == []
    assert any("also seen" in n.message for n in notes)


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
    assert [c for c in yours(again) if c.before is None] == []
    assert not [n for n in notes if "wasn't seen" in n.message]


def test_hand_filled_serial_keeps_file_and_swapped_dimm_gets_new_one(repo):
    import re
    changes, _ = run(repo, "pve1")
    apply(repo, changes)
    cpu_facts = hardware_facts_path(repo.root, "pve1 Intel Xeon E-2236 CPU")
    cpu_facts.write_text(cpu_facts.read_text().replace("socket: CPU\n", "socket: CPU\nserial: LABEL123\n"))
    repo.commit([cpu_facts], "hand edit", as_bastet=False)
    again, notes = run(repo, "pve1")
    assert [c for c in yours(again) if c.before is None] == []
    assert not [n for n in notes if "wasn't seen" in n.message]
    swapped = SERVER["dmidecode"].replace("Serial Number: 40A1B2C3", "Serial Number: 99Z9Z9Z9")
    third, _ = run(repo, "pve1", dict(SERVER, dmidecode=swapped))
    assert [c.path.name for c in yours(third) if c.before is None] == ["M391A4G43MB1-CTD 99Z9Z9Z9.md"]
    assert re.search(r"serial: 40A1B2C3", hardware_facts_path(repo.root, "M391A4G43MB1-CTD 40A1B2C3").read_text())
