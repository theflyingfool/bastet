import json
import os
import re
import time
from pathlib import Path

from bastet.cli.app import app
from bastet.core.config import data_dir
from bastet.core.secrets.redact import ACTIVE
from bastet.events.jsonl import runs_dir
from bastet.events.model import make_event
from conftest import git

RUN_ID = "20261010-121800-22d326"


def ev(kind, host=None, run_id=RUN_ID, **data):
    return make_event(kind, run_id, time.monotonic() - 2, host, data).to_dict()


def apply_events(run_id=RUN_ID, command="run -a pve1"):
    return [
        ev("run_started", run_id=run_id, command=command, schema=1, mode="apply", user="alice"),
        ev("host_started", "pve1", run_id=run_id, mode="apply"),
        ev("phase_started", "pve1", run_id=run_id, phase="compare"),
        ev("item_checked", "pve1", run_id=run_id, item="/etc/motd", status="would-change", phase="compare", changes=["differs → update"], error=None),
        ev("item_checked", "pve1", run_id=run_id, item="/etc/ok", status="compliant", phase="compare", changes=[], error=None),
        ev("phase_finished", "pve1", run_id=run_id, phase="compare", duration=0.1),
        ev("phase_started", "pve1", run_id=run_id, phase="apply"),
        ev("command_run", "pve1", run_id=run_id, phase="apply", command="printf x > /etc/motd", exit=0, duration=0.25,
           stdout="wrote it", stderr="", error=None, hidden=False),
        ev("item_checked", "pve1", run_id=run_id, item="/etc/motd", status="changed", phase="apply", changes=["differs → update"], error=None),
        ev("item_checked", "pve1", run_id=run_id, item="/etc/bad", status="failed", phase="apply", changes=[], error="boom"),
        ev("phase_finished", "pve1", run_id=run_id, phase="apply", duration=0.4),
        ev("host_finished", "pve1", run_id=run_id, status="failed", changed=1, failed=1, skipped=0),
        ev("run_finished", run_id=run_id, status="failed", duration=1.5, hosts=1, changed=1, failed=1, skipped=0),
    ]


def record(events=None, run_id=RUN_ID, raw=None):
    """Write a record straight into the (temporary) data directory."""
    directory = runs_dir(data_dir())
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{run_id}.jsonl"
    if raw is not None:
        path.write_text(raw, encoding="utf-8")
    else:
        path.write_text("".join(json.dumps(e) + "\n" for e in (events or apply_events(run_id))), encoding="utf-8")
    return path


def notes(inventory):
    folder = inventory / "_bastet" / "runs"
    return sorted(folder.glob("*.md")) if folder.is_dir() else []


def commit_count(inventory):
    return int(git(inventory, "rev-list", "--count", "HEAD").strip())


def set_detail(level):
    cfg = Path(os.environ["BASTET_CONFIG"])
    cfg.write_text(cfg.read_text() + f"runs:\n  note_detail: {level}\n")


def test_note_makes_a_note_at_the_configured_detail_in_one_commit(runner, inventory):
    record()
    before = commit_count(inventory)
    result = runner.invoke(app, ["log", "note", "latest", "-y"])
    assert result.exit_code == 0, result.output
    assert commit_count(inventory) == before + 1
    [note] = notes(inventory)
    assert note.parent == inventory / "_bastet" / "runs"
    text = note.read_text()
    assert "detail: 1" in text and "bastet: run" in text and f"run: {RUN_ID}" in text
    assert note.relative_to(inventory).as_posix() in git(inventory, "show", "--stat", "--name-only", "HEAD")


def test_note_replaces_the_same_file_when_the_configured_detail_changes(runner, inventory):
    record()
    before = commit_count(inventory)
    assert runner.invoke(app, ["log", "note", "latest", "-y"]).exit_code == 0
    [first] = notes(inventory)
    assert "$ printf x" not in first.read_text()
    set_detail(3)
    result = runner.invoke(app, ["log", "note", RUN_ID, "-y"])
    assert result.exit_code == 0, result.output
    [second] = notes(inventory)
    assert second == first
    text = second.read_text()
    assert "detail: 3" in text and "$ printf x" in text
    assert commit_count(inventory) == before + 2


def test_note_is_up_to_date_when_nothing_changes(runner, inventory):
    record()
    assert runner.invoke(app, ["log", "note", "latest", "-y"]).exit_code == 0
    before = commit_count(inventory)
    result = runner.invoke(app, ["log", "note", "latest", "-y"])
    assert result.exit_code == 0 and "Already up to date." in result.output
    assert commit_count(inventory) == before


def test_note_for_a_missing_or_pruned_record_is_a_clear_error(runner, inventory):
    result = runner.invoke(app, ["log", "note", "latest", "-y"])
    assert result.exit_code == 1 and "Traceback" not in result.output
    assert "no runs recorded yet" in result.output
    record()
    result = runner.invoke(app, ["log", "note", "20250101", "-y"])
    assert result.exit_code == 1 and "Traceback" not in result.output
    assert "no run matching" in result.output
    assert notes(inventory) == []


def test_note_for_an_empty_or_torn_record_is_a_clear_error(runner, inventory):
    before = commit_count(inventory)
    record(raw="", run_id="20261010-120000-aaaa")
    result = runner.invoke(app, ["log", "note", "20261010-120000-aaaa", "-y"])
    assert result.exit_code == 1 and "Traceback" not in result.output
    assert "that record has no start event" in result.output
    record(raw='{"kind": "run_star', run_id="20261011-120000-bbbb")
    result = runner.invoke(app, ["log", "note", "20261011-120000-bbbb", "-y"])
    assert result.exit_code == 1 and "Traceback" not in result.output
    assert "that record has no start event" in result.output
    assert notes(inventory) == [] and commit_count(inventory) == before


