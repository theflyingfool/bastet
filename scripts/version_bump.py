"""Bump the Bastet version and refresh the time zone list that ships with the time role.

Run: uv run python scripts/version_bump.py X.Y.Z [--refresh] [--check]
"""

import argparse
import hashlib
import re
import subprocess
import sys
import zoneinfo
from pathlib import Path

ROOT = Path(__file__).parents[1]
PYPROJECT = ROOT / "pyproject.toml"
ZONES_PATH = ROOT / "src" / "bastet" / "data" / "roles" / "time" / "time zones.txt"
ROLES_DIR = ROOT / "src" / "bastet" / "data" / "roles"
HASHES_PATH = ROOT / "src" / "bastet" / "data" / "role-hashes.txt"
HASHES_HEADER = "# role content hashes at the last bump; scripts/version-bump rewrites this file\n"
STAMP_PREFIX = "# refreshed for bastet "
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
LIST_CAP = 40


def _project_version_match(text: str) -> re.Match:
    section = re.search(r"^\[project\]\s*$(.*?)(?=^\[|\Z)", text, re.S | re.M)
    if not section:
        raise ValueError("no [project] section in pyproject.toml")
    match = re.search(r'^version = "([^"]*)"[ \t]*$', section.group(1), re.M)
    if not match:
        raise ValueError('no `version = "..."` line under [project]')
    return _Shifted(section.start(1), match)


class _Shifted:
    """A match inside a section, with positions given for the whole text."""

    def __init__(self, offset: int, match: re.Match):
        self.offset = offset
        self.match = match

    def group(self, n: int) -> str:
        return self.match.group(n)

    def span(self, n: int) -> tuple[int, int]:
        a, b = self.match.span(n)
        return a + self.offset, b + self.offset


def read_version(pyproject_text: str) -> str:
    return _project_version_match(pyproject_text).group(1)


def set_version(text: str, new: str, refresh: bool = False) -> str:
    if not VERSION_RE.match(new):
        raise ValueError(f"version must look like X.Y.Z (digits only), got {new!r}")
    match = _project_version_match(text)
    if match.group(1) == new and not refresh:
        raise ValueError(f"pyproject.toml already says {new}; pass --refresh to refresh the zone list anyway")
    a, b = match.span(1)
    return text[:a] + new + text[b:]


def _loadable(name: str) -> bool:
    try:
        zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError):
        return False
    return True


def _has_tzdata() -> bool:
    return bool(zoneinfo.available_timezones())


def _unloadable(zones: list[str]) -> list[str]:
    if not _has_tzdata():
        print("note: this machine has no time zone data, skipping the check that each name loads", file=sys.stderr)
        return []
    return [z for z in zones if not _loadable(z)]


def normalise_zones(lines) -> list[str]:
    zones = sorted(line.strip() for line in lines if line.strip())
    if not zones:
        raise ValueError("the zone list is empty")
    seen, dups = set(), []
    for z in zones:
        if z in seen and z not in dups:
            dups.append(z)
        seen.add(z)
    if dups:
        raise ValueError("duplicate zones: " + ", ".join(dups))
    bad = _unloadable(zones)
    if bad:
        raise ValueError("zones the system cannot load: " + ", ".join(bad))
    return zones


def render_zone_file(version: str, zones: list[str]) -> str:
    return f"{STAMP_PREFIX}{version}\n" + "".join(z + "\n" for z in zones)


def parse_zone_file(text: str) -> tuple[str, list[str]]:
    lines = text.splitlines()
    if not lines:
        return "", []
    return lines[0], [line.strip() for line in lines[1:] if line.strip()]


def diff_zones(old: list[str], new: list[str]) -> tuple[list[str], list[str]]:
    return sorted(set(new) - set(old)), sorted(set(old) - set(new))


def check_zone_file(text: str, version: str) -> list[str]:
    stamp, zones = parse_zone_file(text)
    problems = []
    if stamp != f"{STAMP_PREFIX}{version}":
        problems.append(f"the first line should be {STAMP_PREFIX}{version!s} but is {stamp!r}")
    if not zones:
        problems.append("the zone list is empty")
        return problems
    if zones != sorted(zones):
        problems.append("the zones are not sorted")
    seen: set[str] = set()
    repeated: set[str] = set()
    for z in zones:
        if z in seen:
            repeated.add(z)
        seen.add(z)
    dups = sorted(repeated)
    if dups:
        problems.append("duplicate zones: " + ", ".join(dups))
    bad = _unloadable(zones)
    if bad:
        problems.append("zones the system cannot load: " + ", ".join(bad))
    return problems


def _capped(label: str, items: list[str]) -> list[str]:
    if not items:
        return []
    out = [f"{label}:"] + [f"  {z}" for z in items[:LIST_CAP]]
    if len(items) > LIST_CAP:
        out.append(f"  and {len(items) - LIST_CAP} more")
    return out


def format_changes(added: list[str], removed: list[str], total: int) -> str:
    return "\n".join([f"{total} zones"] + _capped("added", added) + _capped("removed", removed))


