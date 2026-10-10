"""Security reports: read-only resources whose results land in each host's security note.

Each reads something, gives attention when it's worth a look, never changes the host, and renders its own
Markdown section (`security_section`). Running a lynis audit is a step in `apply` (cli), not a read.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import ClassVar

from bastet.engine.model import FieldChange, Read, Resource, Unsupported

LYNIS_REPORT = "/var/log/lynis-report.dat"
LYNIS_AUDIT = "lynis audit system --cronjob --quiet"


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


class _Report(Resource):
    family: ClassVar[str] = "Security"
    title: ClassVar[str] = ""
    slot: ClassVar[str] = "reports"

    def report_only(self) -> bool:
        return True

    def fix(self, changes, current):
        return []


@dataclass(frozen=True, kw_only=True)
class LynisReport(_Report):
    """The last lynis audit's result. Bastet runs audits during apply; check only reads the report."""

    title: ClassVar[str] = "Lynis"

    @property
    def identity(self) -> str:
        return "security:lynis"

    @property
    def label(self) -> str:
        return "lynis report"

    def desired(self):
        return {}

    def reads(self):
        return (Read("report", f"cat {LYNIS_REPORT} 2>/dev/null; true", root=True),)

    def current(self, results):
        warnings, suggestions, values = [], [], {}
        for line in results["report"].output.splitlines():
            key, sep, value = line.partition("=")
            if not sep:
                continue
            if key in ("warning[]", "suggestion[]"):
                parts = value.split("|")
                (warnings if key == "warning[]" else suggestions).append((parts[0], parts[1] if len(parts) > 1 else ""))
            else:
                values[key] = value
        index = values.get("hardening_index")
        return {"present": bool(values), "date": values.get("report_datetime_end", ""),
                "index": int(index) if index and index.isdigit() else None, "version": values.get("lynis_version", ""),
                "warnings": warnings, "suggestions": list(dict.fromkeys(suggestions))}

    def compare(self, current):
        if not current["present"]:
            return [FieldChange("report", "no lynis report yet (bastet run applies and runs the audit)", "a report")]
        n = len(current["warnings"])
        return [FieldChange("warnings", f"{n} warning{'s' if n != 1 else ''}", "none")] if n else []

    def diff_text(self, current):
        return "\n".join(f"{i}: {t}" for i, t in current["warnings"]) or None

    def security_section(self, current) -> str:
        if not current["present"]:
            return "## Lynis\n\nNo report yet. `bastet run` runs an audit on hosts with `lynis: true`.\n"
        out = [f"## Lynis\n\nHardening index **{current['index']}** · audited {current['date']} · lynis {current['version']}\n"]
        if current["warnings"]:
            out.append("\n### Warnings\n\n| Test | Warning |\n|---|---|\n")
            out += [f"| {_cell(i)} | {_cell(t)} |\n" for i, t in current["warnings"]]
        if current["suggestions"]:
            out.append("\n### Suggestions\n\n| Test | Suggestion |\n|---|---|\n")
            out += [f"| {_cell(i)} | {_cell(t)} |\n" for i, t in current["suggestions"]]
        return "".join(out)


TOOLS = {
    "arch-audit": ("arch-audit", "arch-audit --format '%n|%s|%c|%v'"),
    "debsecan": ("debsecan", "debsecan --suite \"$(. /etc/os-release; echo \"$VERSION_CODENAME\")\" --only-fixed --format summary"),
}
_RC = re.compile(r"^@@RC (\d+)$", re.M)
_DEBSECAN = re.compile(r"^(\S+)\s+(\S+)\s+\(([^)]*)\)")


