import json

from bastet.core.collect import MARK, PROBES

LAPTOP = {
    "os_release": 'NAME="Arch Linux"\nPRETTY_NAME="Arch Linux"\nID=arch',
    "uname": "Linux 6.16.8-arch1-1 x86_64",
    "hostname": "hp-13",
    "hostnamectl": json.dumps({"Hostname": "hp-13", "Chassis": "laptop", "HardwareVendor": "HP",
                               "HardwareModel": "HP Spectre x360", "OperatingSystemPrettyName": "Arch Linux"}),
    "chassis_type": "10",
    "virt": (1, "none"),
    "lscpu": json.dumps({"lscpu": [
        {"field": "Architecture:", "data": "x86_64", "children": [{"field": "CPU op-mode(s):", "data": "32-bit, 64-bit"}]},
        {"field": "CPU(s):", "data": "8"},
        {"field": "Vendor ID:", "data": "GenuineIntel", "children": [
            {"field": "Model name:", "data": "Intel(R) Core(TM) i7-8565U CPU @ 1.80GHz", "children": [
                {"field": "Thread(s) per core:", "data": "2"},
                {"field": "Core(s) per socket:", "data": "4"},
                {"field": "Socket(s):", "data": "1"},
            ]},
        ]},
    ]}),
    "meminfo": "MemTotal:       16165428 kB\nMemFree:          123456 kB",
    "lsblk": json.dumps({"blockdevices": [
        {"name": "nvme0n1", "path": "/dev/nvme0n1", "type": "disk", "size": 512110190592,
         "model": "SAMSUNG MZVLB512HAJQ", "serial": "S4XXNX0M123456", "rota": False, "tran": "nvme"},
        {"name": "zram0", "path": "/dev/zram0", "type": "disk", "size": 4294967296},
    ]}),
    "ip_addr": json.dumps([
        {"ifname": "lo", "link_type": "loopback", "address": "00:00:00:00:00:00",
         "addr_info": [{"family": "inet", "local": "127.0.0.1", "prefixlen": 8, "scope": "host"}]},
        {"ifname": "wlan0", "link_type": "ether", "address": "aa:bb:cc:dd:ee:10",
         "addr_info": [{"family": "inet", "local": "10.0.10.50", "prefixlen": 24, "scope": "global"},
                       {"family": "inet6", "local": "fe80::1", "prefixlen": 64, "scope": "link"}]},
        {"ifname": "veth1a2b", "link_type": "ether", "address": "aa:bb:cc:dd:ee:99", "addr_info": []},
    ]),
    "ip_route": json.dumps([{"dst": "default", "gateway": "10.0.10.1", "dev": "wlan0"}]),
}

VPS = {
    "os_release": 'PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nNAME="Debian GNU/Linux"\nID=debian',
    "uname": "Linux 6.12.48+deb13-amd64 x86_64",
    "hostname": "vps1",
    "hostnamectl": json.dumps({"Hostname": "vps1", "Chassis": "vm", "HardwareVendor": "Linode",
                               "HardwareModel": "Compute Instance"}),
    "virt": "kvm",
    "lscpu": json.dumps({"lscpu": [
        {"field": "CPU(s):", "data": "2"},
        {"field": "Model name:", "data": "AMD EPYC 7713 64-Core Processor"},
        {"field": "Thread(s) per core:", "data": "1"},
        {"field": "Core(s) per socket:", "data": "2"},
        {"field": "Socket(s):", "data": "1"},
    ]}),
    "meminfo": "MemTotal:        4005284 kB",
    "lsblk": json.dumps({"blockdevices": [
        {"name": "sda", "path": "/dev/sda", "type": "disk", "size": 85899345920, "model": "QEMU HARDDISK", "rota": True},
        {"name": "sdb", "path": "/dev/sdb", "type": "disk", "size": 536870912, "model": "QEMU HARDDISK", "rota": True},
    ]}),
    "ip_addr": json.dumps([
        {"ifname": "eth0", "link_type": "ether", "address": "f2:3c:00:00:00:01",
         "addr_info": [{"family": "inet", "local": "203.0.113.10", "prefixlen": 24, "scope": "global"},
                       {"family": "inet6", "local": "2001:db8::10", "prefixlen": 64, "scope": "global"}]},
    ]),
    "ip_route": json.dumps([{"dst": "default", "gateway": "203.0.113.1", "dev": "eth0"}]),
}


