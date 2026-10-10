# Console output, plan 1: console primitives — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this repo, the `bastet-run-plan` skill supplies the Bastet-specific parts.

**Goal:** every command prints through one `bastet.ui` console that adds colour, width-aware tables and coloured diffs on a terminal, and prints exactly what it prints today when piped or under test.

**Architecture:** a small `bastet/ui/` package. `out` is a module-level proxy to a `Console` that has `typer.echo`/`typer.secho`-compatible `echo` and `secho` (so migrating ~180 call sites is mechanical), plus `diff`, `table` and `block`. Plain mode (not a TTY, `NO_COLOR`, `TERM=dumb`) writes the text unchanged; colour mode builds Rich `Text` objects (never markup strings). The run report is rebuilt as a `Block` of styled lines whose `.plain()` equals today's string. No events yet (that is plan 2).

**Tech Stack:** Python ≥3.12, Rich (already a dependency), Typer, pytest.

**Spec:** `docs/specs/2026-10-10-bastet-console-output-design.md`, "Plan 1: console primitives". Out of scope here, and left for plans 2 and 3: events, JSONL, run notes, the `-vv`/`-vvv`/`-vvvv` display levels, the Runs Bases.

**Roadmap:** `docs/ROADMAP.md`, milestone 3b. This plan runs before roles subplan 2.

## Global Constraints

- **Plain mode is byte-compatible with today's output.** No ANSI escapes, no boxes, no re-wrapping. The existing tests must keep passing with no edits to their expected text, except where a task says so. `CliRunner` and `capsys` have no TTY, so they get plain mode.
- **Colour only on a real terminal:** the stream is a TTY, `NO_COLOR` is unset or empty, and `TERM` is not `dumb`. Tests that need colour pass `color=True` explicitly.
- **Rich `Text` objects only, never markup strings.** Host names, `[[wiki links]]` and `[bold]` in data must print literally.
- **Secret masking is applied inside the console** (`bastet.core.secrets.redact.ACTIVE`). Existing explicit `mask(...)` calls may stay (masking is idempotent).
- **Errors and warnings to stderr, results to stdout,** exactly as today. Prompts (`typer.prompt`, `typer.confirm`) stay on Typer.
- **Unit tests** never touch the real inventory, `~/.config/bastet`, `~/.local/share/bastet`, `~/.ssh`, the real `~/.cache` or `$XDG_RUNTIME_DIR`; no network; `tmp_path` only; placeholder data only (see "Example data" in `docs/ROADMAP.md`).
- **Commit trailer:**
  ```
  Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01DBkyXRsdxwovkRErg9n9wt
  ```
  Stage by name, never `git commit -a`. The privacy pre-commit hook runs on every commit.
- **Each task:** failing tests first and seen failing, then implement, then the task's tests green. The user runs the full suite; run only the files a task names.

## Review Focus

1. **A secret value in any printed text is masked** in plain and colour modes: echo, diff, table cell, block line, stderr.
2. **No escapes when colour is off,** even for styled calls: `NO_COLOR=1`, `TERM=dumb`, and piped output on a stream that is not a TTY.
3. **The console follows the current `sys.stdout`/`sys.stderr`.** Under `CliRunner` and `capsys` the streams are swapped after import; output must land in the swapped stream.
4. **Markup-looking data prints literally in colour mode:** `[red]x[/red]`, `[[Bastet guide]]`, `[/]`.
5. **Odd input:** `echo(None)`, a non-`str` message, an empty table, empty cells, a very narrow width (20), and a `Block` with no lines.

## File structure

| File | Responsibility |
|---|---|
| `src/bastet/ui/__init__.py` | exports `out`, `Console`, `Block`, `Line`, `use` |
| `src/bastet/ui/blocks.py` | `Line` and `Block`: styled lines with a `.plain()` that matches today's strings |
| `src/bastet/ui/console.py` | `Console`, the `out` proxy, `use()` for tests |
| `src/bastet/engine/report.py` | gains `host_block`; `render_host` becomes `host_block(...).plain()` |
| `tests/ui/test_ui_console.py` | console, diff, table, block tests |
| `tests/test_no_raw_echo.py` | guard: no `typer.echo`/`typer.secho`/`click.echo` outside `bastet/ui` |

