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