def stdout_for(outputs: dict, mark: str = MARK) -> str:
    """Collector stdout as the shell script would print it; probes not in `outputs` are 'missing' (rc 127)."""
    parts = []
    for probe in PROBES:
        value = outputs.get(probe.name, (127, ""))
        rc, text = value if isinstance(value, tuple) else (0, value)
        parts.append(f"{mark} {probe.name} {rc}\n{text}\n")
    return "".join(parts)


LAPTOP.update({
    "privilege": "sudo -n",
    "dmidecode": """# dmidecode 3.6
Handle 0x0000, DMI type 0, 26 bytes
BIOS Information
\tVendor: Insyde
\tVersion: F.47
\tRelease Date: 05/12/2023

Handle 0x0001, DMI type 1, 27 bytes
System Information
\tManufacturer: HP
\tProduct Name: HP Spectre x360 Convertible 13-ae0xx
\tSerial Number: 5CD1234XYZ

Handle 0x0002, DMI type 2, 15 bytes
Base Board Information
\tManufacturer: HP
\tProduct Name: 83BB
\tSerial Number: To Be Filled By O.E.M.

Handle 0x0004, DMI type 4, 48 bytes
Processor Information
\tSocket Designation: U3E1
\tStatus: Populated, Enabled
\tVersion: Intel(R) Core(TM) i7-8565U CPU @ 1.80GHz
\tCore Count: 4
\tThread Count: 8

Handle 0x0011, DMI type 17, 40 bytes
Memory Device
\tSize: 16384 MB
\tLocator: Onboard
\tType: LPDDR3
\tSpeed: 2133 MT/s
\tSerial Number: 00000000
\tPart Number: Not Specified
""",
    "smart": json.dumps([{
        "device": {"name": "/dev/nvme0n1", "protocol": "NVMe"},
        "model_name": "SAMSUNG MZVLB512HAJQ-000H1", "serial_number": "S4XXNX0M123456",
        "firmware_version": "EXH7301Q", "smart_status": {"passed": True},
        "nvme_total_capacity": 512110190592,
    }]),
    "lspci": "Slot:\t0000:00:02.0\nClass:\tVGA compatible controller [0300]\nVendor:\tIntel Corporation [8086]\n"
             "Device:\tWhiskeyLake-U GT2 [UHD Graphics 620] [3ea0]\nDriver:\ti915\n\n"
             "Slot:\t0000:02:00.0\nClass:\tNetwork controller [0280]\nVendor:\tIntel Corporation [8086]\n"
             "Device:\tWireless-AC 9560 [9df0]\nDriver:\tiwlwifi\n",
    "net_sysfs": "lo\t\t\nwlan0\t\t../../../0000:02:00.0\n",
    "disk_ids": "lrwxrwxrwx 1 root root 13 Oct  1 10:00 nvme-SAMSUNG_MZVLB512HAJQ-000H1_S4XXNX0M123456 -> ../../nvme0n1\n",
})