---

### Task 1: The console: `echo`, `secho`, masking, colour detection

**Files:**
- Create: `src/bastet/ui/__init__.py`, `src/bastet/ui/blocks.py`, `src/bastet/ui/console.py`
- Test: `tests/ui/test_ui_console.py`

**Interfaces:**
- Produces:
  - `Console(stdout=None, stderr=None, *, color: bool | None = None, width: int | None = None)` — `None` streams mean "the current `sys.stdout`/`sys.stderr`, looked up at each call".
  - `Console.echo(text="", *, nl=True, err=False)`
  - `Console.secho(text="", fg: str | None = None, *, err=False, nl=True, bold=False)`
  - `out`: proxy to the current console. `use(console)`: context manager that pins a console (tests).
  - `Line(text: str, style: str | None = None)` and `Block(lines=())` with `.add(text="", style=None)`, `.extend(lines)`, `.plain() -> str` (`"\n".join(texts) + "\n"`).

- [ ] **Step 1: Write the failing tests**

Create `tests/ui/test_ui_console.py`:

```python
import io
import re

import pytest

from bastet.core.secrets.redact import ACTIVE
from bastet.ui import Block, Console, out, use

ANSI = re.compile(r"\x1b\[[0-9;]*m")


class Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


def make(color=None, width=None, tty=False):
    cls = Tty if tty else io.StringIO
    o, e = cls(), cls()
    return Console(o, e, color=color, width=width), o, e


def test_plain_mode_writes_exactly_what_typer_echo_wrote():
    c, o, e = make(color=False)
    c.echo("hello")
    c.echo("x", nl=False)
    c.secho("warn", fg="red", bold=True)
    c.echo("bad", err=True)
    c.echo()
    assert o.getvalue() == "hello\nxwarn\n\n"
    assert e.getvalue() == "bad\n"


def test_colour_mode_styles_secho_and_leaves_echo_alone():
    c, o, _ = make(color=True)
    c.secho("warn", fg="red")
    c.echo("plain")
    assert "\x1b[31m" in o.getvalue()
    assert ANSI.sub("", o.getvalue()) == "warn\nplain\n"
    assert "\x1b" not in o.getvalue().split("\n")[1]


@pytest.mark.parametrize("env", [{"NO_COLOR": "1"}, {"TERM": "dumb"}])
def test_no_escapes_when_colour_is_off_even_on_a_tty(monkeypatch, env):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    c, o, _ = make(tty=True)
    c.secho("warn", fg="red")
    assert o.getvalue() == "warn\n"


def test_a_tty_gets_colour_by_default(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm")
    c, o, _ = make(tty=True)
    c.secho("warn", fg="red")
    assert "\x1b[" in o.getvalue()


def test_markup_looking_text_prints_literally():
    c, o, _ = make(color=True)
    for text in ("[red]x[/red]", "see [[Bastet guide]]", "[/]", "[bold]"):
        c.secho(text, fg="yellow")
    assert ANSI.sub("", o.getvalue()).splitlines() == ["[red]x[/red]", "see [[Bastet guide]]", "[/]", "[bold]"]


def test_secrets_are_masked_in_both_modes_and_on_stderr():
    ACTIVE.add("hunter2-value")
    for color in (False, True):
        c, o, e = make(color=color)
        c.echo("pw is hunter2-value")
        c.secho("pw is hunter2-value", fg="red", err=True)
        assert "hunter2-value" not in o.getvalue() + e.getvalue()


def test_none_and_non_strings_are_accepted():
    c, o, _ = make(color=False)
    c.echo(None)
    c.echo(42)
    assert o.getvalue() == "\n42\n"


def test_the_console_follows_the_current_streams(capsys):
    out.echo("to stdout")
    out.secho("to stderr", err=True)
    seen = capsys.readouterr()
    assert (seen.out, seen.err) == ("to stdout\n", "to stderr\n")


def test_use_pins_a_console_and_restores_the_default():
    c, o, _ = make(color=False)
    with use(c):
        out.echo("pinned")
    assert o.getvalue() == "pinned\n"


def test_block_plain_matches_a_joined_string():
    b = Block().add("HOST: pve1").add("").add("done", "green")
    assert b.plain() == "HOST: pve1\n\ndone\n"
    assert Block().plain() == "\n"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/ui/test_ui_console.py -q`
