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
    assert d["interfaces"] == [{"name": "eno1", "mac": "3c:ec:ef:00:00:01", "max_speed": "1G", "firmware": "3.16, 0x800004d6"}]
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
        {"name": "enp1s0f0", "mac": "3c:fd:fe:00:00:10", "max_speed": "10G", "firmware": "8.50 0x8000b6c5 1.3082.0"},
        {"name": "enp1s0f1", "mac": "3c:fd:fe:00:00:11", "max_speed": "10G", "firmware": "8.50 0x8000b6c5 1.3082.0"},
    ]
    assert v.pools == [{"name": "tank", "state": "ONLINE"}]
    assert [g["name"] for g in v.guests] == ["git1", "media", "dns", "ghost"]
    assert v.complete == {"drives": True, "cards": True, "cpus": True, "memory": True, "psus": True, "usb": True} and not v.skipped_root


def test_laptop_machine_and_nvme():
    v = view(LAPTOP, host="hp-13")
    names = [o.name for o in v.items]
    assert names == ["HP Spectre x360 Convertible 13-ae0xx 5CD1234XYZ", "SAMSUNG MZVLB512HAJQ-000H1 S4XXNX0M123456",
                     "hp-13 Intel Core i7-8565U U3E1", "hp-13 Onboard 16 GB"]
    assert v.items[0].data["category"] == "laptop"
    assert not [o for o in v.items if o.data["category"] in ("gpu", "nic", "hba")]


def test_no_root_still_makes_machine_file():
    outputs = dict(SERVER, privilege="none", dmidecode=(126, ""), smart=(126, ""), ipmi=(126, ""), pve_guests=(126, ""),
                   ipmi_fru=(126, ""), ipmi_mc=(126, ""))
    v = view(outputs)
    machine = v.items[0]
    assert machine.data["make"] == "Supermicro" and machine.data["model"] == "SYS-5019C-MR"
    assert "serial" not in machine.data and machine.key == "machine:pve1" and machine.name == "pve1 Supermicro SYS-5019C-MR"
    assert v.skipped_root and v.complete["cards"] is True and v.complete["drives"] is True
    assert {o.data["category"] for o in v.items} == {"server", "drive", "nic", "usb"}
    assert v.complete["cpus"] is False and v.complete["psus"] is False and v.complete["usb"] is True


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


def test_add_in_card_found_by_subsystem_vendor_when_slot_data_is_useless():
    from gather_fixtures import RACK
    v = view(RACK, host="sanrio")
    cards = {o.name: o for o in v.items if o.data["category"] in ("gpu", "hba", "nic")}
    assert list(cards) == ["sanrio 9207-8e SAS2.1 HBA"]
    hba = cards["sanrio 9207-8e SAS2.1 HBA"]
    assert hba.data["category"] == "hba" and hba.key == "pci:sanrio:0000:2b:00" and "slot" not in hba.data


def test_onboard_wired_and_wireless_interfaces_recorded():
    from gather_fixtures import RACK
    machine = view(RACK, host="sanrio").items[0]
    assert [i["name"] for i in machine.data["interfaces"]] == ["enp35s0", "enp36s0", "wlp44s0"]


def test_bmc_without_ipmitool_gives_a_hint():
    from gather_fixtures import RACK
    v = view(RACK, host="sanrio")
    assert any("ipmitool" in n for n in v.hints)
    assert not any("ipmitool" in n for n in view(SERVER).hints)


def test_guest_addresses_resolved():
    guests = {g["name"]: g for g in view(SERVER).guests}
    assert guests["git1"]["ip"] == "10.0.20.21/24" and guests["git1"]["ip_source"] == "config"
    assert guests["media"]["ip"] == "10.0.20.25" and guests["media"]["ip_source"] == "neighbour"
    assert guests["dns"]["ip"] == "10.0.20.36/24" and guests["dns"]["ip_source"] == "config"
    assert guests["ghost"]["ip"] is None


def test_subsystem_rule_not_used_when_slot_data_works():
    # SERVER has a working PhySlot for the X710; its onboard I210 with a chip-maker SVID must stay onboard.
    lspci = SERVER["lspci"].replace(
        "Device:\tI210 Gigabit Network Connection [1533]\nDriver:\tigb\n",
        "Device:\tI210 Gigabit Network Connection [1533]\nSVendor:\tIntel Corporation [8086]\nDriver:\tigb\n").replace(
        "Device:\tCoffeeLake-S GT2 [UHD Graphics P630] [3e96]\n",
        "Device:\tCoffeeLake-S GT2 [UHD Graphics P630] [3e96]\nSVendor:\tSuper Micro Computer Inc [15d9]\n")
    dmi = SERVER["dmidecode"]
    v = view(dict(SERVER, lspci=lspci, dmidecode=dmi))
    assert [o.name for o in v.items if o.data["category"] == "nic"] == ["pve1 Ethernet Converged Network Adapter X710-2"]
    assert [i["name"] for i in v.items[0].data["interfaces"]] == ["eno1"]


