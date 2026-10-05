import pytest

from bastet.core.errors import Unreachable
from bastet.core.remote import LocalRunner
from bastet.engine.model import Trigger
from bastet.engine.run import Batch, ConflictError, run_host
from engine_fakes import Append, Broken, DeniedRunner, ExplodingRunner, Flag, NoSystemd, Stubborn, UnreadableReportOnly


def statuses(run):
    return {i.resource.label: (i.status, i.error) for i in run.items}


def test_check_reports_without_changing(tmp_path):
    p = tmp_path / "a"
    run = run_host(LocalRunner(), "h", [Batch("one", [Flag(path=str(p), value="1")])], apply=False)
    [item] = run.items
    assert item.status == "would-change" and [(c.field, c.before, c.after) for c in item.changes] == [("value", "(absent)", "1")]
    assert not p.exists() and not run.applied


def test_apply_then_rerun_is_clean(tmp_path):
    batches = [Batch("one", [Flag(path=str(tmp_path / "a"), value="1")])]
    first = run_host(LocalRunner(), "h", batches, apply=True)
    assert first.ok and first.count("changed") == 1 and (tmp_path / "a").read_text() == "1"
    second = run_host(LocalRunner(), "h", batches, apply=True)
    assert second.count("compliant") == 1 and not second.triggers


def test_same_item_from_two_batches_is_merged(tmp_path):
    f = Flag(path=str(tmp_path / "a"), value="1")
    run = run_host(LocalRunner(), "h", [Batch("lab", [f]), Batch("media01", [f])], apply=False)
    [item] = run.items
    assert item.origins == ["lab", "media01"]


def test_conflict_stops_before_anything_runs(tmp_path):
    p = str(tmp_path / "a")
    with pytest.raises(ConflictError) as e:
        run_host(ExplodingRunner(), "h", [Batch("lab", [Flag(path=p, value="1")]), Batch("media01", [Flag(path=p, value="2")])], apply=True)
    assert "lab" in str(e.value) and "media01" in str(e.value) and "value" in str(e.value)


def test_failure_skips_rest_of_batch_and_later_batches(tmp_path):
    bad, after, other = (str(tmp_path / n) for n in ("bad", "after", "other"))
    run = run_host(LocalRunner(), "h", [
        Batch("one", [Broken(path=bad, value="x"), Flag(path=after, value="y")]),
        Batch("two", [Flag(path=other, value="z")]),
    ], apply=True)
    s = statuses(run)
    assert s[bad] == ("failed", "boom")
    assert s[after][0] == "skipped" and s[after][1] == f"earlier failure: {bad}"
    assert s[other] == ("skipped", f"earlier failure on this host: {bad}")
    assert not (tmp_path / "other").exists() and not run.ok


def test_failure_stops_later_batches_but_not_an_earlier_trigger(tmp_path):
    log = tmp_path / "log"
    trigger = Trigger("t", f"echo ran >> {log}", root=False)
    zero = Flag(path=str(tmp_path / "z"), value="1", on_change=(trigger,))
    bad, other = (str(tmp_path / n) for n in ("bad", "other"))
    run = run_host(LocalRunner(), "h", [
        Batch("zero", [zero]),
        Batch("one", [Broken(path=bad, value="x")]),
        Batch("two", [Flag(path=other, value="z")]),
    ], apply=True)
    s = statuses(run)
    assert s[bad] == ("failed", "boom")
    assert s[other] == ("skipped", f"earlier failure on this host: {bad}")
    assert not (tmp_path / "other").exists()
    assert [(t.trigger.label, t.ok) for t in run.triggers] == [("t", True)]
    assert log.read_text() == "ran\n"


def test_failed_trigger_stops_later_batches(tmp_path):
    trigger = Trigger("restart-thing", "exit 1", root=False)
    other = str(tmp_path / "other")
    run = run_host(LocalRunner(), "h", [
        Batch("one", [Flag(path=str(tmp_path / "a"), value="1", on_change=(trigger,))]),
        Batch("two", [Flag(path=other, value="z")]),
    ], apply=True)
    s = statuses(run)
    assert [(t.trigger.label, t.ok) for t in run.triggers] == [("restart-thing", False)]
    assert s[other] == ("skipped", "earlier failure on this host: restart-thing")
    assert not (tmp_path / "other").exists() and not run.ok


