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
        {"id": "qemu/106", "vmid": 106, "name": "dns", "type": "qemu", "node": "pve1", "status": "running"},
        {"id": "qemu/107", "vmid": 107, "name": "ghost", "type": "qemu", "node": "pve1", "status": "stopped"},
    ]),
}


# A board whose SMBIOS slot table is useless (root-port addresses, no PhySlot): add-in cards are told apart by
# their PCI subsystem vendor, which differs from the board's own (ASRock here).
RACK = dict(SERVER, **{
    "hostnamectl": json.dumps({"Hostname": "sanrio", "Chassis": "desktop", "HardwareVendor": "ASRockRack",
                               "HardwareModel": "1U4LW-X470"}),
    "hostname": "sanrio",
    "dmidecode": """Handle 0x0001, DMI type 1, 27 bytes
System Information
\tManufacturer: ASRockRack
\tProduct Name: 1U4LW-X470
\tSerial Number: 218000000000001

Handle 0x0002, DMI type 2, 15 bytes
Base Board Information
\tManufacturer: ASRockRack
\tProduct Name: X470D4U
\tSerial Number: 218000000000001

Handle 0x0030, DMI type 9, 17 bytes
System Slot Information
\tDesignation: J6B2
\tCurrent Usage: In Use
\tID: 0
\tBus Address: 0000:00:01.0

Handle 0x0031, DMI type 38, 18 bytes
IPMI Device Information
\tInterface Type: KCS (Keyboard Control Style)
\tBase Address: 0x0000000000000CA2 (I/O)
""",
    "lspci": (
        "Slot:\t0000:00:01.0\nClass:\tPCI bridge [0604]\nVendor:\tAdvanced Micro Devices, Inc. [AMD] [1022]\nDevice:\tFamily 17h PCIe Port [1453]\nSVendor:\tAdvanced Micro Devices, Inc. [AMD] [1022]\nSDevice:\tDevice [1453]\nDriver:\tpcieport\n\n"
        "Slot:\t0000:00:02.0\nClass:\tPCI bridge [0604]\nVendor:\tAdvanced Micro Devices, Inc. [AMD] [1022]\nDevice:\tFamily 17h PCIe Port [1453]\nSVendor:\tAdvanced Micro Devices, Inc. [AMD] [1022]\nSDevice:\tDevice [1453]\nDriver:\tpcieport\n\n"
        "Slot:\t0000:00:03.0\nClass:\tPCI bridge [0604]\nVendor:\tAdvanced Micro Devices, Inc. [AMD] [1022]\nDevice:\tFamily 17h PCIe Port [1453]\nSVendor:\tAdvanced Micro Devices, Inc. [AMD] [1022]\nSDevice:\tDevice [1453]\nDriver:\tpcieport\n\n"
        "Slot:\t0000:00:04.0\nClass:\tPCI bridge [0604]\nVendor:\tAdvanced Micro Devices, Inc. [AMD] [1022]\nDevice:\tFamily 17h PCIe Port [1453]\nSVendor:\tAdvanced Micro Devices, Inc. [AMD] [1022]\nSDevice:\tDevice [1453]\nDriver:\tpcieport\n\n"
        "Slot:\t0000:00:05.0\nClass:\tPCI bridge [0604]\nVendor:\tAdvanced Micro Devices, Inc. [AMD] [1022]\nDevice:\tFamily 17h PCIe Port [1453]\nSVendor:\tAdvanced Micro Devices, Inc. [AMD] [1022]\nSDevice:\tDevice [1453]\nDriver:\tpcieport\n\n"
        "Slot:\t0000:00:06.0\nClass:\tPCI bridge [0604]\nVendor:\tAdvanced Micro Devices, Inc. [AMD] [1022]\nDevice:\tFamily 17h PCIe Port [1453]\nSVendor:\tAdvanced Micro Devices, Inc. [AMD] [1022]\nSDevice:\tDevice [1453]\nDriver:\tpcieport\n\n"
        "Slot:\t0000:00:07.0\nClass:\tPCI bridge [0604]\nVendor:\tAdvanced Micro Devices, Inc. [AMD] [1022]\nDevice:\tFamily 17h PCIe Port [1453]\nSVendor:\tAdvanced Micro Devices, Inc. [AMD] [1022]\nSDevice:\tDevice [1453]\nDriver:\tpcieport\n\n"
        "Slot:\t0000:00:08.0\nClass:\tPCI bridge [0604]\nVendor:\tAdvanced Micro Devices, Inc. [AMD] [1022]\nDevice:\tFamily 17h PCIe Port [1453]\nSVendor:\tAdvanced Micro Devices, Inc. [AMD] [1022]\nSDevice:\tDevice [1453]\nDriver:\tpcieport\n\n"
        "Slot:\t0000:00:09.0\nClass:\tPCI bridge [0604]\nVendor:\tAdvanced Micro Devices, Inc. [AMD] [1022]\nDevice:\tFamily 17h PCIe Port [1453]\nSVendor:\tAdvanced Micro Devices, Inc. [AMD] [1022]\nSDevice:\tDevice [1453]\nDriver:\tpcieport\n\n"
        "Slot:\t0000:00:0a.0\nClass:\tPCI bridge [0604]\nVendor:\tAdvanced Micro Devices, Inc. [AMD] [1022]\nDevice:\tFamily 17h PCIe Port [1453]\nSVendor:\tAdvanced Micro Devices, Inc. [AMD] [1022]\nSDevice:\tDevice [1453]\nDriver:\tpcieport\n\n"
        "Slot:\t0000:22:00.0\nClass:\tVGA compatible controller [0300]\nVendor:\tASPEED Technology, Inc. [1a03]\n"
        "Device:\tASPEED Graphics Family [2000]\nSVendor:\tASRock Incorporation [1849]\nSDevice:\tASPEED Graphics Family [2000]\nDriver:\tast\n\n"
        "Slot:\t0000:23:00.0\nClass:\tEthernet controller [0200]\nVendor:\tIntel Corporation [8086]\n"
        "Device:\tI210 Gigabit Network Connection [1533]\nSVendor:\tASRock Incorporation [1849]\nSDevice:\tI210 Gigabit Network Connection [1533]\nDriver:\tigb\n\n"
        "Slot:\t0000:24:00.0\nClass:\tEthernet controller [0200]\nVendor:\tIntel Corporation [8086]\n"
        "Device:\tI210 Gigabit Network Connection [1533]\nSVendor:\tASRock Incorporation [1849]\nSDevice:\tI210 Gigabit Network Connection [1533]\nDriver:\tigb\n\n"
        "Slot:\t0000:25:00.0\nClass:\tSATA controller [0106]\nVendor:\tASMedia Technology Inc. [1b21]\n"
        "Device:\tASM1062 Serial ATA Controller [0612]\nSVendor:\tASRock Incorporation [1849]\nSDevice:\tMotherboard [0612]\nDriver:\tahci\n\n"
        "Slot:\t0000:2b:00.0\nClass:\tSerial Attached SCSI controller [0107]\nVendor:\tBroadcom / LSI [1000]\n"
        "Device:\tSAS2308 PCI-Express Fusion-MPT SAS-2 [0087]\nSVendor:\tBroadcom / LSI [1000]\nSDevice:\t9207-8e SAS2.1 HBA [3040]\nDriver:\tmpt3sas\n\n"
        "Slot:\t0000:2c:00.0\nClass:\tNetwork controller [0280]\nVendor:\tIntel Corporation [8086]\n"
        "Device:\tWi-Fi 6 AX200 [2723]\nSVendor:\tASRock Incorporation [1849]\nSDevice:\tWi-Fi 6 AX200 [0084]\nDriver:\tiwlwifi\n"
    ),
    "net_sysfs": "enp35s0\t\t../../../0000:23:00.0\nenp36s0\t1000\t../../../0000:24:00.0\nwlp44s0\t\t../../../0000:2c:00.0\n"
                 "enx3e7ef27dd077\t\t../../../1-14.3:2.0\nlo\t\t\nvmbr0\t10000\t\n",
    "ip_addr": json.dumps([
        {"ifname": "enp35s0", "link_type": "ether", "address": "a8:a1:59:00:00:01", "addr_info": []},
        {"ifname": "enp36s0", "link_type": "ether", "address": "a8:a1:59:00:00:02", "addr_info": []},
        {"ifname": "wlp44s0", "link_type": "ether", "address": "a8:a1:59:00:00:03", "addr_info": []},
    ]),
    "ipmi": (127, ""),
})


