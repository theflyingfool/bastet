import json

import pytest

from bastet.core.errors import BastetError
from bastet.core.unifi import device_facts, machine_item, parse_mca, redact
from unifi_fixtures import AP, AP_MAC, GATEWAY, GW_MAC, SWITCH


def test_parse_gateway():
    d = parse_mca(GATEWAY)
    assert (d.mac, d.model, d.firmware, d.serial) == (GW_MAC, "Gateway Fiber", "6.0.10", "1C0B8B000001")
    assert [p.id for p in d.ports] == ["1", "4", "7"] and d.ports[2].uplink and d.ports[2].media == "SFP+"
    assert [(n.local, n.chassis, n.wired) for n in d.neighbours] == [("4", AP_MAC, True)]


def test_parse_ap_uses_interface_names():
    d = parse_mca(AP)
    assert d.ports == [] and [(n.local, n.wired) for n in d.neighbours] == [("eth0", True), ("vwireap4", False)]


def test_facts_and_machine():
    d = parse_mca(SWITCH)
    assert device_facts(d) == {"mac": "02:00:00:00:00:05", "firmware": "8.8.9",
                               "ports": [{"port": "2", "name": "PoE Out + Data", "media": "2P5GE"},
                                         {"port": "8", "name": "PoE Out + Data", "media": "10GE"}]}
    m = machine_item("udb-switch", "unifi-switch", d)
    assert m.key == "serial:9041b2000005" and m.name == "Ubiquiti UDB Switch 9041B2000005"
    assert m.data["category"] == "switch" and m.data["installed_in"] == "[[udb-switch]]" and m.data["make"] == "Ubiquiti"


def test_redact():
    text = json.dumps(redact(json.loads(GATEWAY)))
    assert "SECRET-AUTHKEY" not in text and "(redacted)" in text and "inform_url" in text


def test_not_json():
    with pytest.raises(BastetError):
        parse_mca("sh: mca-dump: not found")


def test_redact_more_secret_shapes():
    data = {"snmp_community": "pub", "radius": {"servers": [{"shared": "S"}]}, "wan": {"auth": "pw"},
            "config": [{"name": "x_authkey", "value": "V"}], "blob": "mgmt.authkey=abc123\nother=1",
            "rx_bytes": 5, "max_speed": 10}
    out = json.dumps(redact(data))
    for secret in ('"pub"', '"S"', '"pw"', '"V"', "abc123"):
        assert secret not in out, secret
    assert '"rx_bytes": 5' in out and '"max_speed": 10' in out


def test_gateway_networks_skip_wan_and_down():
    d = parse_mca(GATEWAY)
    assert d.networks == [
        {"interface": "br0", "cidr": "10.10.0.0/24", "address": "10.10.0.1"},
        {"interface": "br20", "cidr": "10.10.20.0/24", "address": "10.10.20.1"},
    ]
    assert "198.51.100" not in str(device_facts(d))