@dataclass(frozen=True, kw_only=True)
class VulnerablePackages(_Report):
    """Installed packages with known vulnerabilities: arch-audit on Arch, debsecan (fixes available) on Debian."""

    title: ClassVar[str] = "Vulnerable packages"
    tool: str

    def __post_init__(self):
        if self.tool not in TOOLS:
            raise ValueError(f"unknown vulnerability tool {self.tool!r}")

    @property
    def identity(self) -> str:
        return "security:vulnerable-packages"

    @property
    def label(self) -> str:
        return f"vulnerable packages ({self.tool})"

    def desired(self):
        return {"tool": self.tool}

    def reads(self):
        binary, command = TOOLS[self.tool]
        return (Read("tool", f"command -v {binary} >/dev/null && echo yes; true"),
                Read("scan", f"{command} 2>&1; echo \"@@RC $?\""))

    def current(self, results):
        if results["tool"].output.strip() != "yes":
            raise Unsupported(f"{self.tool} isn't installed yet (apply installs it)")
        text = results["scan"].output
        rc = _RC.findall(text)
        if rc and rc[-1] != "0":
            lines = [line for line in _RC.sub("", text).splitlines() if line.strip()]
            raise Unsupported(f"{self.tool} scan failed: {lines[-1].strip() if lines else 'exit ' + rc[-1]}")
        packages = []
        for line in _RC.sub("", text).splitlines():
            if self.tool == "arch-audit":
                parts = line.split("|")
                if len(parts) >= 3 and parts[0]:
                    packages.append((parts[0], parts[1], parts[2], parts[3] if len(parts) > 3 else ""))
            elif m := _DEBSECAN.match(line.strip()):
                packages.append((m.group(2), m.group(3), m.group(1), ""))
        return {"installed": True, "packages": packages}

    def compare(self, current):
        names = {p[0] for p in current["packages"]}
        n = len(names)
        return [FieldChange("vulnerable", f"{n} package{'s' if n != 1 else ''} with known vulnerabilities", "none")] if n else []

    def diff_text(self, current):
        return "\n".join(f"{p[0]}: {p[2]}" for p in current["packages"][:40]) or None

    def security_section(self, current) -> str:
        if not current["packages"]:
            return f"## Vulnerable packages\n\nNone known ({self.tool}).\n"
        rows = "".join(f"| {_cell(n)} | {_cell(s)} | {_cell(c)} | {_cell(v) or '—'} |\n" for n, s, c, v in current["packages"])
        return (f"## Vulnerable packages\n\nFrom {self.tool}.\n\n| Package | Severity | Issues | Fixed in |\n"
                f"|---|---|---|---|\n{rows}")


_EXPOSURE_ROW = re.compile(r"^(\S+\.service)\s+([\d.]+)\s+(\S+)")


@dataclass(frozen=True, kw_only=True)
class ServiceExposure(_Report):
    """systemd-analyze security: how exposed each service is. Attention only for role-managed services over target."""

    title: ClassVar[str] = "Service exposure"
    managed: tuple[str, ...] = ()
    target: float = 5.0

    @property
    def identity(self) -> str:
        return "security:exposure"

    @property
    def label(self) -> str:
        return "service exposure"

    def desired(self):
        return {"managed": self.managed, "target": self.target}

    def reads(self):
        return (Read("exposure", "systemd-analyze security --no-pager --json=short 2>/dev/null "
                                 "|| systemd-analyze security --no-pager 2>/dev/null; true", root=True),)

    def current(self, results):
        text = results["exposure"].output.strip()
        units = []
        try:
            rows = json.loads(text)
            for r in rows if isinstance(rows, list) else []:
                try:
                    units.append((r["unit"], float(r["exposure"]), r["predicate"]))
                except (KeyError, TypeError, ValueError):
                    continue  # one odd row doesn't empty the report
        except json.JSONDecodeError:
            for line in text.splitlines():
                if m := _EXPOSURE_ROW.match(line):
                    units.append((m.group(1), float(m.group(2)), m.group(3)))
        return {"units": units}

    def compare(self, current):
        over = [(u, s) for u, s, _ in current["units"] if u in self.managed and s > self.target]
        return [FieldChange("exposure", f"{u} exposure {s} > {self.target}", f"≤ {self.target}") for u, s in over]

    def security_section(self, current) -> str:
        managed = [u for u in current["units"] if u[0] in self.managed]
        rest = sorted((u for u in current["units"] if u[0] not in self.managed), key=lambda u: -u[1])
        out = ["## Service exposure\n\nFrom `systemd-analyze security`: 0 is locked down, 10 fully exposed.\n"]
        if managed:
            out.append(f"\n### Services Bastet's roles run (target ≤ {self.target})\n\n| Service | Exposure | |\n|---|---|---|\n")
            out += [f"| {u} | {s} | {p} |\n" for u, s, p in managed]
        if rest:
            out.append("\n### Everything else\n\n| Service | Exposure | |\n|---|---|---|\n")
            out += [f"| {u} | {s} | {p} |\n" for u, s, p in rest]
        return "".join(out)