def refresh_zone_file(path: Path, version: str, lines) -> tuple[list[str], list[str]]:
    """Write the zone file for `version`; return (added, removed). Bad input raises before anything is written."""
    zones = normalise_zones(lines)
    old_zones: list[str] = []
    if path.exists():
        old_zones = parse_zone_file(path.read_text(encoding="utf-8"))[1]
    added, removed = diff_zones(old_zones, zones)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not added and not removed:
        # same zones: change only the stamp, keep the zone lines byte-identical
        rest = path.read_text(encoding="utf-8").split("\n", 1)
        body = rest[1] if len(rest) > 1 else ""
        path.write_text(f"{STAMP_PREFIX}{version}\n{body}", encoding="utf-8")
    else:
        path.write_text(render_zone_file(version, zones), encoding="utf-8")
    return added, removed


def read_system_zones(timeout: int = 30) -> list[str]:
    result = subprocess.run(
        ["timedatectl", "list-timezones"], capture_output=True, text=True, timeout=timeout, check=True
    )
    return result.stdout.splitlines()


def role_hashes(roles_dir: Path) -> dict[str, str]:
    """A short hash of every file (names and bytes) in each shipped role's directory."""
    out = {}
    for d in sorted(p for p in roles_dir.iterdir() if p.is_dir() and not p.name.startswith((".", "__"))):
        h = hashlib.sha256()
        for f in sorted(p for p in d.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
            h.update(f.relative_to(d).as_posix().encode() + b"\0" + f.read_bytes() + b"\0")
        out[d.name] = h.hexdigest()[:12]
    return out


def render_hashes(hashes: dict[str, str]) -> str:
    return HASHES_HEADER + "".join(f"{name} {h}\n" for name, h in sorted(hashes.items()))


def parse_hashes(text: str) -> dict[str, str]:
    return dict(line.split(" ", 1) for line in text.splitlines() if line.strip() and not line.startswith("#"))


def changed_roles(recorded: dict[str, str], current: dict[str, str]) -> list[str]:
    return sorted(n for n in set(recorded) | set(current) if recorded.get(n) != current.get(n))


def check_hashes(hashes_path: Path, roles_dir: Path) -> list[str]:
    """Names of the roles that changed since the last bump (every role, if there is no record yet)."""
    recorded = parse_hashes(hashes_path.read_text(encoding="utf-8")) if hashes_path.exists() else {}
    return changed_roles(recorded, role_hashes(roles_dir))


def run_check(pyproject: Path, zones_path: Path, hashes_path: Path = HASHES_PATH, roles_dir: Path = ROLES_DIR) -> int:
    version = read_version(pyproject.read_text(encoding="utf-8"))
    if not zones_path.exists():
        print(f"the zone list is missing: {zones_path}", file=sys.stderr)
        return 1
    problems = check_zone_file(zones_path.read_text(encoding="utf-8"), version)
    if problems:
        for p in problems:
            print(f"{zones_path.name}: {p}", file=sys.stderr)
        print(f"run: scripts/version-bump {version} --refresh", file=sys.stderr)
        return 1
    changed = check_hashes(hashes_path, roles_dir)
    if changed:
        print("roles changed since the last bump: " + ", ".join(changed), file=sys.stderr)
        print("bump the project version (and each changed role's own version): scripts/version-bump X.Y.Z",
              file=sys.stderr)
        return 1
    print(f"time zone list and role hashes are current for bastet {version}")
    return 0


def run_bump(new: str, pyproject: Path, zones_path: Path, lines, refresh: bool = False, gen_doc: bool = True,
             hashes_path: Path = HASHES_PATH, roles_dir: Path = ROLES_DIR) -> int:
    try:
        text = pyproject.read_text(encoding="utf-8")
        new_text = set_version(text, new, refresh=refresh)
        zones = normalise_zones(lines)  # validate before writing anything
        added, removed = refresh_zone_file(zones_path, new, zones)
    except ValueError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    pyproject.write_text(new_text, encoding="utf-8")
    changed = check_hashes(hashes_path, roles_dir)
    hashes_path.write_text(render_hashes(role_hashes(roles_dir)), encoding="utf-8")
    if changed:
        print("roles changed since the last bump: " + ", ".join(changed))
    print(f"version {read_version(text)} -> {new}")
    print(format_changes(added, removed, len(zones)))
    if gen_doc:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_roles_doc.py")], check=True)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Bump the Bastet version and refresh the time zone list.")
    parser.add_argument("version", nargs="?", help="new version, X.Y.Z")
    parser.add_argument("--refresh", action="store_true", help="allow the same version (refresh the zone list only)")
    parser.add_argument("--check", action="store_true", help="write nothing; verify the zone list is current")
    args = parser.parse_args(argv)
    if args.check:
        return run_check(PYPROJECT, ZONES_PATH)
    if not args.version:
        parser.error("give the new version, X.Y.Z")
    try:
        lines = read_system_zones()
    except (OSError, subprocess.SubprocessError) as err:
        print(f"error: could not read time zones from timedatectl: {err}", file=sys.stderr)
        return 1
    return run_bump(args.version, PYPROJECT, ZONES_PATH, lines, refresh=args.refresh)


if __name__ == "__main__":
    sys.exit(main())
