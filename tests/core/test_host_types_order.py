from bastet.core.hosttypes import HostType, load_host_types

ORDER = ["computer", "server", "proxmox", "unifi", "vm", "lxc", "vps", "undefined", "other"]


def test_the_shipped_types_are_these_nine_in_this_order():
    types = load_host_types()
    assert sorted(types, key=lambda n: (types[n].order, n)) == ORDER


def test_unifi_is_one_type_and_keeps_the_gateway_networks_fact():
    types = load_host_types()
    assert not {"unifi-ap", "unifi-gateway", "unifi-switch", "laptop", "unknown"} & set(types)
    assert types["unifi"].managed is False and types["unifi"].gather is True
    assert "networks" in types["unifi"].fields


def test_a_type_without_order_sorts_last():
    assert HostType(name="x").order == 100
