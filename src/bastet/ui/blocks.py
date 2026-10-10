"""Styled lines: the report builds these, the console prints them, `.plain()` is the old string."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Line:
    text: str
    style: str | None = None


class Block:
    def __init__(self, lines: Iterable[Line] = ()) -> None:
        self.lines: list[Line] = list(lines)

    def add(self, text: str = "", style: str | None = None) -> "Block":
        self.lines.append(Line(text, style))
        return self

    def extend(self, lines: Iterable[Line]) -> "Block":
        self.lines.extend(lines)
        return self

    def plain(self) -> str:
        return "\n".join(line.text for line in self.lines) + "\n"