Expected: collection error, `No module named 'bastet.ui'`.

- [ ] **Step 3: Implement**

`src/bastet/ui/blocks.py`:

```python
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
```

`src/bastet/ui/console.py`:

```python
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
```

`src/bastet/ui/__init__.py`:

```python
from bastet.ui.blocks import Block, Line
from bastet.ui.console import Console, out, use

__all__ = ["Block", "Console", "Line", "out", "use"]
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/ui/test_ui_console.py -q`
Expected: all pass. If `test_colour_mode_styles_secho_and_leaves_echo_alone` shows an escape on the plain `echo` line, `echo` must not go through Rich: keep `_emit(None, ...)`.

- [ ] **Step 5: Commit**

```bash
git add src/bastet/ui/__init__.py src/bastet/ui/blocks.py src/bastet/ui/console.py tests/ui/test_ui_console.py
git commit -m "ui: console with echo/secho, colour detection and masking"
```

---

### Task 2: Diffs, tables and blocks on the console

**Files:**
- Modify: `src/bastet/ui/console.py`
- Test: `tests/ui/test_ui_console.py`

**Interfaces:**
- Consumes: Task 1's `Console`, `Block`, `Line`.
- Produces:
  - `Console.diff(text: str)` — prints a unified diff; in colour mode `+` green, `-` red, `@@` cyan, `+++`/`---` bold. Plain mode equals `echo(text)`.
  - `Console.table(rows: list[list[str]], *, indent: str = "  ")` — plain mode is the aligned-column text `show` prints today (columns padded with `ljust`, joined by two spaces, right-stripped, prefixed with `indent`). Colour mode is a borderless Rich table that shrinks and wraps to the width. An empty `rows` prints nothing.
  - `Console.block(block: Block)` — plain mode equals `echo(block.plain())`.

- [ ] **Step 1: Write the failing tests** (append to `tests/ui/test_ui_console.py`)

```python
DIFF = "--- a/x.md\n+++ b/x.md\n@@ -1 +1 @@\n-old\n+new\n context\n"


def test_diff_is_unchanged_in_plain_mode_and_coloured_in_colour_mode():
    c, o, _ = make(color=False)
    c.diff(DIFF)
    assert o.getvalue() == DIFF + "\n"  # echo semantics: the trailing newline stays, echo adds one
    c, o, _ = make(color=True)
    c.diff(DIFF)
    lines = o.getvalue().split("\n")
    assert "\x1b[32m" in lines[4] and "new" in lines[4]  # + green
    assert "\x1b[31m" in lines[3] and "old" in lines[3]  # - red
    assert "\x1b[36m" in lines[2]                         # @@ cyan
    assert ANSI.sub("", o.getvalue()) == DIFF + "\n"


def test_diff_masks_secrets():
    ACTIVE.add("s3cret-token")
    c, o, _ = make(color=True)
    c.diff("+token: s3cret-token\n")
    assert "s3cret-token" not in o.getvalue()


ROWS = [["pve1", "proxmox", "10.1.0.15", "Debian"], ["git1", "lxc", "10.1.20.21", ""]]


def test_plain_table_matches_the_old_show_output():
    c, o, _ = make(color=False)
    c.table(ROWS)
    assert o.getvalue() == "  pve1  proxmox  10.1.0.15  Debian\n  git1  lxc      10.1.20.21\n"


def test_empty_table_prints_nothing():
    for color in (False, True):
        c, o, _ = make(color=color)
        c.table([])
        assert o.getvalue() == ""


@pytest.mark.parametrize("width", [20, 40, 80])
def test_coloured_table_fits_the_width(width):
    c, o, _ = make(color=True, width=width)
    c.table([["pve1", "proxmox", "10.1.0.15", "Debian GNU/Linux 13 (trixie) with a very long description"], ["", "", "", ""]])
    assert all(len(ANSI.sub("", line)) <= width for line in o.getvalue().splitlines())
    assert "pve1" in o.getvalue()


def test_table_cells_with_markup_text_print_literally():
    c, o, _ = make(color=True, width=60)
    c.table([["[[Bastet guide]]", "[red]x[/red]"]])
    text = ANSI.sub("", o.getvalue())
    assert "[[Bastet guide]]" in text and "[red]x[/red]" in text


def test_block_prints_styled_lines_and_plain_is_echo_of_plain():
    b = Block().add("HOST: pve1", "bold").add("  /etc/motd ✗ failed", "red").add("")
    c, o, _ = make(color=False)
    c.block(b)
    assert o.getvalue() == b.plain() + "\n"
    c, o, _ = make(color=True)
    c.block(b)
    assert "\x1b[31m" in o.getvalue() and ANSI.sub("", o.getvalue()) == b.plain() + "\n"


def test_empty_block_and_masked_block():
    c, o, _ = make(color=False)
    c.block(Block())
    assert o.getvalue() == "\n\n"
    ACTIVE.add("hunter2-value")
    c, o, _ = make(color=True)
    c.block(Block().add("pw hunter2-value", "red"))
    assert "hunter2-value" not in o.getvalue()
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/ui/test_ui_console.py -q`
Expected: the new tests fail with `AttributeError: 'Console' object has no attribute 'diff'` (and `table`, `block`).