_SS = re.compile(r'^(\S+)\s+\S+\s+\d+\s+\d+\s+(\S+):(\d+|\*)\s+\S+(?:\s+users:\(\("([^"]+)")?')


@dataclass(frozen=True, kw_only=True)
class ListeningPorts(_Report):
    """What listens on the network (ss), and which of it no role accounts for."""

    title: ClassVar[str] = "Listening ports"
    accounted: tuple[str, ...] = ()

    @property
    def identity(self) -> str:
        return "security:listening"

    @property
    def label(self) -> str:
        return "listening ports"

    def desired(self):
        return {"accounted": self.accounted}

    def reads(self):
        return (Read("ports", "ss -H -tulpn", root=True),)

    def current(self, results):
        if results["ports"].missing:
            raise Unsupported("ss isn't installed yet (iproute2; apply installs it)")
        ports = []
        for line in results["ports"].output.splitlines():
            if m := _SS.match(line.strip()):
                proto, address, port, process = m.group(1), m.group(2).strip("[]"), m.group(3), m.group(4) or ""
                if address.startswith("127.") or address in ("::1", "localhost") or "%lo" in address:
                    continue  # loopback only: not reachable from the network
                entry = (proto, address, port, process)
                if entry not in ports:
                    ports.append(entry)
        return {"ports": ports}

    def unaccounted(self, current) -> list[tuple[str, str, str, str]]:
        """Listeners no role accounts for (by proto/port or process); one row per proto/port/process."""
        seen, out = set(), []
        for p in current["ports"]:
            if f"{p[0]}/{p[2]}" in self.accounted or p[3] in self.accounted or (p[0], p[2], p[3]) in seen:
                continue
            seen.add((p[0], p[2], p[3]))
            out.append(p)
        return out

    def compare(self, current):
        n = len(self.unaccounted(current))
        return [FieldChange("listening", f"{n} listening port{'s' if n != 1 else ''} no role accounts for", "none")] if n else []

    def diff_text(self, current):
        return "\n".join(f"{p}/{port} {proc}".strip() for p, _, port, proc in self.unaccounted(current)) or None

    def security_section(self, current) -> str:
        out = ["## Listening ports\n\nFrom `ss`; loopback-only listeners left out.\n\n| Proto | Address | Port | Process | |\n|---|---|---|---|---|\n"]
        loose = {(p, port, proc) for p, _, port, proc in self.unaccounted(current)}
        for proto, address, port, proc in current["ports"]:
            flag = "#warn unaccounted" if (proto, port, proc) in loose else ""
            out.append(f"| {proto} | {address} | {port} | {_cell(proc)} | {flag} |\n")
        return "".join(out)


@dataclass(frozen=True, kw_only=True)
class AppArmorStatus(_Report):
    """Whether AppArmor is on, and how many profiles enforce or complain. Information only."""

    title: ClassVar[str] = "AppArmor"

    @property
    def identity(self) -> str:
        return "security:apparmor"

    @property
    def label(self) -> str:
        return "AppArmor"

    def desired(self):
        return {}

    def reads(self):
        return (Read("apparmor", "cat /sys/module/apparmor/parameters/enabled 2>/dev/null || echo N; "
                                 "aa-status --json 2>/dev/null; true", root=True),)

    def current(self, results):
        lines = results["apparmor"].output.strip().splitlines()
        enabled = bool(lines) and lines[0].strip().upper().startswith("Y")
        enforce = complain = None
        if enabled and len(lines) > 1:
            try:
                profiles = json.loads("\n".join(lines[1:])).get("profiles") or {}
                enforce = sum(1 for m in profiles.values() if m == "enforce")
                complain = sum(1 for m in profiles.values() if m == "complain")
            except (json.JSONDecodeError, AttributeError):
                pass
        return {"enabled": enabled, "enforce": enforce, "complain": complain}

    def compare(self, current):
        return []

    def security_section(self, current) -> str:
        if not current["enabled"]:
            return "## AppArmor\n\nnot enabled\n"
        if current["enforce"] is None:
            return "## AppArmor\n\nEnabled · profiles not readable (aa-status missing or not permitted)\n"
        return f"## AppArmor\n\nEnabled · {current['enforce']} profiles enforcing · {current['complain']} complaining\n"


REPORTS = (LynisReport, VulnerablePackages, ServiceExposure, ListeningPorts, AppArmorStatus)
