from bastet.engine.model import ABSENT, FieldChange, Trigger
from bastet.engine.report import change_text, render_host, render_runs
from bastet.engine.run import HostRun, Item, TriggerRun
from engine_fakes import Flag


def item(path, status, changes=(), error=None, diff=None, origins=("lab",), secret=False):
    return Item(Flag(path=path, value="v", secret=secret), list(origins), [], status, list(changes), {}, error, diff)


def test_change_text():
    assert change_text(FieldChange("content", ABSENT, "x"), secret=False) == "(absent) → create"
    assert change_text(FieldChange("content", "old", "new"), secret=False) == "differs → update"
    assert change_text(FieldChange("state", "down", "up"), secret=False) == "state: down → up"
    assert change_text(FieldChange("password", "a", "b"), secret=True) == "password: (secret) → (secret)"


def test_check_report_full():
    run = HostRun("media01", False, [
        item("/etc/motd", "would-change", [FieldChange("content", "old", "new")], diff="-Welcome\n+media01"),
        item("/etc/ok", "compliant"),
    ])
    text = render_host(run, full=True)
    assert text.startswith("HOST: media01") and "check" in text.splitlines()[0]
    assert "Files\n  /etc/motd\n    differs → update\n      -Welcome\n      +media01\n  /etc/ok  ✓ compliant\n" in text
    assert text.rstrip().endswith("media01: 1 to change · 1 compliant · 0 failed")


def test_apply_report_collapsed_with_failure_triggers_and_origins():
    run = HostRun("media01", True, [
        item("/a", "changed", [FieldChange("value", ABSENT, "1")], origins=("lab", "media01")),
        item("/b", "failed", [FieldChange("value", ABSENT, "2")], error="boom\nsecond line"),
        item("/c", "compliant"), item("/d", "compliant"),
        item("/e", "skipped", error="no systemd on this host"),
    ], [TriggerRun(Trigger("restart chrony", "x"), True), TriggerRun(Trigger("reload x", "y"), False, "nope")])
    text = render_host(run, full=False)
    assert "  /a\n    value: (absent) → 1 ✓\n    ← lab, media01\n" in text
    assert "  /b\n    value: (absent) → 2\n    ✗ boom\n      second line\n" in text
    assert "  /e\n    – skipped (no systemd on this host)\n" in text
    assert "On change\n  restart chrony ✓\n  reload x ✗ nope\n" in text
    assert "/c, /d: compliant ✓" in text and "/c  ✓" not in text
    assert text.rstrip().endswith("media01: 1 changed · 2 compliant · 1 failed · 1 skipped")


def test_render_runs_single_full_many_collapsed_with_total():
    one = HostRun("a", True, [item("/x", "compliant")])
    two = HostRun("b", True, [item("/y", "changed", [FieldChange("value", "1", "2")])])
    assert "/x  ✓ compliant" in render_runs([one])
    many = render_runs([one, two])
    assert "/x: compliant ✓" in many and many.rstrip().endswith("all: 2 hosts · 1 changed · 0 failed")
    assert "/x  ✓ compliant" in render_runs([one, two], verbose=True)


def test_composite_content_change_text():
    assert change_text(FieldChange("/etc/apt/sources.list.d/b.sources:content", ABSENT, "desired"), secret=False) == \
        "/etc/apt/sources.list.d/b.sources: (absent) → create"
    assert change_text(FieldChange("/etc/pacman.conf:content", "current", "desired"), secret=False) == \
        "/etc/pacman.conf: differs → update"


def test_attention_marked_and_counted():
    run = HostRun("media01", False, [item("/x", "attention", [FieldChange("unaccounted", "2 packages", "none")], diff="htop\nsteam"),
                                     item("/y", "compliant")])
    text = render_host(run, full=False)
    assert "    unaccounted: 2 packages → none ⚠\n      htop\n      steam\n" in text
    assert text.rstrip().endswith("media01: 0 to change · 1 compliant · 0 failed · 1 need attention")