- [ ] **Step 3: Implement**

In `src/bastet/ui/console.py` add the imports `from rich.padding import Padding` and `from rich.table import Table`, then add these methods to `Console`:

```python
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
```

and at module level:

```python
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
```

Note for the empty block: `Block().plain()` is `"\n"` and `echo` adds one more, so the plain output is `"\n\n"`, matching `test_empty_block_and_masked_block`.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/ui/test_ui_console.py -q`
Expected: all pass. If the width-20 table test fails because Rich keeps a column wider than the console, add `no_wrap=False` and `overflow="fold"` to `Table.add_column` for each column before adding rows.

- [ ] **Step 5: Commit**

```bash
git add src/bastet/ui/console.py tests/ui/test_ui_console.py
git commit -m "ui: coloured diffs, width-fitting tables, styled blocks"
```

---

### Task 3: The run report as a styled block

**Files:**
- Modify: `src/bastet/engine/report.py`
- Test: `tests/engine/test_report.py`

**Interfaces:**
- Consumes: `bastet.ui.Block`, `bastet.ui.Line`.
- Produces: `host_block(run: HostRun, *, full: bool) -> Block`. `render_host(run, *, full)` keeps its signature and returns `host_block(run, full=full).plain()`; `render_runs` is unchanged.

Styles: the `HOST:` header and each family name `bold`; a compliant item line `dim`; an item's change lines `green` (status `changed`), `yellow` (`would-change`, `attention`); failed lines `red`; skipped lines `dim`; diff lines by their first character (`+` green, `-` red, `@@` cyan, otherwise default); the `On change` list `green` for ok and `red` for failed triggers; the summary line `red` if anything failed, else `green` if anything changed or would change, else `dim`.

- [ ] **Step 1: Write the failing tests** (append to `tests/engine/test_report.py`)

```python
from bastet.engine.report import host_block


def test_block_plain_is_the_old_render_host_text_exactly():
    run = HostRun("media01", True, [
        item("/a", "changed", [FieldChange("value", ABSENT, "1")]),
        item("/b", "failed", [FieldChange("value", ABSENT, "2")], error="boom\nsecond line"),
        item("/c", "compliant"),
        item("/e", "skipped", error="no systemd on this host"),
    ])
    for full in (True, False):
        assert host_block(run, full=full).plain() == render_host(run, full=full)