def test_note_for_a_run_with_odd_command_text_makes_a_safe_file_name(runner, inventory):
    record(apply_events(command="run -c 'a*/b#[[x]]'"))
    result = runner.invoke(app, ["log", "note", "latest", "-y"])
    assert result.exit_code == 0, result.output
    [note] = notes(inventory)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{4} (apply|check|gather) [0-9a-f]+\.md", note.name)
    assert note.parent == inventory / "_bastet" / "runs"
    assert note.name.endswith(" apply 22d326.md") and "[" not in note.name and "*" not in note.name


def test_note_never_holds_a_secret(runner, inventory):
    ACTIVE.add("SENTINEL-4242")
    record(apply_events(command="run -a pve1 --token SENTINEL-4242"))
    set_detail(3)
    result = runner.invoke(app, ["log", "note", "latest", "-y"])
    assert result.exit_code == 0, result.output
    [note] = notes(inventory)
    assert "SENTINEL-4242" not in note.read_text()
    assert "SENTINEL-4242" not in result.output


def test_there_is_no_remove_option(runner, inventory):
    record()
    result = runner.invoke(app, ["log", "note", RUN_ID, "--remove"])
    assert result.exit_code != 0
    assert "No such option" in result.output
    assert notes(inventory) == []


def test_show_default_prints_changes_and_failures_only(runner, inventory):
    record()
    result = runner.invoke(app, ["log", "show", "latest"])
    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[0] == f"{RUN_ID}  run -a pve1  failed"
    assert "/etc/motd" in result.output and "/etc/bad" in result.output and "boom" in result.output
    assert "/etc/ok" not in result.output and "printf x" not in result.output and "wrote it" not in result.output
    assert runner.invoke(app, ["log", "show", "latest", "-v"]).output == result.output


def test_show_vv_adds_phases_and_items_vvv_commands_vvvv_output(runner, inventory):
    record()
    outputs = {n: runner.invoke(app, ["log", "show", "latest", "-" + "v" * n]).output for n in (2, 3, 4)}
    default = runner.invoke(app, ["log", "show", "latest"]).output
    assert "/etc/ok" in outputs[2] and "/etc/ok" not in default
    assert "printf x" not in outputs[2] and "printf x" in outputs[3]
    assert "wrote it" not in outputs[2] and "wrote it" not in outputs[3] and "wrote it" in outputs[4]
    assert len(outputs[2]) > len(default)


def test_show_skips_torn_lines_and_reports_a_missing_run(runner, inventory):
    lines = [json.dumps(e) for e in apply_events()]
    raw = "\n".join([lines[0], "this is not json", *lines[1:], '{"kind": "item_chec']) + "\n"
    record(raw=raw)
    result = runner.invoke(app, ["log", "show", "latest"])
    assert result.exit_code == 0, result.output
    assert "Traceback" not in result.output and "/etc/bad" in result.output
    result = runner.invoke(app, ["log", "show", "20250101"])
    assert result.exit_code == 1 and "Traceback" not in result.output
    assert "no run matching" in result.output


def test_show_writes_nothing(runner, inventory):
    path = record()
    data_before = sorted(p.name for p in runs_dir(data_dir()).iterdir())
    text_before = path.read_text()
    commits = commit_count(inventory)
    for flags in ([], ["-vvvv"]):
        assert runner.invoke(app, ["log", "show", "latest", *flags]).exit_code == 0
    assert commit_count(inventory) == commits
    assert git(inventory, "status", "--porcelain").strip() == ""
    assert notes(inventory) == []
    assert sorted(p.name for p in runs_dir(data_dir()).iterdir()) == data_before
    assert path.read_text() == text_before


def clean_unfinished():
    events = apply_events()[:-1]
    events[-1] = ev("host_finished", "pve1", status="ok", changed=0, failed=0, skipped=0)   # no failed items, no run_finished
    return [e for e in events if e["kind"] != "item_checked" or e["data"]["status"] != "failed"]


def test_note_and_show_call_a_record_with_no_run_finished_unfinished(runner, inventory):
    record(clean_unfinished())
    assert runner.invoke(app, ["log", "note", "latest", "-y"]).exit_code == 0
    [note] = notes(inventory)
    assert "status: unfinished" in note.read_text()
    shown = runner.invoke(app, ["log", "show", "latest"])
    assert shown.exit_code == 0 and shown.output.splitlines()[0].endswith("  unfinished")


def test_a_finished_record_keeps_its_own_status(runner, inventory):
    record()
    assert runner.invoke(app, ["log", "show", "latest"]).output.splitlines()[0].endswith("  failed")


def test_odd_lines_are_skipped_not_a_traceback(runner, inventory):
    good = [json.dumps(e) for e in apply_events()]
    odd = ['{"kind": "note", "data": {}}', '{"kind": "note", "run_id": "r", "t": "x", "host": 3, "data": {}}',
           '{"kind": "note", "run_id": "r", "t": "x", "data": "text"}', '[1, 2]', '{"kind": 7, "data": {}}',
           '{"kind": "mystery", "run_id": "r", "t": "x", "host": null, "data": {}}']
    record(raw="\n".join([good[0], *odd, *good[1:]]) + "\n")
    for args in (["log", "show", "latest", "-vvvv"], ["log", "note", "latest", "-y"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output
        assert "Traceback" not in result.output


def test_show_on_a_record_with_no_start_event_is_a_clear_error(runner, inventory):
    record(raw='{"kind": "run_star')
    result = runner.invoke(app, ["log", "show", "latest"])
    assert result.exit_code == 1 and "that record has no start event" in result.output
