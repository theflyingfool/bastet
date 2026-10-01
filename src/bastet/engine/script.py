"""Shell scripts for the engine: one batched read, and one script per fix or trigger."""

import secrets

from bastet.core.collect import PRELUDE, Probe, ProbeResult, build_script, parse_sections
from bastet.engine.model import Read

NOT_REPORTED = ProbeResult(125, "")


def new_mark() -> str:
    return f"@@BASTET-{secrets.token_hex(8)}@@"


def read_script(groups: list[tuple[Read, ...]], mark: str) -> str:
    probes = tuple(
        Probe(f"r{i}-{r.name}", r.command, r.name, root=r.root) for i, reads in enumerate(groups) for r in reads
    )
    return build_script(probes, mark)


def split_results(stdout: str, groups: list[tuple[Read, ...]], mark: str) -> list[dict[str, ProbeResult]]:
    sections = parse_sections(stdout, mark)
    return [{r.name: sections.get(f"r{i}-{r.name}", NOT_REPORTED) for r in reads} for i, reads in enumerate(groups)]


def exec_script(commands: list[str], *, root: bool, mark: str) -> str:
    """Run `commands` with `sh -e` (stop at the first failure), as root through $SUDO when asked."""
    lines = [PRELUDE]
    if root:
        lines.append('if [ "$SUDO" = none ]; then echo "needs root: sudo -n is not available" >&2; exit 126; fi')
        lines.append(f"$SUDO sh -e <<'{mark}'")
    else:
        lines.append(f"sh -e <<'{mark}'")
    lines += [*commands, mark]
    return "\n".join(lines) + "\n"
