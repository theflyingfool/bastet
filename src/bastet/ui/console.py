"""Terminal output: the one place that decides colour, width and secret masking."""

from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Iterator
from typing import IO

from rich.console import Console as RichConsole
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

    def secho(self, text: object = "", fg: str | None = None, *, err: bool = False, nl: bool = True,
              bold: bool = False) -> None:
        plain = self._text(text)
        style = " ".join(s for s in ("bold" if bold else "", fg or "") if s) or None
        self._emit(Text(plain, style=style or ""), plain, nl=nl, err=err)


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