def test_block_styles_follow_status():
    run = HostRun("media01", False, [
        item("/m", "would-change", [FieldChange("content", "old", "new")], diff="@@ -1 +1 @@\n-old\n+new"),
        item("/f", "failed", [FieldChange("value", ABSENT, "2")], error="boom"),
        item("/c", "compliant"),
    ])
    styles = {line.text.strip(): line.style for line in host_block(run, full=True).lines}
    assert styles["differs → update"] == "yellow"
    assert styles["@@ -1 +1 @@"] == "cyan" and styles["-old"] == "red" and styles["+new"] == "green"
    assert styles["✗ boom"] == "red"
    assert styles["/c  ✓ compliant"] == "dim"
    assert host_block(run, full=True).lines[0].style == "bold"
    assert host_block(run, full=True).lines[-1].style == "red"  # the summary: something failed
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/engine/test_report.py -q`
Expected: `ImportError: cannot import name 'host_block'`.

- [ ] **Step 3: Implement**

In `src/bastet/engine/report.py` add `from bastet.ui import Block, Line`, replace `_item_lines` and `render_host`:

```python
_CHANGE_STYLE = {"changed": "green", "would-change": "yellow", "attention": "yellow"}


def _diff_line_style(line: str) -> str | None:
    if line.startswith("@@"):
        return "cyan"
    if line.startswith("+"):
        return "green"
    if line.startswith("-"):
        return "red"
    return None


def _item_lines(item: Item) -> list[Line]:
    label = item.resource.label
    if item.status == "compliant":
        return [Line(f"  {label}  ✓ compliant", "dim")]
    lines = [Line(f"  {label}")]
    tick = " ✓" if item.status == "changed" else (" ⚠" if item.status == "attention" else "")
    style = _CHANGE_STYLE.get(item.status)
    lines += [Line(f"    {change_text(c, secret=item.resource.secret)}{tick}", style) for c in item.changes]
    if item.status == "failed":
        for n, line in enumerate((item.error or "failed").splitlines()):
            lines.append(Line(f"    ✗ {line}" if n == 0 else f"      {line}", "red"))
    elif item.status == "skipped":
        lines.append(Line(f"    – skipped ({item.error})", "dim"))
    if item.diff:
        lines += [Line(f"      {line}", _diff_line_style(line)) for line in item.diff.splitlines()]
    if len(item.origins) > 1:
        lines.append(Line(f"    ← {', '.join(item.origins)}", "dim"))
    return lines


def host_block(run: HostRun, *, full: bool) -> Block:
    block = Block().add(f"{'HOST: ' + run.host:<38}{'applied' if run.applied else 'check'}", "bold").add("")
    families = list(FAMILIES) + sorted({i.resource.family for i in run.items} - set(FAMILIES))
    collapsed: list[str] = []
    for family in families:
        shown: list[Line] = []
        for item in run.items:
            if item.resource.family != family:
                continue
            if item.status == "compliant" and not full:
                collapsed.append(item.resource.label)
                continue
            shown += _item_lines(item)
        if shown:
            block.add(family, "bold").extend(shown).add("")
    if run.triggers:
        block.add("On change", "bold")
        for t in run.triggers:
            block.add(f"  {t.trigger.label} ✓" if t.ok else f"  {t.trigger.label} ✗ {t.error}", "green" if t.ok else "red")
        block.add("")
    if collapsed:
        block.add(f"{', '.join(collapsed)}: compliant ✓", "dim").add("")
    summary_style = "red" if run.count("failed") else ("green" if run.count("changed") or run.count("would-change") else "dim")
    block.add(summary(run), summary_style)
    return block


def render_host(run: HostRun, *, full: bool) -> str:
    return host_block(run, full=full).plain()
```

(`summary` is unchanged.)

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/engine/test_report.py -q`
Expected: the new tests pass and every existing test in the file still passes unmodified.

- [ ] **Step 5: Commit**

```bash
git add src/bastet/engine/report.py tests/engine/test_report.py
git commit -m "report: build host reports as styled blocks; plain text unchanged"
```

---

### Task 4: Migrate the everyday commands

**Files:**
- Modify: `src/bastet/cli/init.py`, `add.py`, `app.py`, `refresh.py`, `doctor.py`, `show.py`, `common.py`
- Test: `tests/test_no_raw_echo.py` (created here, finished in Task 5), existing CLI tests

**Interfaces:**
- Consumes: `bastet.ui.out` (Tasks 1–2).

- [ ] **Step 1: Write the failing guard test**

Create `tests/test_no_raw_echo.py`:

