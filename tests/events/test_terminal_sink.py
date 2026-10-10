import io
import time

from bastet.events.model import make_event
from bastet.events.terminal import TerminalSink
from bastet.ui import Console, use


def ev(kind, host="pve1", **data):
    return make_event(kind, "20261010-120000-ab12", time.monotonic(), host, data)


def render(level, *events):
    buf = io.StringIO()
    with use(Console(buf, io.StringIO(), color=False)):
        sink = TerminalSink(level)
        for e in events:
            sink.handle(e)
    return buf.getvalue()


ITEM = ev("item_checked", item="/etc/motd", status="would-change", phase="compare", changes=["differs → update"], error=None)
CMD = ev("command_run", phase="apply", command="printf x > /etc/motd", exit=0, duration=0.25, stdout="out line", stderr="err line", error=None, hidden=False)


def test_level_two_shows_items_and_phases_but_not_commands():
    text = render(2, ev("phase_started", phase="read"), ITEM, CMD, ev("phase_finished", phase="read", duration=0.3))
    assert "pve1: read…" in text and "pve1:   ~ /etc/motd  would-change" in text
    assert "pve1:       differs → update" in text and "read done (0.3s)" in text
    assert "$ " not in text


def test_level_three_adds_commands_with_exit_and_timing_but_no_output():
    text = render(3, CMD)
    assert "pve1:   $ printf x > /etc/motd  → exit 0 (0.2s)" in text or "(0.3s)" in text
    assert "out line" not in text


def test_level_four_adds_output():
    text = render(4, CMD)
    assert "pve1:     out line" in text and "pve1:     err line" in text


def test_compliant_items_are_level_two_so_a_level_one_view_would_hide_them():
    compliant = ev("item_checked", item="/etc/ok", status="compliant", phase="compare", changes=[], error=None)
    assert "/etc/ok" in render(2, compliant)


def test_failed_item_shows_its_error_and_a_hidden_command_shows_no_output():
    failed = ev("item_checked", item="/etc/x", status="failed", phase="apply", changes=[], error="boom")
    hidden = ev("command_run", phase="apply", command="(hidden: secret resource)", exit=1, duration=0.1, stdout="", stderr="", error=None, hidden=True)
    text = render(4, failed, hidden)
    assert "✗ /etc/x  failed" in text and "boom" in text and "(hidden: secret resource)" in text


def test_run_level_and_host_level_lines():
    text = render(
        2,
        ev("host_started", mode="apply"),
        ev("host_finished", status="ok", changed=2, failed=0, skipped=1),
        ev("host_skipped", host="media01", reason="not managed"),
        ev("trigger_fired", trigger="restart chrony", ok=False, error="no unit"),
        ev("note", host=None, message="careful"),
        ev("run_finished", host=None, status="ok", duration=12.34),
    )
    assert "pve1: apply started" in text and "pve1: ok: 2 changed · 0 failed · 1 skipped" in text
    assert "media01: skipped: not managed" in text and "trigger restart chrony ✗ no unit" in text
    assert "careful" in text and "run 20261010-120000-ab12: ok in 12.3s" in text
    assert render(2, ev("run_started", host=None, command="run", schema=1)) == ""


def test_a_sink_never_raises_on_odd_data():
    odd = ev("item_checked", item="/x", status="mystery", phase="compare", changes=None, error=None)
    assert "/x" in render(2, odd)
