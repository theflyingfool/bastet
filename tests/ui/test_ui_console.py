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
    assert o.getvalue() == "  pve1  proxmox  10.1.0.15   Debian\n  git1  lxc      10.1.20.21\n"


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


def test_reveal_prints_a_secret_unmasked_while_echo_masks_it():
    ACTIVE.add("hunter2-value")
    c, o, _ = make(color=False)
    c.echo("hunter2-value")
    c.reveal("hunter2-value")
    assert o.getvalue() == "\n".join([ACTIVE.mask("hunter2-value"), "hunter2-value", ""])


from bastet.engine.model import FieldChange  # noqa: E402
from bastet.engine.report import host_block  # noqa: E402
from bastet.engine.run import HostRun, Item  # noqa: E402
from engine_fakes import Flag  # noqa: E402


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
