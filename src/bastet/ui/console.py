"""Terminal output: the one place that decides colour, width and secret masking."""

from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Iterator
from typing import IO

from rich.console import Console as RichConsole
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from bastet.core.secrets.redact import ACTIVE
from bastet.ui.blocks import Block


class Console:
    """`typer.echo`/`typer.secho`-compatible output. Plain text unless the stream is a colour terminal."""

    def __init__(self, stdout: IO[str] | None = None, stderr: IO[str] | None = None, *,
                 color: bool | None = None, width: int | None = None) -> None:
        self._stdout, self._stderr = stdout, stderr
        self._color = color
        self.width = width
        self._rich: dict[bool, tuple[IO[str], RichConsole]] = {}

    def _stream(self, err: bool) -> IO[str]:
        return (self._stderr or sys.stderr) if err else (self._stdout or sys.stdout)

    def _use_color(self, stream: IO[str]) -> bool:
        if self._color is not None:
            return self._color
        if os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
            return False
        isatty = getattr(stream, "isatty", None)
        return bool(isatty and isatty())

    def _rich_for(self, err: bool) -> RichConsole:
        stream = self._stream(err)
        cached = self._rich.get(err)
        if cached is None or cached[0] is not stream:
            console = RichConsole(file=stream, force_terminal=True, highlight=False, markup=False, emoji=False,
                                  color_system="auto" if getattr(stream, "isatty", lambda: False)() else "standard",
                                  width=self.width)
            cached = self._rich[err] = (stream, console)
        return cached[1]

    @staticmethod
    def _text(value: object) -> str:
        return ACTIVE.mask("" if value is None else str(value))

    def _emit(self, rich_text: Text | None, plain: str, *, nl: bool, err: bool) -> None:
        stream = self._stream(err)
        if rich_text is not None and self._use_color(stream):
            self._rich_for(err).print(rich_text, end="\n" if nl else "", soft_wrap=True)
        else:
            stream.write(plain + ("\n" if nl else ""))
        stream.flush()

    def echo(self, text: object = "", *, nl: bool = True, err: bool = False) -> None:
        self._emit(None, self._text(text), nl=nl, err=err)

    def reveal(self, text: object) -> None:
        """Print a value unmasked. For the one place a secret is meant to be seen (`secret show`)."""
        stream = self._stream(False)
        stream.write(("" if text is None else str(text)) + "\n")
        stream.flush()

    def secho(self, text: object = "", fg: str | None = None, *, err: bool = False, nl: bool = True,
              bold: bool = False) -> None:
        plain = self._text(text)
        style = " ".join(s for s in ("bold" if bold else "", fg or "") if s) or None
        self._emit(Text(plain, style=style or ""), plain, nl=nl, err=err)

    def diff(self, text: str) -> None:
        plain = self._text(text)
        rich_text = Text()
        for line in plain.splitlines(keepends=True):
            rich_text.append(line, style=_diff_style(line))
        self._emit(rich_text, plain, nl=True, err=False)

    def table(self, rows: list[list[str]], *, indent: str = "  ") -> None:
        if not rows:
            return
        cells = [[self._text(c) for c in row] for row in rows]
        stream = self._stream(False)
        if not self._use_color(stream):
            widths = [max(len(r[i]) for r in cells) for i in range(len(cells[0]))]
            for r in cells:
                stream.write(indent + "  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() + "\n")
            stream.flush()
            return
        table = Table(box=None, show_header=False, show_edge=False, pad_edge=False, padding=(0, 2, 0, 0))
        for i, _ in enumerate(cells[0]):
            table.add_column(no_wrap=i == 0, overflow="fold")
        for r in cells:
            table.add_row(*[Text(c) for c in r])
        self._rich_for(False).print(Padding(table, (0, 0, 0, len(indent))))
        stream.flush()

    def block(self, block: Block) -> None:
        plain = self._text(block.plain())
        rich_text = Text()
        for i, line in enumerate(block.lines):
            if i:
                rich_text.append("\n")
            rich_text.append(self._text(line.text), style=line.style or "")
        rich_text.append("\n")
        self._emit(rich_text, plain, nl=True, err=False)


def _diff_style(line: str) -> str:
    if line.startswith(("+++", "---")):
        return "bold"
    if line.startswith("@@"):
        return "cyan"
    if line.startswith("+"):
        return "green"
    if line.startswith("-"):
        return "red"
    return ""


_default = Console()
_current = _default


@contextlib.contextmanager
def use(console: Console) -> Iterator[Console]:
    """Pin `console` as the one `out` writes to (tests)."""
    global _current
    previous, _current = _current, console
    try:
        yield console
    finally:
        _current = previous


class _Out:
    """`out.echo(...)`: whatever console is current, looked up at call time."""

    def __getattr__(self, name: str):
        return getattr(_current, name)


out = _Out()

__all__ = ["Block", "Console", "out", "use"]
