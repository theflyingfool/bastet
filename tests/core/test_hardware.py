import json

from bastet.core.collect import parse_sections
from bastet.core.facts import extract
from bastet.core.hardware import file_name, observe_hardware
from gather_fixtures import LAPTOP, SERVER, stdout_for


def view(outputs, host="pve1"):
    results = parse_sections(stdout_for(outputs))
    return observe_hardware(host, results, extract(results))


def test_file_name():
    assert file_name("WDC WD40EFRX/68N32N0", "WD-WCC4E1234567") == "WDC WD40EFRX 68N32N0 WD-WCC4E1234567"
    assert file_name(None, "x") == "x"


def test_server_machine_file():
    v = view(SERVER)
    machine = v.items[0]
    assert machine.name == "Supermicro SYS-5019C-MR S123456X" and machine.key == "serial:s123456x"
    d = machine.data
    assert list(d)[:7] == ["bastet", "category", "make", "model", "serial", "status", "installed_in"]
    assert d["category"] == "server" and d["installed_in"] == "[[pve1]]" and d["status"] == "in-service"
    assert d["memory_slots"] == "2 of 4 used" and len(d["memory"]) == 2
    assert d["interfaces"] == [{"name": "eno1", "mac": "3c:ec:ef:00:00:01"}]
    assert d["oob"] == {"type": "ipmi", "address": "10.0.10.9", "mac": "3c:ec:ef:00:00:09", "source": "static"}


def test_server_drives():
    drives = {o.name: o for o in view(SERVER).items if o.data["category"] == "drive"}
    assert set(drives) == {
        "WDC WD40EFRX-68N32N0 WD-WCC4E1234567", "WDC WD40EFRX-68N32N0 WD-WCC4E7654321",
        "Samsung SSD 970 EVO Plus 1TB S4EWNX0R123456",
    }
    wd = drives["WDC WD40EFRX-68N32N0 WD-WCC4E1234567"].data
    assert wd["size"] == "4 TB" and wd["interface"] == "sata" and wd["media"] == "hdd"
    assert wd["firmware"] == "82.00A82" and wd["health"] == "passed" and wd["pool"] == "tank"
    assert drives["Samsung SSD 970 EVO Plus 1TB S4EWNX0R123456"].data["media"] == "ssd"


def test_server_card_pools_guests():
    v = view(SERVER)
    [card] = [o for o in v.items if o.data["category"] == "nic"]
    assert card.name == "pve1 Ethernet Converged Network Adapter X710-2" and card.key == "slot:pve1:6"
    assert card.data["slot"] == "CPU SLOT6 PCI-E 3.0 X16" and card.data["driver"] == "i40e"
    assert card.data["ports"] == [
        {"name": "enp1s0f0", "mac": "3c:fd:fe:00:00:10"},
        {"name": "enp1s0f1", "mac": "3c:fd:fe:00:00:11"},
    ]
    assert v.pools == [{"name": "tank", "state": "ONLINE"}]
    assert [g["name"] for g in v.guests] == ["git1", "media"]
    assert v.complete == {"drives": True, "cards": True} and not v.skipped_root


def test_laptop_machine_and_nvme():
    v = view(LAPTOP, host="hp-13")
    names = [o.name for o in v.items]
    assert names == ["HP Spectre x360 Convertible 13-ae0xx 5CD1234XYZ", "SAMSUNG MZVLB512HAJQ-000H1 S4XXNX0M123456"]
    assert v.items[0].data["category"] == "laptop"
    assert not [o for o in v.items if o.data["category"] in ("gpu", "nic", "hba")]


def test_no_root_still_makes_machine_file():
    outputs = dict(SERVER, privilege="none", dmidecode=(126, ""), smart=(126, ""), ipmi=(126, ""), pve_guests=(126, ""))
    v = view(outputs)
    machine = v.items[0]
    assert machine.data["make"] == "Supermicro" and machine.data["model"] == "SYS-5019C-MR"
    assert "serial" not in machine.data and machine.key == "machine:pve1" and machine.name == "pve1 Supermicro SYS-5019C-MR"
    assert v.skipped_root and v.complete["cards"] is True and v.complete["drives"] is True
    assert {o.data["category"] for o in v.items} == {"server", "drive", "nic"}


def test_identical_cards_get_distinct_names():
    # second card in physical slot 7
    two = SERVER["lspci"] + (
        "\nSlot:\t0000:05:00.0\nClass:\tEthernet controller [0200]\nVendor:\tIntel Corporation [8086]\n"
        "Device:\tEthernet Controller X710 for 10GbE SFP+ [1572]\nSVendor:\tIntel Corporation [8086]\n"
        "SDevice:\tEthernet Converged Network Adapter X710-2 [0007]\nPhySlot:\t7\nDriver:\ti40e\n"
    )
    dmi = SERVER["dmidecode"] + "\nHandle 0x000B, DMI type 9, 17 bytes\nSystem Slot Information\n\tDesignation: SLOT7\n\tCurrent Usage: In Use\n\tBus Address: 0000:05:00.0\n\tID: 7\n"
    cards = [o for o in view(dict(SERVER, lspci=two, dmidecode=dmi)).items if o.data["category"] == "nic"]
    assert sorted(c.name for c in cards) == [
        "pve1 Ethernet Converged Network Adapter X710-2 0000 01 00",
        "pve1 Ethernet Converged Network Adapter X710-2 0000 05 00",
    ]


def test_no_link_speed_written():
    v = view(SERVER)
    for o in v.items:
        for key in ("interfaces", "ports"):
            assert all("speed" not in p for p in o.data.get(key, []))


def test_cards_keyed_by_physical_slot_and_found_without_root():
    v = view(dict(SERVER, privilege="none", dmidecode=(126, ""), smart=(126, ""), ipmi=(126, ""), pve_guests=(126, "")))
    [card] = [o for o in v.items if o.data["category"] == "nic"]
    assert card.key == "slot:pve1:6" and card.data["phys_slot"] == "6" and card.data["slot"] == "slot 6"
    assert v.complete["cards"] is True


def test_unknown_subsystem_uses_device_name():
    lspci = SERVER["lspci"].replace("SDevice:\tEthernet Converged Network Adapter X710-2 [0007]", "SDevice:\tDevice [827e]")
    [card] = [o for o in view(dict(SERVER, lspci=lspci)).items if o.data["category"] == "nic"]
    assert card.data["model"] == "Ethernet Controller X710 for 10GbE SFP+"


def test_duplicate_serial_in_one_host_kept_once_with_note():
    blk = json.loads(SERVER["lsblk"])
    blk["blockdevices"].append(dict(blk["blockdevices"][0], name="sdd", path="/dev/sdd"))
    v = view(dict(SERVER, lsblk=json.dumps(blk)))
    assert len([o for o in v.items if o.data.get("serial") == "WD-WCC4E1234567"]) == 1
    assert any("WD-WCC4E1234567" in n for n in v.notes)