SERVER = {
    "privilege": "sudo -n",
    "os_release": 'PRETTY_NAME="Debian GNU/Linux 13 (trixie)"',
    "uname": "Linux 6.14.8-2-pve x86_64",
    "hostname": "pve1",
    "hostnamectl": json.dumps({"Hostname": "pve1", "Chassis": "server", "HardwareVendor": "Supermicro",
                               "HardwareModel": "SYS-5019C-MR"}),
    "virt": (1, "none"),
    "pveversion": "pve-manager/9.0.6/49c767b70aeb6648 (running kernel: 6.14.8-2-pve)",
    "lscpu": json.dumps({"lscpu": [
        {"field": "CPU(s):", "data": "12"}, {"field": "Model name:", "data": "Intel(R) Xeon(R) E-2236 CPU @ 3.40GHz"},
        {"field": "Core(s) per socket:", "data": "6"}, {"field": "Socket(s):", "data": "1"},
    ]}),
    "meminfo": "MemTotal:       65703464 kB",
    "lsblk": json.dumps({"blockdevices": [
        {"name": "sda", "path": "/dev/sda", "type": "disk", "size": 4000787030016, "model": "WDC WD40EFRX-68N32N0",
         "serial": "WD-WCC4E1234567", "rota": True, "tran": "sata"},
        {"name": "sdb", "path": "/dev/sdb", "type": "disk", "size": 4000787030016, "model": "WDC WD40EFRX-68N32N0",
         "serial": "WD-WCC4E7654321", "rota": True, "tran": "sata"},
        {"name": "nvme0n1", "path": "/dev/nvme0n1", "type": "disk", "size": 1000204886016,
         "model": "Samsung SSD 970 EVO Plus 1TB", "serial": "S4EWNX0R123456", "rota": False, "tran": "nvme"},
        {"name": "zd0", "path": "/dev/zd0", "type": "disk", "size": 34359738368},
        {"name": "sdc", "path": "/dev/sdc", "type": "disk", "size": 32000000000, "model": "USB DISK",
         "serial": "USB123", "rota": False, "tran": "usb"},
    ]}),
    "ip_addr": json.dumps([
        {"ifname": "eno1", "link_type": "ether", "address": "3c:ec:ef:00:00:01", "addr_info": []},
        {"ifname": "enp1s0f0", "link_type": "ether", "address": "3c:fd:fe:00:00:10", "addr_info": []},
        {"ifname": "enp1s0f1", "link_type": "ether", "address": "3c:fd:fe:00:00:11", "addr_info": []},
        {"ifname": "vmbr0", "link_type": "ether", "address": "3c:ec:ef:00:00:01",
         "addr_info": [{"family": "inet", "local": "10.0.10.11", "prefixlen": 24, "scope": "global"}]},
    ]),
    "ip_route": json.dumps([{"dst": "default", "gateway": "10.0.10.1", "dev": "vmbr0"}]),
    "dmidecode": """# dmidecode 3.6
Handle 0x0000, DMI type 0, 26 bytes
BIOS Information
\tVendor: American Megatrends Inc.
\tVersion: 3.4
\tRelease Date: 03/21/2023

Handle 0x0001, DMI type 1, 27 bytes
System Information
\tManufacturer: Supermicro
\tProduct Name: SYS-5019C-MR
\tSerial Number: S123456X

Handle 0x0002, DMI type 2, 15 bytes
Base Board Information
\tManufacturer: Supermicro
\tProduct Name: X11SCM-F
\tSerial Number: ZM12345678

Handle 0x0003, DMI type 3, 22 bytes
Chassis Information
\tManufacturer: Supermicro
\tType: Rack Mount Chassis
\tSerial Number: C123456789

Handle 0x0004, DMI type 4, 48 bytes
Processor Information
\tSocket Designation: CPU
\tStatus: Populated, Enabled
\tVersion: Intel(R) Xeon(R) E-2236 CPU @ 3.40GHz
\tCore Count: 6
\tThread Count: 12

Handle 0x0009, DMI type 9, 17 bytes
System Slot Information
\tDesignation: CPU SLOT6 PCI-E 3.0 X16
\tCurrent Usage: In Use
\tID: 6
\tBus Address: 0000:01:00.0

Handle 0x000A, DMI type 9, 17 bytes
System Slot Information
\tDesignation: PCH SLOT4 PCI-E 3.0 X4
\tCurrent Usage: Available
\tBus Address: 0000:ff:00.0

Handle 0x0011, DMI type 17, 40 bytes
Memory Device
\tSize: 32 GB
\tLocator: DIMMA1
\tType: DDR4
\tSpeed: 2666 MT/s
\tSerial Number: 40A1B2C3
\tPart Number: M391A4G43MB1-CTD    

Handle 0x0012, DMI type 17, 40 bytes
Memory Device
\tSize: No Module Installed
\tLocator: DIMMA2
\tType: Unknown

Handle 0x0013, DMI type 17, 40 bytes
Memory Device
\tSize: 32 GB
\tLocator: DIMMB1
\tType: DDR4
\tSpeed: 2666 MT/s
\tSerial Number: 40A1B2C4
\tPart Number: M391A4G43MB1-CTD

Handle 0x0014, DMI type 17, 40 bytes
Memory Device
\tSize: No Module Installed
\tLocator: DIMMB2
\tType: Unknown
""",
    "smart": json.dumps([
        {"device": {"name": "/dev/sda"}, "model_name": "WDC WD40EFRX-68N32N0", "serial_number": "WD-WCC4E1234567",
         "firmware_version": "82.00A82", "smart_status": {"passed": True}, "rotation_rate": 5400,
         "user_capacity": {"bytes": 4000787030016}},
        {"device": {"name": "/dev/sdb"}, "model_name": "WDC WD40EFRX-68N32N0", "serial_number": "WD-WCC4E7654321",
         "firmware_version": "82.00A82", "smart_status": {"passed": True}, "rotation_rate": 5400,
         "user_capacity": {"bytes": 4000787030016}},
        {"device": {"name": "/dev/nvme0n1"}, "model_name": "Samsung SSD 970 EVO Plus 1TB",
         "serial_number": "S4EWNX0R123456", "firmware_version": "2B2QEXM7", "smart_status": {"passed": True},
         "nvme_total_capacity": 1000204886016},
        {"device": {"name": "/dev/zd0"}, "smartctl": {"exit_status": 1}},
    ]),
    "lspci": (
        "Slot:\t0000:00:02.0\nClass:\tVGA compatible controller [0300]\nVendor:\tIntel Corporation [8086]\n"
        "Device:\tCoffeeLake-S GT2 [UHD Graphics P630] [3e96]\nDriver:\ti915\n\n"
        "Slot:\t0000:00:17.0\nClass:\tSATA controller [0106]\nVendor:\tIntel Corporation [8086]\n"
        "Device:\tCannon Lake PCH SATA AHCI Controller [a352]\nDriver:\tahci\n\n"
        "Slot:\t0000:01:00.0\nClass:\tEthernet controller [0200]\nVendor:\tIntel Corporation [8086]\n"
        "Device:\tEthernet Controller X710 for 10GbE SFP+ [1572]\nSVendor:\tIntel Corporation [8086]\n"
        "SDevice:\tEthernet Converged Network Adapter X710-2 [0007]\nPhySlot:\t6\nRev:\t02\nDriver:\ti40e\n\n"
        "Slot:\t0000:01:00.1\nClass:\tEthernet controller [0200]\nVendor:\tIntel Corporation [8086]\n"
        "Device:\tEthernet Controller X710 for 10GbE SFP+ [1572]\nPhySlot:\t6\nDriver:\ti40e\n\n"
        "Slot:\t0000:03:00.0\nClass:\tEthernet controller [0200]\nVendor:\tIntel Corporation [8086]\n"
        "Device:\tI210 Gigabit Network Connection [1533]\nDriver:\tigb\n"
    ),
    "net_sysfs": "eno1\t1000\t../../../0000:03:00.0\nenp1s0f0\t10000\t../../../0000:01:00.0\n"
                 "enp1s0f1\t-1\t../../../0000:01:00.1\nlo\t\t\nvmbr0\t\t\n",
    "ipmi": "Set in Progress         : Set Complete\nIP Address Source       : Static Address\n"
            "IP Address              : 10.0.10.9\nSubnet Mask             : 255.255.255.0\n"
            "MAC Address             : 3c:ec:ef:00:00:09\n",
    "zpool": """  pool: tank
 state: ONLINE
config:

\tNAME                                                              STATE     READ WRITE CKSUM
\ttank                                                              ONLINE       0     0     0
\t  mirror-0                                                        ONLINE       0     0     0
\t    /dev/disk/by-id/ata-WDC_WD40EFRX-68N32N0_WD-WCC4E1234567-part1  ONLINE       0     0     0
\t    /dev/disk/by-id/ata-WDC_WD40EFRX-68N32N0_WD-WCC4E7654321-part1  ONLINE       0     0     0

errors: No known data errors
""",
    "disk_ids": (
        "lrwxrwxrwx 1 root root  9 Oct  1 10:00 ata-WDC_WD40EFRX-68N32N0_WD-WCC4E1234567 -> ../../sda\n"
        "lrwxrwxrwx 1 root root 10 Oct  1 10:00 ata-WDC_WD40EFRX-68N32N0_WD-WCC4E1234567-part1 -> ../../sda1\n"
        "lrwxrwxrwx 1 root root  9 Oct  1 10:00 ata-WDC_WD40EFRX-68N32N0_WD-WCC4E7654321 -> ../../sdb\n"
        "lrwxrwxrwx 1 root root 10 Oct  1 10:00 ata-WDC_WD40EFRX-68N32N0_WD-WCC4E7654321-part1 -> ../../sdb1\n"
        "lrwxrwxrwx 1 root root 13 Oct  1 10:00 nvme-Samsung_SSD_970_EVO_Plus_1TB_S4EWNX0R123456 -> ../../nvme0n1\n"
    ),
    "pve_guests": json.dumps([
        {"id": "lxc/104", "vmid": 104, "name": "git1", "type": "lxc", "node": "pve1", "status": "running"},
        {"id": "qemu/105", "vmid": 105, "name": "media", "type": "qemu", "node": "pve1", "status": "stopped"},
    ]),
}
