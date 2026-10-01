"""Obsidian frontmatter round-trip spike: prepare a scratch vault, then compare it with the fixture."""

import argparse
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

FIXTURE = Path(__file__).resolve().parent / "vault"
TOP_KEY = re.compile(r"^([A-Za-z_][\w-]*)\s*:")


def split_frontmatter(text: str) -> tuple[str, str]:
    text = text.replace("\r\n", "\n")
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise ValueError("no frontmatter")
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1 :])
    raise ValueError("no frontmatter")


def _blocks(fm: str) -> tuple[list[str], dict[str, str], list[str]]:
    """Top-level keys in order, raw text per key, and comment lines."""
    order: list[str] = []
    raw: dict[str, list[str]] = {}
    comments: list[str] = []
    current = None
    for line in fm.split("\n"):
        if line.strip().startswith("#"):
            comments.append(line.strip())
            continue
        m = TOP_KEY.match(line)
        if m:
            current = m.group(1)
            order.append(current)
            raw[current] = [line]
        elif current is not None:
            raw[current].append(line)
    return order, {k: "\n".join(v).rstrip() for k, v in raw.items()}, comments


@dataclass
class FileReport:
    body_changed: bool = False
    comments_lost: list[str] = field(default_factory=list)
    order_changed: bool = False
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    value_changes: dict[str, tuple[object, object]] = field(default_factory=dict)
    reformatted: list[str] = field(default_factory=list)


def compare(before: str, after: str) -> FileReport:
    fm_b, body_b = split_frontmatter(before)
    fm_a, body_a = split_frontmatter(after)
    order_b, raw_b, comments_b = _blocks(fm_b)
    order_a, raw_a, comments_a = _blocks(fm_a)
    val_b = yaml.safe_load(fm_b) or {}
    val_a = yaml.safe_load(fm_a) or {}

    r = FileReport()
    r.body_changed = body_b.strip() != body_a.strip()
    r.comments_lost = [c for c in comments_b if c not in comments_a]
    r.added = [k for k in order_a if k not in raw_b]
    r.removed = [k for k in order_b if k not in raw_a]
    common_b = [k for k in order_b if k in raw_a]
    common_a = [k for k in order_a if k in raw_b]
    r.order_changed = common_b != common_a
    for key in common_b:
        if val_b.get(key) != val_a.get(key):
            r.value_changes[key] = (val_b.get(key), val_a.get(key))
        elif raw_b[key] != raw_a[key]:
            r.reformatted.append(key)
    return r


def prepare(dest: Path) -> None:
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit(f"{dest} exists and is not empty; choose an empty or new directory")
    shutil.copytree(FIXTURE, dest, dirs_exist_ok=True)


def report(scratch: Path, pristine: Path = FIXTURE) -> str:
    out = ["# Obsidian round-trip report", ""]
    for src in sorted(pristine.rglob("*.md")):
        rel = src.relative_to(pristine).as_posix()
        dst = scratch / rel
        out.append(f"## {rel}")
        if not dst.exists():
            out += ["- missing in scratch vault", ""]
            continue
        try:
            r = compare(src.read_text(encoding="utf-8"), dst.read_text(encoding="utf-8"))
        except ValueError as exc:
            out += [f"- {exc} (in one of the two copies)", ""]
            continue
        except yaml.YAMLError as exc:
            out += [f"- invalid YAML in frontmatter: {exc}".replace("\n", " "), ""]
            continue
        out.append(f"- body changed: {r.body_changed}")
        out.append(f"- comments lost: {r.comments_lost or 'none'}")
        out.append(f"- key order changed: {r.order_changed}")
        out.append(f"- keys added: {r.added or 'none'}")
        out.append(f"- keys removed: {r.removed or 'none'}")
        out.append(f"- value changes: {r.value_changes or 'none'}")
        out.append(f"- reformatted (same value, different text): {r.reformatted or 'none'}")
        out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prepare").add_argument("dest", type=Path)
    sub.add_parser("compare").add_argument("dest", type=Path)
    args = parser.parse_args(argv)
    if args.cmd == "prepare":
        prepare(args.dest.expanduser())
        print(f"Prepared {args.dest}. Open it as a vault in Obsidian and follow spikes/obsidian/README.md.")
    else:
        print(report(args.dest.expanduser()))


if __name__ == "__main__":
    main(sys.argv[1:])
