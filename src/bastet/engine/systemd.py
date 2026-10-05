"""systemd family: units, drop-ins, time, hostname and locale.

Restarts and reloads for every role go through the triggers here, so there's one implementation.
"""

import re
import shlex
from dataclasses import dataclass
from typing import ClassVar

from bastet.engine.files import File
from bastet.engine.model import ABSENT, Read, ReadError, Resource, Trigger, Unsupported


def _q(text: str) -> str:
    return shlex.quote(text)


def _kv(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            out[key.strip()] = value.strip()
    return out


def restart(unit: str) -> Trigger:
    return Trigger(f"restart {unit}", f"systemctl restart {_q(unit)}")


def reload(unit: str) -> Trigger:
    return Trigger(f"reload {unit}", f"systemctl reload-or-restart {_q(unit)}")


def daemon_reload() -> Trigger:
    return Trigger("daemon-reload", "systemctl daemon-reload", order=10)


def drop_in(unit: str, name: str, content: str, *, restart_unit: bool = True) -> File:
    triggers = (daemon_reload(), restart(unit)) if restart_unit else (daemon_reload(),)
    return File(path=f"/etc/systemd/system/{unit}.d/{name}.conf", content=content, mode="0644", on_change=triggers)


ENABLED = {"enabled", "enabled-runtime", "static", "alias", "indirect", "generated"}
UP = {"active", "reloading", "activating"}


@dataclass(frozen=True, kw_only=True)
class Unit(Resource):
    family: ClassVar[str] = "Services"
    name: str
    enabled: bool | None = None
    state: str | None = None

    @property
    def identity(self) -> str:
        return f"unit:{self.name}"

    @property
    def label(self) -> str:
        return self.name

    def desired(self):
        return {"enabled": self.enabled, "state": self.state}

    def reads(self):
        command = (
            "command -v systemctl >/dev/null || exit 127; "
            f"systemctl show -p LoadState -p UnitFileState -p ActiveState -- {_q(self.name)}"
        )
        return (Read("show", command),)

    def current(self, results):
        r = results["show"]
        if r.missing:
            raise Unsupported("no systemd on this host")
        if not r.ok:
            raise ReadError(f"systemctl show failed (exit {r.returncode})")
        kv = _kv(r.output)
        if kv.get("LoadState") == "not-found":
            return {"exists": False, "enabled": ABSENT, "state": ABSENT}
        state_file = kv.get("UnitFileState", "")
        enabled: object = True if state_file in ENABLED else ("masked" if state_file.startswith("masked") else False)
        return {"exists": True, "enabled": enabled, "state": "up" if kv.get("ActiveState") in UP else "down"}

    def compare(self, current):
        """A unit that isn't there is already disabled and down; masked is stronger than disabled."""
        changes = super().compare(current)
        if current.get("exists") is False:
            changes = [c for c in changes if not (c.field == "enabled" and c.after is False)
                       and not (c.field == "state" and c.after == "down")]
        if current.get("enabled") == "masked":
            changes = [c for c in changes if not (c.field == "enabled" and c.after is False)]
        return changes

    def fix(self, changes, current):
        cmds = [] if current.get("exists") else ["systemctl daemon-reload"]
        for c in changes:
            if c.field == "enabled":
                cmds.append(f"systemctl {'enable' if c.after else 'disable'} {_q(self.name)}")
            elif c.field == "state":
                cmds.append(f"systemctl {'start' if c.after == 'up' else 'stop'} {_q(self.name)}")
        return cmds


@dataclass(frozen=True, kw_only=True)
class TimeSettings(Resource):
    """Timezone, NTP on/off and hardware clock through timedatectl; timezone only without systemd."""

    family: ClassVar[str] = "System"
    timezone: str | None = None
    ntp: bool | None = None
    rtc_local: bool | None = None

    @property
    def identity(self) -> str:
        return "time"

    @property
    def label(self) -> str:
        return "time"

    def desired(self):
        return {"timezone": self.timezone, "ntp": self.ntp, "rtc_local": self.rtc_local}

    def reads(self):
        return (
            Read("timedatectl", "command -v timedatectl >/dev/null || exit 127; timedatectl show"),
            Read("localtime", "readlink /etc/localtime"),
        )

    def current(self, results):
        t = results["timedatectl"]
        if t.ok:
            kv = _kv(t.output)
            return {"timezone": kv.get("Timezone") or ABSENT, "ntp": kv.get("NTP") == "yes",
                    "rtc_local": kv.get("LocalRTC") == "yes", "systemd": True}
        if self.ntp is not None or self.rtc_local is not None:
            raise Unsupported("NTP and the hardware clock need systemd's timedatectl")
        link = results["localtime"].output.strip()
        return {"timezone": link.split("zoneinfo/", 1)[1] if "zoneinfo/" in link else ABSENT, "systemd": False}

    def fix(self, changes, current):
        cmds = []
        for c in changes:
            if c.field == "timezone":
                tz = _q(str(c.after))
                if current.get("systemd"):
                    cmds.append(f"timedatectl set-timezone {tz}")
                else:
                    cmds += [f"test -e /usr/share/zoneinfo/{tz}", f"ln -sf /usr/share/zoneinfo/{tz} /etc/localtime",
                             f"printf '%s\\n' {tz} > /etc/timezone"]
            elif c.field == "ntp":
                cmds.append(f"timedatectl set-ntp {'true' if c.after else 'false'}")
            elif c.field == "rtc_local":
                cmds.append(f"timedatectl set-local-rtc {'yes' if c.after else 'no'}")
        return cmds


@dataclass(frozen=True, kw_only=True)
class Hostname(Resource):
    family: ClassVar[str] = "System"
    name: str

    @property
    def identity(self) -> str:
        return "hostname"

    @property
    def label(self) -> str:
        return "hostname"

    def desired(self):
        return {"hostname": self.name}

    def reads(self):
        return (Read("static", "cat /etc/hostname 2>/dev/null || uname -n"),)

    def current(self, results):
        lines = [line.strip() for line in results["static"].output.splitlines()]
        name = next((line for line in lines if line and not line.startswith("#")), "")
        return {"hostname": name or ABSENT}

    def fix(self, changes, current):
        n = _q(self.name)
        return [f"if command -v hostnamectl >/dev/null 2>&1; then hostnamectl set-hostname {n}; "
                f"else printf '%s\\n' {n} > /etc/hostname; hostname {n}; fi"]


@dataclass(frozen=True, kw_only=True)
class Locale(Resource):
    family: ClassVar[str] = "System"
    lang: str | None = None
    keymap: str | None = None

    @property
    def identity(self) -> str:
        return "locale"

    @property
    def label(self) -> str:
        return "locale"

    def desired(self):
        return {"lang": self.lang, "keymap": self.keymap}

    def reads(self):
        return (
            Read("localectl", "command -v localectl >/dev/null || exit 127; localectl status"),
            Read("update_locale", "for p in /usr/sbin/update-locale /usr/bin/update-locale; do "
                                  "[ -x \"$p\" ] && echo \"$p\" && exit 0; done; command -v update-locale"),
        )

    def current(self, results):
        r = results["localectl"]
        if r.missing:
            raise Unsupported("no localectl (systemd) on this host")
        if not r.ok:
            raise ReadError(f"localectl status failed (exit {r.returncode})")
        lang = re.search(r"LANG=(\S+)", r.output)
        keymap = re.search(r"VC Keymap:\s*(\S+)", r.output)
        km = keymap.group(1) if keymap else None
        # Debian forbids localectl's setters (even for root) and sets these through update-locale and console-setup.
        debian = "update_locale" in results and results["update_locale"].ok and bool(results["update_locale"].output.strip())
        if debian and self.keymap is not None:
            raise Unsupported("Debian sets the console keymap through console-setup (/etc/default/keyboard); not supported yet")
        return {"lang": lang.group(1) if lang else ABSENT, "keymap": km if km not in (None, "(unset)", "n/a") else ABSENT,
                "tool": results["update_locale"].output.strip() if debian else "localectl"}

    def fix(self, changes, current):
        cmds = []
        for c in changes:
            if c.field == "lang":
                tool = str(current.get("tool", "localectl"))
                setter = "localectl set-locale" if tool == "localectl" else _q(tool)
                cmds.append(f"{setter} {_q('LANG=' + str(c.after))}")
            elif c.field == "keymap":
                cmds.append(f"localectl set-keymap {_q(str(c.after))}")
        return cmds
