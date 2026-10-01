from bastet.core.collect import parse_sections
from bastet.core.facts import extract, propose_type
from gather_fixtures import LAPTOP, VPS, stdout_for


def ex(outputs):
    return extract(parse_sections(stdout_for(outputs)))


def test_laptop_facts():
    f = ex(LAPTOP).facts
    assert f["hostname"] == "hp-13" and f["os"] == "Arch Linux"
    assert f["kernel"] == "6.16.8-arch1-1" and f["arch"] == "x86_64"
    assert f["chassis"] == "laptop" and "virtualization" not in f
    assert f["cpu"] == "Intel(R) Core(TM) i7-8565U CPU @ 1.80GHz"
    assert f["cpu_cores"] == 4 and f["cpu_threads"] == 8
    assert f["ram"] == "16 GB" and f["storage"] == "512 GB"
    assert f["interfaces"] == [{"name": "wlan0", "mac": "aa:bb:cc:dd:ee:10", "addresses": ["10.0.10.50/24"]}]
    assert f["gateway"] == "10.0.10.1"


def test_vps_facts_use_binary_storage_for_virtual_disks():
    e = ex(VPS)
    assert e.facts["os"] == "Debian GNU/Linux 13 (trixie)"
    assert e.facts["virtualization"] == "kvm" and e.facts["chassis"] == "vm"
    assert e.facts["ram"] == "4 GB" and e.facts["storage"] == "80 GB"
    assert e.facts["cpu_cores"] == 2 and e.facts["cpu_threads"] == 2
    assert e.facts["interfaces"][0]["addresses"] == ["203.0.113.10/24", "2001:db8::10/64"]


def test_type_proposals():
    assert propose_type(ex(LAPTOP)) == "laptop"
    assert propose_type(ex(VPS)) == "vps"
    pve = dict(VPS, pveversion="pve-manager/9.0.6", hostnamectl=(1, ""), chassis_type="17", virt=(1, "none"))
    assert propose_type(ex(pve)) == "proxmox-node"
    lxc = dict(VPS, hostnamectl=(1, ""), virt="lxc")
    assert propose_type(ex(lxc)) == "lxc"
    vm = dict(VPS, hostnamectl=(1, ""), virt="kvm", sys_vendor="QEMU", product_name="Standard PC")
    assert propose_type(ex(vm)) == "vm"


def test_chassis_from_smbios_when_no_hostnamectl():
    f = ex(dict(LAPTOP, hostnamectl=(1, "")))
    assert f.facts["chassis"] == "laptop"


def test_missing_tools_are_absent_not_errors():
    e = ex({"os_release": 'PRETTY_NAME="Alpine Linux v3.20"', "uname": "Linux 6.6.1 x86_64"})
    assert e.facts["os"] == "Alpine Linux v3.20"
    assert "cpu" not in e.facts and "ram" not in e.facts and "interfaces" not in e.facts
    assert set(e.missing_required) >= {"lscpu", "meminfo", "lsblk", "ip_addr"}


def test_garbage_json_is_ignored():
    e = ex(dict(LAPTOP, lscpu="{not json", lsblk="nope", ip_addr="[}"))
    assert "cpu" not in e.facts and "storage" not in e.facts and "interfaces" not in e.facts
    assert e.facts["ram"] == "16 GB"