def test_cpu_and_dimm_files_without_serials():
    v = view(LAPTOP, host="hp-13")
    cats = {o.data["category"]: o for o in v.items}
    assert cats["cpu"].key == "cpu:hp-13:u3e1" and cats["cpu"].name == "hp-13 Intel Core i7-8565U U3E1"
    assert cats["memory"].key == "dimm:hp-13:onboard" and cats["memory"].name == "hp-13 Onboard 16 GB"
    assert "serial" not in cats["memory"].data and cats["memory"].data["size"] == "16 GB"
    assert [o.key for o in view(LAPTOP, host="hp-13").items] == [o.key for o in v.items]


def test_server_cpu_dimm_psu_files():
    v = view(SERVER)
    by_cat = {}
    for o in v.items:
        by_cat.setdefault(o.data["category"], []).append(o)
    assert [o.name for o in by_cat["memory"]] == ["M391A4G43MB1-CTD 40A1B2C3", "M391A4G43MB1-CTD 40A1B2C4"]
    assert by_cat["memory"][0].key == "serial:40a1b2c3" and by_cat["memory"][0].data["slot"] == "DIMMA1"
    [psu] = by_cat["psu"]
    assert psu.name == "PWS-504P-1R P504PCH12AB3456" and psu.key == "serial:p504pch12ab3456"
    assert psu.data["max_power"] == "500 W" and psu.data["make"] == "SUPERMICRO"
    assert by_cat["cpu"][0].data["cores"] == 6 and by_cat["cpu"][0].name == "pve1 Intel Xeon E-2236 CPU"
    assert all(o.data["installed_in"] == "[[pve1]]" and o.data["status"] == "in-service" for o in v.items)


def test_psu_only_in_dmi_or_only_in_fru():
    dmi_only = view(dict(SERVER, ipmi_fru=(127, "")))
    assert [o.name for o in dmi_only.items if o.data["category"] == "psu"] == ["PWS-504P-1R P504PCH12AB3456"]
    no_serial = SERVER["ipmi_fru"].replace(" Product Serial        : P504PCH12AB3456\n", "")
    dmi_free = SERVER["dmidecode"].split("Handle 0x0050")[0]
    fru_only = view(dict(SERVER, ipmi_fru=no_serial, dmidecode=dmi_free))
    [psu] = [o for o in fru_only.items if o.data["category"] == "psu"]
    assert psu.key == "psu:pve1:psu1" and psu.name == "pve1 PSU1"


def test_usb_removable_files_builtin_listed_hubs_skipped():
    v = view(SERVER)
    [usb] = [o for o in v.items if o.data["category"] == "usb"]
    assert usb.name == "ConBee II DE2412345" and usb.data["usb_id"] == "1cf1:0030"
    assert usb.key == "usb:1cf1:0030:de2412345"
    assert v.items[0].data["usb"] == [{"name": "Virtual Keyboard and Mouse", "id": "0557:9241"}]


def test_machine_firmware_gpus_and_port_speeds():
    v = view(SERVER)
    m = v.items[0].data
    assert m["bmc_firmware"] == "1.73" and m["microcode"] == "0xde" and m["tpm"] == "TPM 2.0"
    assert m["boot"] == "uefi" and m["secure_boot"] == "disabled"
    assert m["gpus"] == [{"model": "CoffeeLake-S GT2 [UHD Graphics P630]", "make": "Intel Corporation", "pci": "0000:00:02.0"}]
    [card] = [o for o in v.items if o.data["category"] == "nic"]
    assert card.data["ports"][0]["max_speed"] == "10G" and card.data["ports"][0]["firmware"].startswith("8.50")


def test_fru_output_used_even_when_ipmitool_exits_nonzero():
    v = view(dict(SERVER, ipmi_fru=(1, SERVER["ipmi_fru"]), dmidecode=SERVER["dmidecode"].split("Handle 0x0050")[0]))
    assert [o.name for o in v.items if o.data["category"] == "psu"] == ["PWS-504P-1R P504PCH12AB3456"]
    assert v.complete["psus"] is True