def test_triggers_run_once_after_batch_in_order(tmp_path):
    log = tmp_path / "log"
    late = Trigger("late", f"echo late >> {log}", root=False)
    early = Trigger("early", f"echo early >> {log}", order=10, root=False)
    a = Flag(path=str(tmp_path / "a"), value="1", on_change=(late, early))
    b = Flag(path=str(tmp_path / "b"), value="2", on_change=(late,))
    run = run_host(LocalRunner(), "h", [Batch("one", [a, b])], apply=True)
    assert log.read_text() == "early\nlate\n"
    assert [(t.trigger.label, t.ok) for t in run.triggers] == [("early", True), ("late", True)]
    again = run_host(LocalRunner(), "h", [Batch("one", [a, b])], apply=True)
    assert not again.triggers and log.read_text() == "early\nlate\n"


def test_verify_catches_a_fix_that_did_nothing(tmp_path):
    run = run_host(LocalRunner(), "h", [Batch("one", [Stubborn(path=str(tmp_path / "a"), value="1")])], apply=True)
    [item] = run.items
    assert item.status == "failed" and item.error.startswith("still value (absent) after apply")


def test_root_reads_denied(tmp_path):
    run = run_host(DeniedRunner(), "h", [Batch("one", [Flag(path=str(tmp_path / "a"), value="1", root=True)])], apply=True)
    [item] = run.items
    assert item.status == "failed" and "needs root" in item.error


def test_unsupported_is_skipped(tmp_path):
    run = run_host(LocalRunner(), "h", [Batch("one", [NoSystemd(path=str(tmp_path / "a"), value="1")])], apply=True)
    [item] = run.items
    assert (item.status, item.error) == ("skipped", "no systemd on this host")
    assert not (tmp_path / "a").exists()


def test_same_file_edits_see_each_other(tmp_path):
    p = str(tmp_path / "shared")
    batches = [Batch("one", [Append(path=p, text="one"), Append(path=p, text="two")])]
    first = run_host(LocalRunner(), "h", batches, apply=True)
    assert first.ok and (tmp_path / "shared").read_text() == "one\ntwo\n"
    assert run_host(LocalRunner(), "h", batches, apply=True).count("compliant") == 2


from bastet.engine.command import Command  # noqa: E402
from bastet.engine.run import collect_items  # noqa: E402
from bastet.engine.systemd import TimeSettings  # noqa: E402
from engine_fakes import SilentRunner, Unreadable  # noqa: E402


def test_stdin_reading_check_cannot_swallow_later_reads(tmp_path):
    marker = tmp_path / "m"
    marker.write_text("")
    greedy = Command(name="greedy", run="true", unless="cat >/dev/null; true", root=False)
    guard = Command(name="guard", run=f"echo ran >> {tmp_path / 'log'}", unless=f"test -e {marker}", root=False)
    run = run_host(LocalRunner(), "h", [Batch("t", [greedy, guard])], apply=True)
    assert not (tmp_path / "log").exists() and statuses(run)["guard"] == ("compliant", None)


def test_unreported_read_fails_the_item():
    run = run_host(SilentRunner(), "h", [Batch("t", [Command(name="guard", run="x", unless="y", root=False)])], apply=False)
    assert run.items[0].status == "failed" and "no output" in run.items[0].error


def test_read_failure_stops_the_rest_of_its_batch(tmp_path):
    run = run_host(LocalRunner(), "h", [Batch("t", [Unreadable(path=str(tmp_path / "d"), value="1"),
                                                     Flag(path=str(tmp_path / "after"), value="2")])], apply=True)
    s = statuses(run)
    assert s[str(tmp_path / "after")][0] == "skipped" and not (tmp_path / "after").exists()