```python
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "bastet"
RAW = re.compile(r"\b(typer\.echo|typer\.secho|click\.echo|click\.secho)\(")
MIGRATED = ["init", "add", "app", "refresh", "doctor", "show", "common"]


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
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_no_raw_echo.py -q`
Expected: FAIL, listing the raw call sites in the seven files.

- [ ] **Step 3: Migrate mechanically, then by hand where the console has a better primitive**

```bash
for f in init add app refresh doctor show common; do
  sed -i -E 's/\btyper\.(echo|secho)\(/out.\1(/g' src/bastet/cli/$f.py
done
```

In each of the seven files add `from bastet.ui import out` with the other `bastet` imports (alphabetical position). Then three hand edits:

1. `common.py` (`write_with_confirmation`) and `init.py` (the `render_diff(Change(homelab_path, ...))` line): `out.echo(render_diff(...))` becomes `out.diff(render_diff(...))`.
2. `show.py`: delete the local `_table` function and replace the loop in `_show_hosts` with `out.table(_host_rows(inv, types, hosts))`.
3. `common.py` (`handles_errors`): `out.secho(ACTIVE.mask(f"error: {exc}"), fg="red", err=True)` keeps working; leave the explicit mask.

Keep `import typer` in each file (options, prompts, `typer.Exit`). The `bold=True` in `common.py`'s upstream-secrets alert is supported by `secho`.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_no_raw_echo.py tests/ui tests/cli/test_show.py tests/cli/test_doctor_cli.py tests/cli/test_add.py tests/cli/test_add_role.py tests/cli/test_init.py tests/cli/test_refresh.py tests/cli/test_common.py tests/cli/test_finish.py -q`
Expected: all pass with no edits to any existing test. A failure in a `capsys` test means a call site was missed or `err=True` was dropped.

- [ ] **Step 5: Commit**

```bash
git add src/bastet/cli/init.py src/bastet/cli/add.py src/bastet/cli/app.py src/bastet/cli/refresh.py src/bastet/cli/doctor.py src/bastet/cli/show.py src/bastet/cli/common.py tests/test_no_raw_echo.py
git commit -m "cli: everyday commands print through the console; diffs and show tables use the primitives"
```

---

### Task 5: Migrate run, gather and secret

**Files:**
- Modify: `src/bastet/cli/run.py`, `gather.py`, `secret.py`, `reboot.py`
- Test: `tests/test_no_raw_echo.py`, existing CLI tests

**Interfaces:**
- Consumes: `out`, `host_block` (Task 3).

- [ ] **Step 1: Extend the guard test**

In `tests/test_no_raw_echo.py` replace the `MIGRATED` list and add a whole-tree test:

```python
MIGRATED = ["init", "add", "app", "refresh", "doctor", "show", "common", "run", "gather", "secret", "reboot"]


def test_nothing_outside_the_ui_package_uses_raw_echo():
    found = []
    for path in SRC.rglob("*.py"):
        if "ui" in path.relative_to(SRC).parts[:1]:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if RAW.search(line):
                found.append(f"{path.relative_to(SRC.parent.parent)}:{n}")
    assert found == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_no_raw_echo.py -q`
Expected: FAIL listing `run.py`, `gather.py`, `secret.py`, `reboot.py` call sites (and any other file the whole-tree test finds).

- [ ] **Step 3: Migrate**

```bash
for f in run gather secret reboot; do
  sed -i -E 's/\btyper\.(echo|secho)\(/out.\1(/g' src/bastet/cli/$f.py
done
```

Add `from bastet.ui import out` to each. Then by hand in `run.py`: import `host_block` (`from bastet.engine.report import host_block, render_host` — keep `render_host` only if still used) and replace the three report prints:

```python
out.echo(ctx.secrets.redactor.mask(render_host(check, full=full)))   # becomes
out.block(host_block(check, full=full))
```

(same for the two `render_host(done, full=full)` prints). The parallel replay loops (`for text, fg in outcome.log.lines: out.secho(ACTIVE.mask(text), fg=fg)` in `run.py` `_print_outcome_log`, and the two in `gather.py`) work unchanged after the rename. The "Changes to apply" list in `_choose_hosts` stays as `out.echo` lines (it is a numbered list, not a table). `secret.py` keeps its `rich.progress.Progress` bar as it is.

