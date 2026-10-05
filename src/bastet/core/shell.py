"""Shared shell prelude and probe/section plumbing: build a batched probe script, run it, and split its
output back into named sections. Used by gather's own probes (core/collect.py) and by the engine's reads."""

import shlex
from dataclasses import dataclass

MARK = "@@BASTET@@"


@dataclass(frozen=True)
class Probe:
    name: str
    command: str
    tool: str
    required: bool = False
    root: bool = False


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


PRELUDE = """export LC_ALL=C
PATH="$PATH:/usr/local/sbin:/usr/sbin:/sbin"; export PATH  # Debian: ethtool, smartctl… live in sbin
if [ "$(id -u)" = 0 ]; then SUDO=""
elif command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then SUDO="sudo -n"
else SUDO="none"; fi"""


def build_script(probes: tuple[Probe, ...], mark: str = MARK) -> str:
    lines = [PRELUDE]
    for p in probes:
        if p.root:
            lines.append(
                f'if [ "$SUDO" = none ]; then out=""; rc=126; '
                f"else out=$( $SUDO sh -c {shlex.quote(p.command)} </dev/null 2>/dev/null ); rc=$?; fi"
            )
        else:
            lines.append(f"out=$( ( {p.command} ) </dev/null 2>/dev/null ); rc=$?")
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
