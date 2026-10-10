import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "bastet"
RAW = re.compile(r"\b(typer\.echo|typer\.secho|click\.echo|click\.secho)\(")
MIGRATED = ["init", "add", "app", "refresh", "doctor", "show", "common", "run", "gather", "secret", "reboot"]


def offenders(names):
    found = []
    for name in names:
        path = SRC / "cli" / f"{name}.py"
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if RAW.search(line):
                found.append(f"{path.relative_to(SRC.parent.parent)}:{n}: {line.strip()}")
    return found


def test_migrated_commands_print_through_the_console():
    assert offenders(MIGRATED) == []


def test_nothing_outside_the_ui_package_uses_raw_echo():
    found = []
    for path in SRC.rglob("*.py"):
        if "ui" in path.relative_to(SRC).parts[:1]:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if RAW.search(line):
                found.append(f"{path.relative_to(SRC.parent.parent)}:{n}")
    assert found == []
