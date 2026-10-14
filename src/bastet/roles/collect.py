"""Collectors: a role that declares `collects: {proxy: <list option>}` receives the `proxy` exposures other hosts' roles declare.

Collection runs at planning time over declared options (every host in the inventory is scanned, unmanaged ones too);
secrets are not resolved for other hosts' values. One scan serves every host of a run, so the per-host entry point
(`collect`) and the whole-inventory one (`collect_all`) share one implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from bastet.core.errors import BastetError
from bastet.core.frontmatter import Document
from bastet.core.hosttypes import HostType
from bastet.core.hostview import host_data
from bastet.core.inventory import Inventory
from bastet.core.links import LINK
from bastet.roles.contract import SECRET_PREFIX, Option, RoleDef
from bastet.roles.resolve import Applied, resolve

SELF = "127.0.0.1"


@dataclass
class _Caddy:
    host: str
    applied: Applied
    target: str  # the list option the collected sites join
    serves: list[str]

    @property
    def key(self) -> tuple[str, str]:
        return self.host, self.applied.role.name

    @property
    def label(self) -> str:
        return f"{self.host}/{self.applied.role.name}"


@dataclass
class _Scan:
    sites: dict[tuple[str, str], list[dict]] = field(default_factory=dict)  # (host, role) -> collected sites
    errors: list[tuple[set[str], BastetError]] = field(default_factory=list)  # (hosts it concerns, error)
    warnings: dict[str, list[tuple[str, str]]] = field(default_factory=dict)  # exposing host -> (role, message)


def _note_file(applied: Applied, option: str) -> Path:
    """The note that set the option, or else the role file."""
    for source in reversed(applied.sources):
        if option in source.values:
            path = source.doc.path if source.doc else source.file
            if path is not None:
                return path
    return applied.role.path


def _has_secret(option: Option) -> bool:
    inner = option.items if option.type in ("list", "map") else None
    return option.secret or (inner is not None and _has_secret(inner)) or any(_has_secret(f) for f in option.fields.values())


def _mentions_secret(value: object) -> bool:
    if isinstance(value, str):
        return value.startswith(SECRET_PREFIX)
    if isinstance(value, dict):
        value = list(value.values())
    return isinstance(value, list) and any(_mentions_secret(v) for v in value)


def _address(data: dict) -> str | None:
    ip = str(data.get("ip") or "")
    if ip and ip.lower() != "dhcp":
        return ip
    return data.get("address") or None


def _via_targets(via: object) -> list[str]:
    items = via if isinstance(via, list) else [via]
    out = []
    for item in items:
        match = LINK.match(item.strip()) if isinstance(item, str) else None
        out.append(match.group(1).strip() if match else str(item))
    return out


class Collector:
    """Scans the inventory once and answers for every collecting role."""

    def __init__(self, inv: Inventory, types: dict[str, HostType], roles: dict[str, RoleDef]):
        self.inv, self.types, self.roles = inv, types, roles
        self._scan: _Scan | None = None

    @property
    def active(self) -> bool:
        return any(r.collects for r in self.roles.values())

    def scan(self) -> _Scan:
        if self._scan is None:
            self._scan = _Scan() if not self.active else self._run()
        return self._scan

    def _raise_for(self, host: str | None) -> None:
        for hosts, error in self.scan().errors:
            if host is None or host in hosts:
                raise error

    def sites_for(self, host: Document) -> dict[str, list[dict]]:
        """For each collecting role applied to the host, the sites it receives (empty when there are none)."""
        self._raise_for(host.name)
        scan = self.scan()
        return {role: sites for (name, role), sites in scan.sites.items() if name == host.name}

    def warnings_for(self, host: Document) -> list[tuple[str, str]]:
        return list(self.scan().warnings.get(host.name, []))

    def all(self) -> dict[tuple[str, str], list[dict]]:
        self._raise_for(None)
        return {key: list(sites) for key, sites in self.scan().sites.items()}

    # -- the scan ---------------------------------------------------------------------------------------------

    def _run(self) -> _Scan:
        scan = _Scan()
        domains = self._domains()
        caddies: list[_Caddy] = []
        exposing: list[tuple[Document, dict, Applied, int, dict]] = []
        for doc in self.inv.of_kind("host"):
            data = host_data(self.inv, doc, self.types)
            for applied in resolve(self.inv, doc, self.types, self.roles):
                role = applied.role
                if "proxy" in role.collects:
                    caddies.append(_Caddy(doc.name, applied, role.collects["proxy"], list(applied.values.get("serves") or [])))
                    scan.sites[(doc.name, role.name)] = []
                    continue
                option = role.options.get("proxy")
                if option is None:
                    continue
                self._check_option(scan, doc, applied, option)
                items = applied.values.get("proxy") or []
                exposing += [(doc, data, applied, i, item) for i, item in enumerate(items) if isinstance(item, dict)]
        for caddy in caddies:
            for scope in caddy.serves:
                if scope not in domains:
                    scan.errors.append(({caddy.host}, BastetError(
                        f"{caddy.label}: serves {scope!r}, which isn't in the lab note's domains ({self._scopes(domains)})",
                        file=_note_file(caddy.applied, "serves"), key="serves")))
        taken: dict[tuple[str, str], dict[str, str]] = {}  # per Caddy, hostname -> the source that has it
        for caddy in caddies:
            seen = taken.setdefault(caddy.key, {})
            for i, site in enumerate(caddy.applied.values.get(caddy.target) or []):
                name = self._clean(site.get("name")) if isinstance(site, dict) else None
                if name:
                    self._claim(scan, caddy, seen, name, f"{caddy.label} {caddy.target}[{i}]",
                                _note_file(caddy.applied, caddy.target), {caddy.host}, caddy.target)
        for doc, data, applied, i, item in exposing:
            self._route(scan, domains, caddies, taken, doc, data, applied, i, item)
        for sites in scan.sites.values():
            sites.sort(key=lambda s: (s["name"], s["source"]))
        return scan

    def _domains(self) -> dict:
        domains = (self.inv.lab.data.get("domains") if self.inv.lab else None) or {}
        return domains if isinstance(domains, dict) else {}

    @staticmethod
    def _scopes(domains: dict) -> str:
        return "scopes: " + ", ".join(sorted(map(str, domains))) if domains else "the lab note has no domains"

    @staticmethod
    def _clean(name: object) -> str | None:
        return str(name).strip().lower().rstrip(".") or None if isinstance(name, str) else None

    def _check_option(self, scan: _Scan, doc: Document, applied: Applied, option: Option) -> None:
        where = f"{doc.name}/{applied.role.name}"
        file = _note_file(applied, "proxy")
        if option.type != "list":
            scan.errors.append(({doc.name}, BastetError(f"{where}: proxy must be a list option", file=applied.role.path, key="proxy")))
        elif _has_secret(option) or _mentions_secret(applied.values.get("proxy")):
            scan.errors.append(({doc.name}, BastetError(
                f"{where}: proxy can't hold a secret (it is read from other hosts before secrets are resolved)",
                file=file, key="proxy")))

    def _claim(self, scan: _Scan, caddy: _Caddy, seen: dict[str, str], name: str, source: str, file: Path,
               hosts: set[str], key: str) -> bool:
        if name in seen:
            scan.errors.append(({caddy.host, *hosts}, BastetError(
                f"{caddy.label}: {name} comes from both {seen[name]} and {source}; give one of them another name "
                "(nothing wins silently)", file=file, key=key)))
            return False
        seen[name] = source
        return True

    def _route(self, scan, domains, caddies, taken, doc, data, applied, i, item) -> None:
        where = f"{doc.name}/{applied.role.name} proxy[{i}]"
        file = _note_file(applied, "proxy")

        def fail(text: str, hosts: set[str] | None = None) -> None:
            scan.errors.append(({doc.name, *(hosts or set())}, BastetError(f"{where}: {text}", file=file, key="proxy")))

        scope = item.get("domain")
        if scope is None:
            if len(domains) != 1:
                return fail(f"needs a domain, one of the lab note's {self._scopes(domains)}" if domains
                            else "the lab note has no domains: to name a site")
            scope = next(iter(domains))
        elif scope not in domains:
            return fail(f"domain {scope!r} isn't in the lab note's domains ({self._scopes(domains)})")
        sub = self._clean(item.get("subdomain"))
        if not sub:
            return fail("needs a subdomain")
        name = f"{sub}.{self._clean(domains[scope])}"
        if item.get("via") is None:
            chosen = [c for c in caddies if scope in c.serves]
            if not chosen:
                scan.warnings.setdefault(doc.name, []).append((applied.role.name, (
                    f"{where}: no Caddy serves {scope!r}, so nothing is generated for {name}")))
                return
            if len(chosen) > 1:
                return fail(f"{', '.join(c.label for c in chosen)} all serve {scope!r}; add `via:` to say which "
                            "(or both), or fix `serves`", {c.host for c in chosen})
        else:
            chosen = []
            for target in _via_targets(item["via"]):
                found = next((c for c in caddies if c.label == target), None)
                if found is None:
                    return fail(f"via {target!r} isn't a role that collects proxy (a host/role like [[vps1/caddy]], "
                                "applied to that host)")
                chosen.append(found)
        address = _address(data)
        upstream_given = item.get("upstream")
        if not upstream_given and item.get("port") is None:
            return fail("needs a port or an upstream")
        if not upstream_given and not address:
            return fail(f"{doc.name} has no address; set `upstream:` (host:port) for this exposure")
        for caddy in chosen:
            upstream = upstream_given or f"{SELF if caddy.host == doc.name else address}:{item['port']}"
            source = f"{doc.name}/{applied.role.name} proxy[{i}]"
            if self._claim(scan, caddy, taken[caddy.key], name, source, file, {doc.name}, "proxy"):
                scan.sites[caddy.key].append({**item, "name": name, "upstream": upstream, "host": doc.name, "source": source})


def collect(inv: Inventory, host: Document, types: dict[str, HostType], roles: dict[str, RoleDef],
            collector: Collector | None = None) -> dict[str, list[dict]]:
    """For each role on `host` that collects, the sites (the exposures routed to it) to add to its list option."""
    return (collector or Collector(inv, types, roles)).sites_for(host)


def collect_all(inv: Inventory, types: dict[str, HostType], roles: dict[str, RoleDef],
                collector: Collector | None = None) -> dict[tuple[str, str], list[dict]]:
    """For every collecting role instance in the inventory, keyed (host, role), the sites routed to it."""
    return (collector or Collector(inv, types, roles)).all()


def warnings_for(inv: Inventory, host: Document, types: dict[str, HostType], roles: dict[str, RoleDef],
                 collector: Collector | None = None) -> list[tuple[str, str]]:
    """(role, message) warnings about the host's own exposures that no collecting role receives."""
    return (collector or Collector(inv, types, roles)).warnings_for(host)