If the whole-tree test lists any other file, apply the same `sed` and import to it.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_no_raw_echo.py tests/engine/test_report.py tests/cli/test_run_cli.py tests/cli/test_check_apply.py tests/cli/test_apply_parallel.py tests/cli/test_gather.py tests/cli/test_gather_parallel.py tests/cli/test_gather_unifi.py tests/cli/test_reboot.py tests/cli/test_secret.py tests/cli/test_secret_leaks.py tests/cli/test_secret_leak_in_diff.py tests/cli/test_secret_pull_alert.py tests/cli/test_secret_audit.py tests/cli/test_ssh_port.py -q`
Expected: all pass with no edits to any existing test.

- [ ] **Step 5: Commit**

```bash
git add src/bastet/cli/run.py src/bastet/cli/gather.py src/bastet/cli/secret.py src/bastet/cli/reboot.py tests/test_no_raw_echo.py
git commit -m "cli: run, gather and secret print through the console; reports use styled blocks"
```

(Add any other file the guard test pointed at to the `git add`.)

---

### Task 6: Width snapshots, a real-terminal check and docs

**Files:**
- Test: `tests/ui/test_ui_console.py`
- Modify: `docs/ROADMAP.md`, `src/bastet/data/docs/troubleshooting.md`

- [ ] **Step 1: Write the width snapshot tests** (append to `tests/ui/test_ui_console.py`)

```python
from bastet.engine.model import ABSENT, FieldChange
from bastet.engine.report import host_block
from bastet.engine.run import HostRun
from engine_fakes import Flag
from bastet.engine.run import Item


def _run():
    def it(path, status, changes=(), error=None, diff=None):
        return Item(Flag(path=path, value="v", secret=False), ["lab"], [], status, list(changes), {}, error, diff)

    return HostRun("pve1", False, [
        it("/etc/motd", "would-change", [FieldChange("content", "old", "new")], diff="@@ -1 +1 @@\n-old\n+new"),
        it("/etc/bad", "failed", error="boom"),
        it("/etc/ok", "compliant"),
    ])


@pytest.mark.parametrize("width", [60, 80, 120])
def test_a_host_report_is_stable_at_common_widths(width):
    c, o, _ = make(color=True, width=width)
    c.block(host_block(_run(), full=True))
    plain = ANSI.sub("", o.getvalue())
    assert plain == host_block(_run(), full=True).plain() + "\n"  # soft wrap: the terminal wraps, Bastet never reflows
    assert "\x1b[31m" in o.getvalue() and "\x1b[33m" in o.getvalue() and "\x1b[1m" in o.getvalue()
```

- [ ] **Step 2: Run to verify they pass** (they pin behaviour built in Tasks 1–3)

Run: `uv run pytest tests/ui -q`
Expected: all pass.

- [ ] **Step 3: Check it on a real terminal**

Use the `run-bastet` skill's sandbox. In a terminal, run `bastet show`, `bastet run -c` against a host that would change, and `bastet add host demo1 --type vps --provider linode --ip 203.0.113.9` (answer `n` at `Write?`). Confirm: coloured diff, host report coloured by status, `show` table fits when you narrow the window, and `bastet show | cat` and `NO_COLOR=1 bastet show` print no escapes. Report anything that looks wrong rather than fixing it silently.

- [ ] **Step 4: Update the docs**

- `docs/ROADMAP.md`: in "Run logs (milestone 3b)", mark the console primitives (colour, width-fitting tables, coloured diffs, status marks) as done and point at `docs/specs/2026-10-10-bastet-console-output-design.md`; plans 2 (events and JSONL) and 3 (run notes) stay not started. Under "Now", state that the next plan is plan 2.
- `src/bastet/data/docs/troubleshooting.md`: one short paragraph: Bastet colours output on a terminal; `NO_COLOR=1` turns it off; piped output is always plain.

- [ ] **Step 5: Commit**

```bash
git add tests/ui/test_ui_console.py docs/ROADMAP.md src/bastet/data/docs/troubleshooting.md
git commit -m "ui: width snapshot tests; roadmap and troubleshooting docs"
```
