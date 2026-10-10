import time

from bastet.core.secrets.redact import ACTIVE
from bastet.events.model import Event, make_event
from bastet.events.runnote import infer_mode, note_name, render_run_note, summarize


def ev(kind, host=None, **data):
    return make_event(kind, "20261010-121800-22d326", time.monotonic() - 2, host, data).to_dict()


def apply_run():
    return [
        ev("run_started", command="run -a pve1", schema=1, mode="apply", user="alice"),
        ev("host_started", "pve1", mode="apply"),
        ev("phase_started", "pve1", phase="compare"),
        ev("item_checked", "pve1", item="/etc/motd", status="would-change", phase="compare", changes=["differs → update"], error=None),
        ev("item_checked", "pve1", item="/etc/ok", status="compliant", phase="compare", changes=[], error=None),
        ev("phase_finished", "pve1", phase="compare", duration=0.1),
        ev("phase_started", "pve1", phase="apply"),
        ev("command_run", "pve1", phase="apply", command="printf x > /etc/motd", exit=0, duration=0.25,
           stdout="wrote it", stderr="", error=None, hidden=False),
        ev("item_checked", "pve1", item="/etc/motd", status="changed", phase="apply", changes=["differs → update"], error=None),
        ev("item_checked", "pve1", item="/etc/bad", status="failed", phase="apply", changes=[], error="boom"),
        ev("phase_finished", "pve1", phase="apply", duration=0.4),
        ev("host_finished", "pve1", status="failed", changed=1, failed=1, skipped=0),
        ev("run_finished", status="failed", duration=1.5, hosts=1, changed=1, failed=1, skipped=0),
    ]


def test_event_dict_round_trip():
    e = make_event("note", "r1", time.monotonic(), "pve1", {"message": "x"})
    assert Event.from_dict(e.to_dict()).to_dict() == e.to_dict()


def test_modes():
    assert infer_mode("run -c box") == "check" and infer_mode("run") == "apply" and infer_mode("run -g") == "gather"
    assert infer_mode("run -g -a x") == "apply" and infer_mode("run -g -c") == "check"


def test_note_name_has_no_command_text():
    assert note_name("2026-10-10T12:18:00.123Z", "apply", "20261010-121800-22d326") == "2026-10-10 1218 apply 22d326"


def test_summarize_a_finished_run():
    s = summarize(apply_run())
    assert (s.command, s.mode, s.user, s.status, s.hosts) == ("run -a pve1", "apply", "alice", "failed", ["pve1"])
    assert (s.changed, s.failed, s.skipped, s.duration) == (1, 1, 0, 1.5)


def test_summarize_an_unfinished_run_uses_the_events_so_far():
    unfinished = apply_run()[:-1]
    s = summarize(unfinished)
    assert s.status == "failed" and s.duration > 0 and s.hosts == ["pve1"]
    ok = [ev("run_started", command="run -c", schema=1), ev("host_finished", "pve1", status="ok", changed=0, failed=0, skipped=0)]
    assert summarize(ok).status == "ok"


def test_a_later_host_finished_replaces_an_earlier_one():
    events = apply_run()[:1] + [
        ev("host_finished", "pve1", status="ok", changed=0, failed=0, skipped=0),
        ev("host_finished", "pve1", status="ok", changed=2, failed=0, skipped=0),
    ]
    s = summarize(events)
    assert s.hosts == ["pve1"] and s.changed == 2


def test_detail_one_lists_only_changes_and_failures_using_the_latest_status():
    text = render_run_note(apply_run(), 1)
    assert text.startswith("---\n") and "bastet: run" in text and "mode: apply" in text and "detail: 1" in text
    assert "[[pve1]]" in text
    assert "## pve1" in text and "✓ /etc/motd" in text and "✗ /etc/bad" in text and "boom" in text
    assert "/etc/ok" not in text and "$ " not in text and "### " not in text


def test_detail_two_groups_by_phase_and_shows_compliant_items():
    text = render_run_note(apply_run(), 2)
    assert text.index("### compare") < text.index("### apply")
    assert "/etc/ok" in text and "$ " not in text


def test_detail_three_adds_commands_but_never_output():
    three = render_run_note(apply_run(), 3)
    assert "$ printf x > /etc/motd" in three and "exit 0" in three and "wrote it" not in three
    assert "wrote it" not in render_run_note(apply_run(), 9)    # above 3 is treated as 3


def test_hidden_commands_are_marked():
    events = apply_run()
    events[7]["data"].update(command="(hidden: secret resource)", hidden=True, stdout="", stderr="")
    assert "(hidden: secret resource)" in render_run_note(events, 3)


def test_secrets_are_masked_everywhere():
    ACTIVE.add("hunter2-value")
    events = apply_run()
    events[3]["data"]["changes"] = ["pw → hunter2-value"]
    events[7]["data"]["command"] = "echo hunter2-value"
    events[0]["data"]["command"] = "run -a hunter2-value"
    for detail in (1, 2, 3):
        assert "hunter2-value" not in render_run_note(events, detail)


def test_a_later_scope_without_counts_keeps_the_earlier_failures():
    events = apply_run()[:-1] + [ev("host_finished", "pve1", status="ok")]
    s = summarize(events)
    assert (s.changed, s.failed) == (1, 1) and s.status == "failed"


def test_a_planning_error_is_a_failed_host_with_a_link_and_a_failed_run():
    events = [ev("run_started", command="run -c", schema=1),
              ev("host_skipped", "media01", reason="error: role files: unknown option"),
              ev("host_finished", "pve1", status="ok", changed=0, failed=0, skipped=0)]
    s = summarize(events)
    assert s.hosts == ["media01", "pve1"] and s.failed == 1 and s.status == "failed"
    text = render_run_note(events, 1)
    assert "[[media01]]" in text and "unknown option" in text


def test_an_explicit_status_wins():
    assert summarize(apply_run()[:-1], status="interrupted").status == "interrupted"
    assert "status: interrupted" in render_run_note(apply_run()[:-1], 1, status="interrupted")


def test_failures_explain_themselves_at_the_default_detail():
    events = [ev("run_started", command="run -a", schema=1),
              ev("note", None, message="refresh skipped: a secret is unlocked"),
              ev("trigger_fired", "pve1", trigger="restart sshd", ok=False, error="unit not found"),
              ev("host_finished", "pve1", status="error", error="connection refused", changed=0, failed=0, skipped=0)]
    text = render_run_note(events, 1)
    assert "refresh skipped: a secret is unlocked" in text and "unit not found" in text and "connection refused" in text


def test_odd_runs_render():
    assert "# " in render_run_note([ev("run_started", command="run -c", schema=1)], 1)    # no hosts, unfinished
    skipped = [ev("run_started", command="run", schema=1), ev("host_skipped", "tv1", reason="not managed")]
    assert "tv1" in render_run_note(skipped, 1) and "not managed" in render_run_note(skipped, 1)
    weird = [ev("run_started", command="run -c 'a*/b#[[x]]'", schema=1),
             ev("host_finished", "my host", status="ok", changed=0, failed=0, skipped=0)]
    assert "my host" in render_run_note(weird, 2)
