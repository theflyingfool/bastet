from bastet.core.shell import ProbeResult, parse_sections
from bastet.core.hosttypes import load_host_types
from bastet.core.tools import install_script, needed_tools
from gather_fixtures import LAPTOP, RACK, SERVER, VPS, stdout_for

TYPES = load_host_types()


def results(outputs):
    return parse_sections(stdout_for(outputs))


def test_physical_host_missing_tools():
    r = results(dict(SERVER, dmidecode=(127, ""), lspci=(127, ""), smart=(127, "")))
    assert needed_tools(r, TYPES["proxmox-node"]) == ["dmidecode", "pciutils", "smartmontools"]


def test_ipmitool_only_when_board_has_a_bmc():
    assert needed_tools(results(RACK), TYPES["proxmox-node"]) == ["ipmitool"]
    assert needed_tools(results(dict(SERVER, ipmi=(127, ""))), TYPES["proxmox-node"]) == []


def test_virtual_hosts_get_nothing_extra():
    assert needed_tools(results(dict(VPS, dmidecode=(127, ""), lspci=(127, ""))), TYPES["vps"]) == []


def test_required_tools_on_any_host_and_denied_is_unknown():
    r = results(dict(VPS, ip_addr=(127, ""), lscpu=(127, "")))
    assert needed_tools(r, TYPES["vps"]) == ["iproute2", "util-linux"]
    denied = results(dict(SERVER, dmidecode=(126, ""), smart=(126, "")))
    assert needed_tools(denied, TYPES["proxmox-node"]) == []


def test_smartmontools_only_with_real_drives():
    import json
    blk = json.dumps({"blockdevices": [{"name": "zram0", "type": "disk", "size": 1}]})
    assert "smartmontools" not in needed_tools(results(dict(LAPTOP, smart=(127, ""), lsblk=blk)), TYPES["laptop"])


def test_install_scripts():
    apt = install_script("apt-get", ["dmidecode", "iproute2"])
    assert "apt-get install -y --no-install-recommends dmidecode iproute2" in apt and "apt-get update" in apt
    assert "pacman -S --noconfirm --needed dmidecode" in install_script("pacman", ["dmidecode"])
    assert "dnf install -y iproute" in install_script("dnf", ["iproute2"])
    assert "sudo -n" in apt
    assert install_script("unknown-pm", ["dmidecode"]) is None


def test_bmc_detected_by_bmc_graphics_or_ipmi_device():
    import json
    from gather_fixtures import RACK
    no_smbios = RACK["dmidecode"].split("Handle 0x0031")[0]
    assert needed_tools(results(dict(RACK, dmidecode=no_smbios)), TYPES["proxmox-node"]) == ["ipmitool"]
    plain = dict(RACK, dmidecode=no_smbios, lspci=RACK["lspci"].replace("ASPEED Technology, Inc. [1a03]", "Intel Corporation [8086]"))
    assert needed_tools(results(plain), TYPES["proxmox-node"]) == []
    assert needed_tools(results(dict(plain, ipmi_dev="/dev/ipmi0")), TYPES["proxmox-node"]) == ["ipmitool"]


def test_ethtool_for_physical_hosts_with_nics():
    assert "ethtool" in needed_tools(results(dict(SERVER, ethtool=(127, ""))), TYPES["proxmox-node"])
    assert "ethtool" not in needed_tools(results(dict(SERVER, ethtool=(127, ""), net_sysfs="lo\t\t\n")), TYPES["proxmox-node"])
    assert "ethtool" not in needed_tools(results(dict(VPS, ethtool=(127, ""))), TYPES["vps"])
    assert "ethtool" in install_script("pacman", ["ethtool"])
