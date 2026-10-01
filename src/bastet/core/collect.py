import datetime as dt
import json
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path

MARK = "@@BASTET@@"


@dataclass(frozen=True)
class Probe:
    name: str
    command: str
    tool: str
    required: bool = False


PROBES: tuple[Probe, ...] = (
    Probe("os_release", "cat /etc/os-release", "/etc/os-release", True),
    Probe("uname", "uname -srm", "uname", True),
    Probe("hostname", "hostname 2>/dev/null || cat /etc/hostname", "hostname", True),
    Probe("hostnamectl", "hostnamectl --json=short", "hostnamectl (systemd)"),
    Probe("chassis_type", "cat /sys/class/dmi/id/chassis_type", "/sys/class/dmi"),
    Probe("sys_vendor", "cat /sys/class/dmi/id/sys_vendor", "/sys/class/dmi"),
    Probe("product_name", "cat /sys/class/dmi/id/product_name", "/sys/class/dmi"),
    Probe("virt", "systemd-detect-virt", "systemd-detect-virt (systemd)"),
    Probe(
        "container",
        "cat /run/systemd/container 2>/dev/null || tr '\\0' '\\n' < /proc/1/environ 2>/dev/null | sed -n 's/^container=//p'",
        "/run/systemd/container, /proc/1/environ",
    ),
    Probe("lscpu", "lscpu -J", "lscpu (util-linux)", True),
    Probe("meminfo", "cat /proc/meminfo", "/proc/meminfo", True),
    Probe("lsblk", "lsblk -J -b -o NAME,PATH,TYPE,SIZE,MODEL,SERIAL,ROTA,TRAN", "lsblk (util-linux)", True),
    Probe("ip_addr", "ip -j addr", "ip (iproute2)", True),
    Probe("ip_route", "ip -j route show default", "ip (iproute2)"),
    Probe("pveversion", "pveversion", "pveversion (Proxmox VE)"),
)


@dataclass
class ProbeResult:
    returncode: int
    output: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def missing(self) -> bool:
        return self.returncode == 127


@dataclass
class Snapshot:
    host: str
    runner: str
    taken_at: str
    results: dict[str, ProbeResult]


def build_script(probes: tuple[Probe, ...] = PROBES, mark: str = MARK) -> str:
    lines = ["export LC_ALL=C"]
    for p in probes:
        lines += [
            f"out=$( ( {p.command} ) 2>/dev/null ); rc=$?",
            f"printf '%s %s %s\\n' '{mark}' '{p.name}' \"$rc\"",
            "printf '%s\\n' \"$out\"",
        ]
    lines.append("exit 0")
    return "\n".join(lines) + "\n"


def parse_sections(stdout: str, mark: str = MARK) -> dict[str, ProbeResult]:
    results: dict[str, ProbeResult] = {}
    name: str | None = None
    rc = 0
    buf: list[str] = []
    for line in stdout.split("\n"):
        if line.startswith(mark + " "):
            if name is not None:
                results[name] = ProbeResult(rc, "\n".join(buf).rstrip("\n"))
            _, name, rc_text = line.split(" ", 2)
            rc = int(rc_text)
            buf = []
        elif name is not None:
            buf.append(line)
    if name is not None:
        results[name] = ProbeResult(rc, "\n".join(buf).rstrip("\n"))
    return results


def collect(runner, host: str, probes: tuple[Probe, ...] = PROBES) -> Snapshot:
    mark = f"@@BASTET-{secrets.token_hex(8)}@@"
    result = runner.run(build_script(probes, mark))
    taken = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return Snapshot(host=host, runner=runner.name, taken_at=taken, results=parse_sections(result.stdout, mark))


def save_snapshot(snapshot: Snapshot, data: Path) -> Path:
    directory = data / "snapshots" / snapshot.host
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{snapshot.taken_at.replace(':', '')}.json"
    payload = {
        "host": snapshot.host,
        "runner": snapshot.runner,
        "taken_at": snapshot.taken_at,
        "results": {k: asdict(v) for k, v in snapshot.results.items()},
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
