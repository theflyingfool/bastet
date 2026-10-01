import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

from bastet.core.errors import BastetError
from bastet.core.yamlstyle import dump_frontmatter

TOP_KEY = re.compile(r"""^(?:"(?P<dq>[^"]+)"|'(?P<sq>[^']+)'|(?P<plain>[^\s#\-"'][^:]*?))\s*:(\s|$)""")


def _key_of(line: str) -> str | None:
    m = TOP_KEY.match(line)
    if not m:
        return None
    return m.group("dq") or m.group("sq") or m.group("plain")


@dataclass
class Document:
    path: Path
    data: dict
    body: str
    key_lines: dict[str, int]

    @property
    def name(self) -> str:
        return self.path.stem


def _fence(lines: list[str], path: Path) -> int | None:
    """Index of the closing --- line, or None when there is no frontmatter."""
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return i
    raise BastetError("frontmatter is not closed with ---", file=path, line=1)


def parse_document(text: str, path: Path) -> Document | None:
    lines = text.replace("\r\n", "\n").split("\n")
    end = _fence(lines, path)
    if end is None:
        return None
    try:
        data = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        problem = getattr(exc, "problem", None) or str(exc)
        raise BastetError(
            f"invalid YAML in frontmatter: {problem}",
            file=path,
            line=mark.line + 2 if mark is not None else 2,
        ) from None
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise BastetError("frontmatter must be a mapping of properties", file=path, line=2)
    key_lines: dict[str, int] = {}
    for i in range(1, end):
        key = _key_of(lines[i])
        if key is not None and key not in key_lines:
            key_lines[key] = i + 1
    return Document(path=path, data=data, body="\n".join(lines[end + 1 :]), key_lines=key_lines)


def _blocks(fm: list[str]) -> dict[str, tuple[int, int]]:
    """Top-level key -> (start, stop) line indexes within the frontmatter lines."""

    def continues(i: int) -> bool:
        line = fm[i]
        if line.strip() == "" or line.startswith("#"):
            for later in fm[i + 1 :]:
                if later.strip() and not later.startswith("#"):
                    return later.startswith((" ", "\t", "-"))
            return False
        return line.startswith((" ", "\t", "-"))

    blocks: dict[str, tuple[int, int]] = {}
    current: str | None = None
    start = 0
    for i, line in enumerate(fm):
        key = _key_of(line)
        if key is not None or not continues(i):
            if current is not None and current not in blocks:
                blocks[current] = (start, i)
            current = key
            start = i
    if current is not None and current not in blocks:
        blocks[current] = (start, len(fm))
    return blocks


def set_keys(text: str, updates: Mapping[str, object], path: Path) -> str:
    newline = "\r\n" if "\r\n" in text else "\n"
    text = text.replace("\r\n", "\n")
    lines = text.split("\n")
    end = _fence(lines, path)
    if end is None:
        result = "---\n" + dump_frontmatter(updates) + "---\n" + text
    else:
        fm = lines[1:end]
        for key, value in updates.items():
            new = dump_frontmatter({key: value}).rstrip("\n").split("\n")
            blocks = _blocks(fm)
            if key in blocks:
                a, b = blocks[key]
                fm[a:b] = new
            else:
                fm += new
        result = "\n".join(["---", *fm, "---", *lines[end + 1 :]])
    return result.replace("\n", newline) if newline != "\n" else result


def new_document(data: Mapping[str, object], body: str) -> str:
    return "---\n" + dump_frontmatter(data) + "---\n" + body
