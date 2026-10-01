import datetime as dt
import json
import secrets
import shlex
from dataclasses import asdict, dataclass
from pathlib import Path

MARK = "@@BASTET@@"


@dataclass(frozen=True)
class Probe:
    name: str
    command: str
    tool: str
    required: bool = False
    root: bool = False


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
    Probe("privilege", 'echo "${SUDO:-root}"', "sudo"),
    Probe(
        "pkg_mgr",
        "for m in apt-get pacman dnf zypper apk; do command -v $m >/dev/null 2>&1 && { echo $m; break; }; done",
        "package manager",
    ),
    Probe("dmidecode", "dmidecode -t 0,1,2,3,4,9,17,38,39", "dmidecode", root=True),
    Probe(
        "smart",
        "command -v smartctl >/dev/null || exit 127; printf '['; sep=''; "
        "for d in $(lsblk -dnp -o NAME,TYPE | awk '$2==\"disk\"{print $1}'); do "
        "o=$(smartctl -n standby -a -j \"$d\" 2>/dev/null); if [ -n \"$o\" ]; then printf '%s%s' \"$sep\" \"$o\"; sep=','; fi; done; printf ']'",
        "smartctl (smartmontools)",
        root=True,
    ),
    Probe("lspci", "lspci -vmm -nn -k -D", "lspci (pciutils)"),
    Probe(
        "net_sysfs",
        "for i in /sys/class/net/*; do n=${i##*/}; "
        "printf '%s\\t%s\\t%s\\n' \"$n\" \"$(cat \"$i/speed\" 2>/dev/null)\" \"$(readlink \"$i/device\" 2>/dev/null)\"; done",
        "/sys/class/net",
    ),
    Probe("ipmi", "modprobe ipmi_devintf ipmi_si 2>/dev/null; ipmitool lan print 1", "ipmitool", root=True),
    Probe("ipmi_dev", "ls -d /dev/ipmi* /sys/class/ipmi/* 2>/dev/null", "/dev/ipmi"),
    Probe("zpool", "zpool status -P", "zpool (OpenZFS)"),
    Probe("disk_ids", "ls -l /dev/disk/by-id/", "/dev/disk/by-id"),
    Probe("pve_guests", "pvesh get /cluster/resources --type vm --output-format json", "pvesh (Proxmox VE)", root=True),
    Probe(
        "pve_guest_conf",
        "for f in /etc/pve/lxc/*.conf /etc/pve/qemu-server/*.conf; do [ -f \"$f\" ] || continue; "
        "printf '### %s\\n' \"$f\"; awk '/^\\[/{exit} /^(net[0-9]+|ipconfig[0-9]+):/{print}' \"$f\"; done",
        "/etc/pve guest configs (Proxmox VE)",
        root=True,
    ),
    Probe("neigh", "ip -j neigh show", "ip (iproute2)"),
    Probe("ip_link", "ip -j -d link", "ip (iproute2)"),
    Probe("ipmi_fru", "modprobe ipmi_devintf ipmi_si 2>/dev/null; ipmitool fru print", "ipmitool", root=True),
    Probe("ipmi_mc", "modprobe ipmi_devintf ipmi_si 2>/dev/null; ipmitool mc info", "ipmitool", root=True),
    Probe(
        "ethtool",
        "command -v ethtool >/dev/null || exit 127; for i in /sys/class/net/*; do [ -e \"$i/device\" ] || continue; "
        "n=${i##*/}; printf '### %s\\n' \"$n\"; ethtool \"$n\" 2>/dev/null; printf '#info\\n'; ethtool -i \"$n\" 2>/dev/null; done",
        "ethtool",
    ),
    Probe(
        "usb",
        "for d in /sys/bus/usb/devices/*; do [ -f \"$d/idVendor\" ] || continue; "
        "printf '%s\\t%s\\t%s\\t%s\\t%s\\t%s\\t%s\\t%s\\n' \"${d##*/}\" \"$(cat \"$d/idVendor\")\" \"$(cat \"$d/idProduct\")\" "
        "\"$(cat \"$d/bDeviceClass\" 2>/dev/null)\" \"$(cat \"$d/removable\" 2>/dev/null)\" \"$(cat \"$d/manufacturer\" 2>/dev/null)\" "
        "\"$(cat \"$d/product\" 2>/dev/null)\" \"$(cat \"$d/serial\" 2>/dev/null)\"; done",
        "/sys/bus/usb",
    ),
    Probe(
        "firmware",
        "printf 'microcode=%s\\n' \"$(awk -F': ' '/^microcode/{print $2; exit}' /proc/cpuinfo)\"; "
        "printf 'tpm=%s\\n' \"$(cat /sys/class/tpm/tpm0/tpm_version_major 2>/dev/null)\"; "
        "if [ -d /sys/firmware/efi ]; then echo boot=uefi; else echo boot=bios; fi; "
        "for f in /sys/firmware/efi/efivars/SecureBoot-*; do [ -f \"$f\" ] && printf 'secure_boot=%s\\n' "
        "\"$(od -An -t u1 \"$f\" | awk '{print $NF}')\"; done",
        "/proc/cpuinfo, /sys/firmware",
    ),
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

    @property
    def denied(self) -> bool:
        return self.returncode == 126


@dataclass
class Snapshot:
    host: str
    runner: str
    taken_at: str
    results: dict[str, ProbeResult]


PRELUDE = """export LC_ALL=C
if [ "$(id -u)" = 0 ]; then SUDO=""
elif command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then SUDO="sudo -n"
else SUDO="none"; fi"""


def build_script(probes: tuple[Probe, ...] = PROBES, mark: str = MARK) -> str:
    lines = [PRELUDE]
    for p in probes:
        if p.root:
            lines.append(
                f'if [ "$SUDO" = none ]; then out=""; rc=126; '
                f"else out=$( $SUDO sh -c {shlex.quote(p.command)} 2>/dev/null ); rc=$?; fi"
            )
        else:
            lines.append(f"out=$( ( {p.command} ) 2>/dev/null ); rc=$?")
        lines += [
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
