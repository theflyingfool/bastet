import ipaddress
from collections.abc import Iterable, Mapping

from bastet.core.inventory import Inventory


def _address(text: str, net: ipaddress.IPv4Network | ipaddress.IPv6Network):
    text = text.strip()
    if text.startswith("."):
        prefix = str(net.network_address).rsplit(".", 1)[0]
        return ipaddress.ip_address(prefix + text)
    return ipaddress.ip_address(text)


def _excluded(spec: object, net) -> set[int]:
    out: set[int] = set()
    if not spec:
        return out
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        low, _, high = part.partition("-")
        start = int(_address(low, net))
        stop = int(_address(high or low, net))
        out.update(range(start, stop + 1))
    return out


def suggest_address(network: Mapping[str, object], used: Iterable[str]) -> str | None:
    net = ipaddress.ip_network(str(network["cidr"]), strict=False)
    excluded = _excluded(network.get("reserved"), net) | _excluded(network.get("dhcp"), net)
    taken = {str(u).split("/", 1)[0].strip() for u in used}
    for candidate in net.hosts():
        if int(candidate) in excluded or str(candidate) in taken:
            continue
        return str(candidate)
    return None


def _bare(value: object) -> str | None:
    text = str(value).split("/", 1)[0].strip()
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return None
    return text


def used_addresses(inventory: Inventory) -> set[str]:
    """Fixed addresses in use; `ip: dhcp` and host names are skipped."""
    values = [d.data.get("ip") for d in inventory.of_kind("host")]
    for doc in inventory.of_kind("hardware"):
        oob = doc.data.get("oob")
        if isinstance(oob, dict):
            values.append(oob.get("address"))
    return {bare for v in values if v and (bare := _bare(v))}
