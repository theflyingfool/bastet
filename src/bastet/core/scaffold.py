import re
from dataclasses import dataclass

from bastet.core.addressing import suggest_address, used_addresses
from bastet.core.changes import Change
from bastet.core.errors import BastetError
from bastet.core.frontmatter import new_document
from bastet.core.hosttypes import HostType
from bastet.core.inventory import HARDWARE_STATUSES, Inventory, markdown_files
from bastet.core.links import make_link
from bastet.core.views import HARDWARE_SECTION, HARDWARE_SUMMARY_SECTION, HOST_SUMMARY_SECTION

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]*$")
OPTION_FOR = {"ip": "--ip", "runs_on": "--on", "provider": "--provider"}


@dataclass
class HostDraft:
    change: Change
    suggested_ip: str | None


def _check_name(inv: Inventory, name: str) -> None:
    if not NAME.match(name):
        raise BastetError(f"'{name}': names may contain letters, digits, spaces, '.', '_' and '-'")
    existing = inv.get(name)
    if existing is not None:
        raise BastetError(f"'{name}' already exists", file=existing.path)
    for path in markdown_files(inv.root):
        if path.stem.lower() == name.lower():
            raise BastetError(f"a note named '{path.stem}' already exists; pick another name", file=path)


def _require(inv: Inventory, name: str, kind: str, option: str) -> None:
    doc = inv.get(name)
    if doc is None or doc.data.get("bastet") != kind:
        raise BastetError(f"{option} {name}: no {kind} named '{name}' in the inventory")


def suggested_ip(inv: Inventory, network: str) -> str:
    """Next free address in a lab network; raises if the network is unknown or full."""
    networks = (inv.lab.data.get("networks") or {}) if inv.lab else {}
    if network not in networks:
        have = ", ".join(sorted(networks)) or "none"
        raise BastetError(f"--network {network}: not in the lab file's networks (have: {have})")
    address = suggest_address(networks[network], used_addresses(inv))
    if address is None:
        raise BastetError(f"no free address left in network '{network}'")
    return address


def new_host(
    inv: Inventory,
    types: dict[str, HostType],
    name: str,
    type_name: str,
    *,
    ip: str | None = None,
    on: str | None = None,
    network: str | None = None,
    location: str | None = None,
    provider: str | None = None,
    address: str | None = None,
    connection: str | None = None,
) -> HostDraft:
    _check_name(inv, name)
    if type_name not in types:
        raise BastetError(f"unknown host type '{type_name}' (known: {', '.join(sorted(types))})")
    data: dict[str, object] = {"bastet": "host", "cssclasses": ["bastet-host"], "type": type_name}
    if provider:
        data["provider"] = provider
    if on:
        _require(inv, on, "host", "--on")
        data["runs_on"] = make_link(inv.get(on).name)
    if location:
        _require(inv, location, "location", "--location")
        data["location"] = make_link(inv.get(location).name)
    used = used_addresses(inv)
    suggested = None
    if network:
        data["network"] = network
        if ip is None:
            suggested = suggested_ip(inv, network)
            ip = suggested
        else:
            suggested_ip(inv, network)
    if ip:
        if ip.split("/", 1)[0] in used:
            raise BastetError(f"address {ip} is already used in the inventory")
        data["ip"] = ip
    if address:
        data["address"] = address
    if connection:
        data["connection"] = connection
    missing = [f for f in types[type_name].minimal if f not in data]
    if missing:
        needs = ", ".join(f"{f} ({OPTION_FOR.get(f, '--' + f)})" for f in missing)
        raise BastetError(f"host type '{type_name}' needs {needs}")
    path = inv.root / "hosts" / f"{name}.md"
    body = f"# {name}\n" + HOST_SUMMARY_SECTION + (HARDWARE_SECTION if types[type_name].physical else "")
    return HostDraft(Change(path, None, new_document(data, body)), suggested)


def new_hardware(
    inv: Inventory,
    name: str,
    category: str,
    *,
    model: str | None = None,
    serial: str | None = None,
    size: str | None = None,
    installed_in: str | None = None,
    location: str | None = None,
    status: str | None = None,
) -> Change:
    _check_name(inv, name)
    status = status or ("in-service" if installed_in else "spare")
    if status not in HARDWARE_STATUSES:
        raise BastetError(f"status '{status}' is not one of: {', '.join(HARDWARE_STATUSES)}")
    data: dict[str, object] = {"bastet": "hardware", "category": category}
    for key, value in (("model", model), ("serial", serial), ("size", size)):
        if value:
            data[key] = value
    data["status"] = status
    if installed_in:
        _require(inv, installed_in, "host", "--in")
        data["installed_in"] = make_link(inv.get(installed_in).name)
    if location:
        _require(inv, location, "location", "--location")
        data["location"] = make_link(inv.get(location).name)
    path = inv.root / "hardware" / f"{name}.md"
    return Change(path, None, new_document(data, f"# {name}\n" + HARDWARE_SUMMARY_SECTION))
