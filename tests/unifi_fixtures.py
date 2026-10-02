"""Placeholder mca-dump outputs shaped like a UXG gateway, a switch and an AP (no real addresses)."""

import json

GW_MAC, AP_MAC, SW_MAC, SW_MAC2 = "02:00:00:00:00:01", "02:00:00:00:00:03", "02:00:00:00:00:05", "02:00:00:00:00:06"
HOST_MAC, GUEST_MAC = "02:00:00:00:10:01", "bc:24:11:00:00:99"

GATEWAY = json.dumps({
    "mac": GW_MAC, "model": "UXGA6AA", "model_display": "Gateway Fiber", "version": "6.0.10", "serial": "1C0B8B000001",
    "hostname": "UXGFiber", "x_authkey": "SECRET-AUTHKEY", "inform_url": "http://10.10.0.254:8080/inform",
    "if_table": [{"name": "eth0", "mac": GW_MAC}],
    "port_table": [
        {"port_idx": 1, "name": "eth0", "media": "2.5GE", "is_uplink": False, "mac_table": [{"mac": GUEST_MAC}]},
        {"port_idx": 4, "name": "eth3", "media": "2.5GE", "is_uplink": False, "mac_table": [{"mac": AP_MAC}, {"mac": HOST_MAC}]},
        {"port_idx": 7, "name": "eth6", "media": "SFP+", "is_uplink": True, "mac_table": [{"mac": "02:00:00:00:99:99"}]},
    ],
    "lldp_table": [{"chassis_id": AP_MAC, "is_wired": True, "local_port_idx": 4, "local_port_name": "eth3", "port_id": AP_MAC}],
    "network_table": [
        {"name": "eth6", "up": True, "address": "198.51.100.7/23", "mac": "02:00:00:00:00:07"},
        {"name": "br0", "up": True, "address": "10.10.0.1/24", "mac": GW_MAC},
        {"name": "br20", "up": True, "address": "10.10.20.1/24", "mac": GW_MAC},
        {"name": "dummy0", "up": False, "addresses": ["2001:db8::fa/128"]},
    ],
})
AP = json.dumps({
    "mac": AP_MAC, "model_display": "U7-Pro-XG-B", "version": "8.8.9", "serial": "847848000003", "hostname": "U7ProXG",
    "port_table": [], "if_table": [{"name": "eth0", "mac": AP_MAC}],
    "lldp_table": [
        {"chassis_id": GW_MAC, "is_wired": True, "local_port_name": "eth0", "port_id": GW_MAC},
        {"chassis_id": SW_MAC, "is_wired": False, "local_port_name": "vwireap4", "port_id": SW_MAC},
    ],
})
SWITCH = json.dumps({
    "mac": SW_MAC, "model_display": "UDB Switch", "version": "8.8.9", "serial": "9041B2000005", "hostname": "UDB Switch",
    "if_table": [{"name": "eth0", "mac": SW_MAC2}],
    "port_table": [
        {"port_idx": 2, "name": "PoE Out + Data", "media": "2P5GE", "is_uplink": False, "mac_table": [{"mac": HOST_MAC}]},
        {"port_idx": 8, "name": "PoE Out + Data", "media": "10GE", "is_uplink": False, "mac_table": []},
    ],
    "lldp_table": [{"chassis_id": AP_MAC, "is_wired": False, "local_port_name": "mld0", "port_id": AP_MAC}],
})