def test_report_only_read_failure_does_not_stop_later_batches(tmp_path):
    bad = str(tmp_path / "bad")
    other = str(tmp_path / "other")
    run = run_host(LocalRunner(), "h", [
        Batch("one", [UnreadableReportOnly(path=bad, value="x")]),
        Batch("two", [Flag(path=other, value="z")]),
    ], apply=True)
    s = statuses(run)
    assert s[bad][0] == "failed"
    assert s[other][0] == "changed"
    assert (tmp_path / "other").read_text() == "z"
    assert not run.ok


def test_partial_desires_merge_and_real_clashes_still_conflict():
    [(_, [item])] = collect_items([Batch("a", [TimeSettings(timezone="UTC")])])
    planned = collect_items([Batch("a", [TimeSettings(timezone="UTC")]), Batch("b", [TimeSettings(ntp=True)])])
    [item] = [i for _, mine in planned for i in mine]
    assert item.resource.desired() == {"timezone": "UTC", "ntp": True, "rtc_local": None} and item.origins == ["a", "b"]
    with pytest.raises(ConflictError):
        collect_items([Batch("a", [TimeSettings(timezone="UTC")]), Batch("b", [TimeSettings(timezone="Europe/Paris")])])


from engine_fakes import BrokenGroup, GroupedFlag  # noqa: E402


def test_consecutive_grouped_items_are_fixed_by_one_call(tmp_path):
    log = str(tmp_path / "log")
    items = [GroupedFlag(path=str(tmp_path / n), value=n, log=log) for n in ("a", "b", "c")]
    run = run_host(LocalRunner(), "h", [Batch("t", [*items, Flag(path=str(tmp_path / "d"), value="d"),
                                                     GroupedFlag(path=str(tmp_path / "e"), value="e", log=log)])], apply=True)
    assert run.ok and run.count("changed") == 5
    assert (tmp_path / "log").read_text() == "call\ncall\n"
    assert all((tmp_path / n).read_text() == n for n in "abcde")


def test_group_failure_fails_every_member(tmp_path):
    log = str(tmp_path / "log")
    run = run_host(LocalRunner(), "h", [Batch("t", [
        BrokenGroup(path=str(tmp_path / "a"), value="a", log=log),
        BrokenGroup(path=str(tmp_path / "b"), value="b", log=log),
        Flag(path=str(tmp_path / "after"), value="x"),
    ])], apply=True)
    s = statuses(run)
    assert s[str(tmp_path / "a")] == ("failed", "E: Unable to locate package nope")
    assert s[str(tmp_path / "b")] == ("failed", "E: Unable to locate package nope")
    assert s[str(tmp_path / "after")][0] == "skipped"


# fixes get their own long timeout, and a timeout fails the group instead of losing the host

class TimingOutRunner:
    name = "slow"

    def __init__(self):
        self.timeouts = []

    def run(self, script, *, timeout=120):
        self.timeouts.append(timeout)
        if "SLOW-FIX" in script:
            raise Unreachable("bastet@203.0.113.10: timed out after 1800s")
        return LocalRunner().run(script, timeout=timeout)


def test_fix_timeout_fails_the_group_and_keeps_the_run(tmp_path):
    runner = TimingOutRunner()
    slow = [GroupedFlag(path=str(tmp_path / n), value="SLOW-FIX", log=str(tmp_path / "log")) for n in "ab"]
    run = run_host(runner, "h", [Batch("one", [*slow, Flag(path=str(tmp_path / "c"), value="x")]),
                                 Batch("two", [Flag(path=str(tmp_path / "d"), value="y")])], apply=True)
    s = {i.resource.label: (i.status, i.error) for i in run.items}
    assert s[str(tmp_path / "a")][0] == "failed" and "timed out" in s[str(tmp_path / "a")][1]
    assert s[str(tmp_path / "c")][0] == "skipped" and s[str(tmp_path / "d")][0] == "skipped"
    assert max(runner.timeouts) >= 1800
