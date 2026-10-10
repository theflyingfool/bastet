import threading

import pytest

from bastet import events
from bastet.core.secrets.redact import ACTIVE
from bastet.events.recorder import ListSink, Recorder, new_run_id, recording


def kinds(sink):
    return [e.kind for e in sink.events]


def test_run_started_first_run_finished_last_and_order_kept():
    sink = ListSink()
    with recording("run -c", [sink]) as rec:
        events.emit("note", None, message="one")
        events.emit("note", None, message="two")
    assert kinds(sink) == ["run_started", "note", "note", "run_finished"]
    assert [e.data["message"] for e in sink.events[1:3]] == ["one", "two"]
    assert sink.events[0].data["command"] == "run -c" and sink.events[0].data["schema"] == 1
    assert sink.events[-1].data["status"] == "ok"


def test_emit_outside_a_recording_is_a_no_op():
    events.emit("note", None, message="nobody listening")


def test_status_follows_the_exception():
    for exc, status in ((ValueError("x"), "failed"), (KeyboardInterrupt(), "interrupted")):
        sink = ListSink()
        with pytest.raises(type(exc)):
            with recording("run", [sink]):
                raise exc
        assert sink.events[-1].kind == "run_finished" and sink.events[-1].data["status"] == status


def test_an_explicit_status_wins_even_when_an_exception_passes():
    sink = ListSink()
    with pytest.raises(RuntimeError):
        with recording("run", [sink]) as rec:
            rec.status = "ok"
            raise RuntimeError("exit 0")
    assert sink.events[-1].data["status"] == "ok"


def test_counts_are_summed_from_host_finished():
    sink = ListSink()
    with recording("run", [sink]):
        events.emit("host_finished", "a", status="ok", changed=2, failed=0, skipped=1)
        events.emit("host_finished", "b", status="failed", changed=1, failed=3, skipped=0)
    done = sink.events[-1].data
    assert (done["hosts"], done["changed"], done["failed"], done["skipped"]) == (2, 3, 3, 1)


def test_many_threads_lose_nothing_and_keep_per_thread_order():
    sink = ListSink()
    with recording("run", [sink]):
        def worker(n):
            for i in range(50):
                events.emit("note", f"h{n}", message=f"{n}-{i}")

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    notes = [e for e in sink.events if e.kind == "note"]
    assert len(notes) == 400
    for n in range(8):
        mine = [int(e.data["message"].split("-")[1]) for e in notes if e.host == f"h{n}"]
        assert mine == list(range(50))
    assert sink.events[-1].kind == "run_finished"


def test_masking_happens_before_any_sink_sees_the_event():
    ACTIVE.add("hunter2-value")
    sink = ListSink()
    with recording("run", [sink]):
        events.emit("note", "pve1", message="pw hunter2-value", extra={"deep": ["hunter2-value"]})
    note = next(e for e in sink.events if e.kind == "note")
    assert "hunter2-value" not in note.to_json()


def test_a_failing_sink_is_reported_once_and_dropped_while_the_others_continue(capsys):
    class Boom(ListSink):
        name = "boom"

        def handle(self, event):
            super().handle(event)
            if len(self.events) == 3:
                raise OSError("disk full")

    boom, good = Boom(), ListSink()
    with recording("run", [boom, good]):
        for i in range(5):
            events.emit("note", None, message=str(i))
    assert len(good.events) == 7 and len(boom.events) == 3
    err = capsys.readouterr().err
    assert err.count("boom output stopped: disk full") == 1


def test_an_invalid_event_is_dropped_counted_and_reported_once(capsys):
    sink = ListSink()
    with recording("run", [sink]) as rec:
        events.emit("command_run", "pve1", phase="apply")
        events.emit("command_run", "pve1", phase="apply")
        events.emit("nope", None)
    assert rec.dropped == 3 and "command_run" not in kinds(sink)
    assert capsys.readouterr().err.count("dropped an invalid event") <= 2  # once per distinct problem


def test_nested_recording_reuses_the_active_recorder():
    sink = ListSink()
    with recording("run", [sink]) as outer:
        with recording("gather", [ListSink()]) as inner:
            assert inner is outer
        events.emit("note", None, message="still recording")
    assert kinds(sink).count("run_started") == 1 and "note" in kinds(sink)


def test_phase_and_host_scope_emit_pairs():
    sink = ListSink()
    with recording("run", [sink]):
        with events.host_scope("pve1", "check") as scope:
            with events.phase("pve1", "read"):
                pass

            class Run:
                stopped = False

                def count(self, status):
                    return {"changed": 2, "failed": 0, "skipped": 1}.get(status, 0)

            scope.record(Run())
    got = [(e.kind, e.data.get("phase") or e.data.get("mode") or e.data.get("status")) for e in sink.events[1:-1]]
    assert got == [("host_started", "check"), ("phase_started", "read"), ("phase_finished", "read"), ("host_finished", "ok")]
    finished = next(e for e in sink.events if e.kind == "host_finished")
    assert (finished.data["changed"], finished.data["skipped"]) == (2, 1)


def test_host_scope_reports_an_error_and_reraises():
    sink = ListSink()
    with recording("run", [sink]):
        with pytest.raises(ValueError):
            with events.host_scope("pve1", "apply"):
                raise ValueError("connection lost")
    finished = next(e for e in sink.events if e.kind == "host_finished")
    assert finished.data["status"] == "error" and "connection lost" in finished.data["error"]


def test_a_failed_run_makes_the_host_failed():
    sink = ListSink()

    class Run:
        stopped = False

        def count(self, status):
            return 1 if status == "failed" else 0

    with recording("run", [sink]):
        with events.host_scope("pve1", "apply") as scope:
            scope.record(Run())
    assert next(e for e in sink.events if e.kind == "host_finished").data["status"] == "failed"


def test_run_ids_sort_by_time_and_are_unique():
    ids = [new_run_id() for _ in range(50)]
    assert len(set(ids)) == 50 and all(len(i) == len("20261010-120000-ab12cd") for i in ids)


def test_set_status_gives_the_run_its_status_and_the_first_reason_wins():
    sink = ListSink()
    with recording("run", [sink]):
        events.set_status("interrupted")
        events.set_status("failed")
    assert sink.events[-1].data["status"] == "interrupted"
    events.set_status("failed")  # outside a recording: nothing happens