SERVER.update({
    "pve_guest_conf": (
        "### /etc/pve/lxc/104.conf\n"
        "net0: name=eth0,bridge=vmbr0,firewall=1,hwaddr=BC:24:11:00:01:04,ip=10.0.20.21/24,type=veth\n"
        "### /etc/pve/qemu-server/105.conf\n"
        "net0: virtio=BC:24:11:00:01:05,bridge=vmbr0,firewall=1\n"
        "### /etc/pve/qemu-server/106.conf\n"
        "net0: virtio=BC:24:11:00:01:06,bridge=vmbr0\n"
        "ipconfig0: ip=10.0.20.36/24,gw=10.0.20.1\n"
    ),
    "neigh": json.dumps([
        {"dst": "10.0.20.25", "dev": "vmbr0", "lladdr": "bc:24:11:00:01:05", "state": ["REACHABLE"]},
        {"dst": "fe80::1", "dev": "vmbr0", "lladdr": "bc:24:11:00:01:05", "state": ["STALE"]},
    ]),
})

SERVER["dmidecode"] += """
Handle 0x0050, DMI type 39, 22 bytes
System Power Supply
\tLocation: PSU1
\tName: PWS-504P-1R
\tManufacturer: SUPERMICRO
\tSerial Number: P504PCH12AB3456
\tModel Part Number: PWS-504P-1R
\tMax Power Capacity: 500 W
\tStatus: Present, OK
"""
SERVER.update({
    "ipmi_fru": (
        "FRU Device Description : Builtin FRU Device (ID 0)\n Board Mfg             : Supermicro\n"
        " Product Name          : SYS-5019C-MR\n\n"
        "FRU Device Description : PSU1 (ID 1)\n Product Manufacturer  : SUPERMICRO\n"
        " Product Name          : PWS-504P-1R\n Product Part Number   : PWS-504P-1R\n"
        " Product Serial        : P504PCH12AB3456\n"
    ),
    "ipmi_mc": "Device ID                 : 32\nFirmware Revision         : 1.73\nManufacturer Name         : Super Micro Computer Inc.\n",
    "ethtool": (
        "### eno1\nSettings for eno1:\n\tSupported ports: [ TP ]\n"
        "\tSupported link modes:   10baseT/Half 10baseT/Full\n\t                        100baseT/Half 100baseT/Full\n"
        "\t                        1000baseT/Full\n\tSupported pause frame use: Symmetric\n\tSpeed: 1000Mb/s\n"
        "#info\ndriver: igb\nfirmware-version: 3.16, 0x800004d6\n"
        "### enp1s0f0\nSettings for enp1s0f0:\n\tSupported link modes:   10000baseSR/Full\n"
        "\tSupported pause frame use: Symmetric\n#info\ndriver: i40e\nfirmware-version: 8.50 0x8000b6c5 1.3082.0\n"
        "### enp1s0f1\nSettings for enp1s0f1:\n\tSupported link modes:   10000baseSR/Full\n"
        "#info\ndriver: i40e\nfirmware-version: 8.50 0x8000b6c5 1.3082.0\n"
    ),
    "usb": (
        "1-1\t1cf1\t0030\t00\tremovable\tdresden elektronik ingenieurtechnik GmbH\tConBee II\tDE2412345\n"
        "1-2\t0bda\t5411\t09\tremovable\tGeneric\tUSB2.1 Hub\t\n"
        "usb1\t1d6b\t0002\t09\tunknown\tLinux Foundation\txHCI Host Controller\t0000:00:14.0\n"
        "1-14\t0557\t9241\t00\tfixed\tAmerican Megatrends Inc.\tVirtual Keyboard and Mouse\t\n"
    ),
    "firmware": "microcode=0xde\ntpm=2\nboot=uefi\nsecure_boot=0\n",
    "ip_link": json.dumps([
        {"ifname": "lo", "link_type": "loopback"},
        {"ifname": "eno1", "master": "vmbr0", "link_type": "ether"},
        {"ifname": "enp1s0f0", "master": "bond0", "link_type": "ether"},
        {"ifname": "enp1s0f1", "master": "bond0", "link_type": "ether"},
        {"ifname": "bond0", "linkinfo": {"info_kind": "bond", "info_data": {"mode": "802.3ad"}}},
        {"ifname": "vmbr0", "linkinfo": {"info_kind": "bridge"}},
        {"ifname": "vmbr0.20", "link": "vmbr0", "linkinfo": {"info_kind": "vlan", "info_data": {"id": 20}}},
        {"ifname": "tap101i0", "master": "vmbr0"},
        {"ifname": "docker0", "linkinfo": {"info_kind": "bridge"}},
    ]),
})

RACK["ethtool"] = ""
