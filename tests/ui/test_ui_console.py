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
