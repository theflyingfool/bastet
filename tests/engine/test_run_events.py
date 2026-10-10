import json

from bastet.core.remote import LocalRunner
from bastet.core.secrets.redact import ACTIVE
from bastet.engine.model import Trigger
from bastet.engine.run import Batch, run_host
from bastet.events import ListSink, recording
from engine_fakes import Broken, Flag, NoSystemd


def record(fn):
    sink = ListSink()
    with recording("test", [sink]):
        fn()
    return [e for e in sink.events if e.kind not in ("run_started", "run_finished")]


def shape(evts):
    return [(e.kind, e.data.get("phase")) for e in evts]


def test_a_check_emits_the_read_side_phases_only(tmp_path):
    p = tmp_path / "a"
    evts = record(lambda: run_host(LocalRunner(), "pve1", [Batch("one", [Flag(path=str(p), value="1")])], apply=False))
    assert shape(evts) == [
        ("phase_started", "collect"), ("phase_finished", "collect"),
        ("phase_started", "read"), ("command_run", "read"), ("phase_finished", "read"),
        ("phase_started", "compare"), ("item_checked", "compare"), ("phase_finished", "compare"),
    ]
    item = next(e for e in evts if e.kind == "item_checked")
    assert item.host == "pve1" and item.data["status"] == "would-change" and item.data["changes"] == ["value: (absent) → 1"]
    assert not p.exists()


def test_an_apply_emits_apply_commands_triggers_and_verification(tmp_path):
    p = tmp_path / "a"
    batch = Batch("one", [Flag(path=str(p), value="1")])
    sink = ListSink()
    with recording("test", [sink]):
        run_host(LocalRunner(), "pve1", [batch], apply=True)
    evts = [e for e in sink.events if e.kind not in ("run_started", "run_finished")]
    phases = [e.data["phase"] for e in evts if e.kind == "phase_started"]
    assert phases == ["collect", "read", "compare", "apply", "verify"]
    fix = next(e for e in evts if e.kind == "command_run" and e.data["phase"] == "apply")
    assert fix.data["exit"] == 0 and fix.data["hidden"] is False and "printf" in fix.data["command"] and fix.data["duration"] >= 0
    final = [e for e in evts if e.kind == "item_checked" and e.data["phase"] == "apply"]
    assert [e.data["status"] for e in final] == ["changed"]
    verified = [e for e in evts if e.kind == "item_checked" and e.data["phase"] == "verify"]
    assert [e.data["status"] for e in verified] == ["changed"]


def test_triggers_emit_a_command_and_a_trigger_event(tmp_path):
    marker = tmp_path / "marker"
    trigger = Trigger("touch marker", f"touch {marker}", root=False)
    flag = Flag(path=str(tmp_path / "a"), value="1", on_change=(trigger,))
    evts = record(lambda: run_host(LocalRunner(), "pve1", [Batch("one", [flag])], apply=True))
    cmd = [e for e in evts if e.kind == "command_run" and e.data["phase"] == "on_change"]
    fired = [e for e in evts if e.kind == "trigger_fired"]
    assert len(cmd) == 1 and len(fired) == 1 and fired[0].data["ok"] is True and fired[0].data["trigger"] == "touch marker"
    assert marker.exists()


def test_a_failing_fix_records_its_exit_and_stderr_and_skips_the_rest(tmp_path):
    batch = Batch("one", [Broken(path=str(tmp_path / "a"), value="1"), Flag(path=str(tmp_path / "b"), value="2")])
    evts = record(lambda: run_host(LocalRunner(), "pve1", [batch], apply=True))
    fix = next(e for e in evts if e.kind == "command_run" and e.data["phase"] == "apply")
    assert fix.data["exit"] == 3 and "boom" in fix.data["stderr"]
    settled = {e.data["item"].split("/")[-1]: e.data["status"] for e in evts if e.kind == "item_checked" and e.data["phase"] == "apply"}
    assert settled == {"a": "failed", "b": "skipped"}


def test_a_read_never_records_its_output(tmp_path):
    p = tmp_path / "a"
    p.write_text("file-contents-that-might-be-secret")
    evts = record(lambda: run_host(LocalRunner(), "pve1", [Batch("one", [Flag(path=str(p), value="1")])], apply=False))
    read = next(e for e in evts if e.kind == "command_run")
    assert read.data["stdout"] == "" and read.data["stderr"] == "" and read.data["command"].startswith("read ")
    assert "file-contents-that-might-be-secret" not in "".join(e.to_json() for e in evts if e.kind == "command_run")


def test_a_secret_resource_hides_its_command_output_changes_and_diff(tmp_path):
    ACTIVE.add("unrelated-value")  # the masker knows nothing about the secret below
    secret = "s3cret-value-xyz"
    evts = record(lambda: run_host(LocalRunner(), "pve1", [Batch("one", [Flag(path=str(tmp_path / "a"), value=secret, secret=True)])], apply=True))
    blob = "".join(e.to_json() for e in evts)
    assert secret not in blob
    fix = next(e for e in evts if e.kind == "command_run" and e.data["phase"] == "apply")
    assert fix.data["hidden"] is True and fix.data["command"] == "(hidden: secret resource)" and fix.data["stdout"] == ""
    item = next(e for e in evts if e.kind == "item_checked" and e.data["phase"] == "compare")
    assert item.data["changes"] == ["value: (absent) → (secret)"] and item.data["diff"] is None


def test_an_unsupported_item_is_reported_as_skipped(tmp_path):
    evts = record(lambda: run_host(LocalRunner(), "pve1", [Batch("one", [NoSystemd(path=str(tmp_path / "a"), value="1")])], apply=False))
    item = next(e for e in evts if e.kind == "item_checked")
    assert item.data["status"] == "skipped" and "no systemd" in item.data["error"]


def test_events_agree_with_the_host_run(tmp_path):
    batch = Batch("one", [Flag(path=str(tmp_path / "a"), value="1"), Broken(path=str(tmp_path / "b"), value="2"), Flag(path=str(tmp_path / "c"), value="3")])
    result = {}
    evts = record(lambda: result.setdefault("run", run_host(LocalRunner(), "pve1", [batch], apply=True)))
    run = result["run"]
    last = {}
    for e in evts:
        if e.kind == "item_checked":
            last[e.data["item"]] = e.data["status"]
    assert last == {i.resource.label: i.status for i in run.items}


def test_an_unrecorded_run_is_unchanged(tmp_path):
    run = run_host(LocalRunner(), "pve1", [Batch("one", [Flag(path=str(tmp_path / "a"), value="1")])], apply=True)
    assert run.ok and run.count("changed") == 1
