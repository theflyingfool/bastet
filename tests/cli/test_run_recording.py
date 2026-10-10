import json

import pytest

import bastet.cli.run as run_mod
from bastet.cli.app import app
from bastet.core.config import data_dir
from bastet.core.remote import LocalRunner
from bastet.core.secrets import crypto
from bastet.core.secrets.notes import SecretNote, SecretPath
from bastet.core.secrets.redact import ACTIVE
from bastet.events.jsonl import runs_dir
from conftest import git


class AsRootLocally(LocalRunner):
    """Runs scripts as the current user, as if it were root, so role files can target temp paths."""

    def run(self, script, *, timeout=120):
        return super().run(script.replace('if [ "$(id -u)" = 0 ]; then SUDO=""', 'if true; then SUDO=""'), timeout=timeout)


def records():
    return sorted(runs_dir(data_dir()).glob("*.jsonl"))


def events_of(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.fixture
def box(inventory, monkeypatch, tmp_path):
    out = tmp_path / "out"
    (inventory / "hosts" / "box.md").write_text("---\nbastet: host\ntype: laptop\nconnection: local\nhostname: box\n---\n# box\n")
    roles = inventory / "_roles" / "hosts" / "box"
    roles.mkdir(parents=True)
    (roles / "files.md").write_text(
        f'---\nbastet: role\nrole: files\napplies_to: "[[box]]"\nfiles:\n  {out}/motd:\n    content: "hi\\n"\n---\n')
    git(inventory, "add", ".")
    git(inventory, "commit", "-q", "-m", "box")
    monkeypatch.setattr(run_mod, "connect", lambda ctx, doc, tmp, yes: (AsRootLocally(), None))
    return out


def test_a_check_leaves_one_record(runner, box):
    result = runner.invoke(app, ["run", "-c", "box"])
    assert result.exit_code == 0, result.output
    files = records()
    assert len(files) == 1
    events = events_of(files[0])
    assert events[0]["kind"] == "run_started"
    assert events[0]["data"]["command"] == "run -c box"
    assert events[0]["data"]["schema"] == 1
    assert events[-1]["kind"] == "run_finished" and events[-1]["data"]["status"] == "ok"
    kinds = {(e["kind"], e.get("host")) for e in events}
    for kind in ("host_started", "phase_started", "item_checked", "host_finished"):
        assert (kind, "box") in kinds
    finished = next(e for e in events if e["kind"] == "host_finished")
    assert finished["data"]["status"] == "ok"
    assert "1 to change" in result.output


def test_an_apply_records_the_command_run(runner, box):
    result = runner.invoke(app, ["run", "box", "-y"])
    assert result.exit_code == 0, result.output
    events = events_of(records()[0])
    assert any(e["kind"] == "command_run" and e["data"]["phase"] == "apply" and e["data"]["exit"] == 0 for e in events)


def test_nothing_printed_changes_below_double_v(runner, box):
    plain = runner.invoke(app, ["run", "-c", "box"]).output
    one = runner.invoke(app, ["run", "-c", "-v", "box"]).output
    for text in (plain, one):
        assert "box: read" not in text
        assert not any(line.startswith("$ ") for line in text.splitlines())
    two = runner.invoke(app, ["run", "-c", "-vv", "box"]).output
    assert "box: read" in two
    assert not any(" $ " in line for line in two.splitlines())
    three = runner.invoke(app, ["run", "-c", "-vvv", "box"]).output
    assert any(" $ " in line for line in three.splitlines())
    # reads and file writes print nothing on stdout, so -vvvv shows what -vvv shows here; the extra
    # output lines are covered in tests/events/test_terminal_sink.py
    four = runner.invoke(app, ["run", "-c", "-vvvv", "box"]).output
    assert any(" $ " in line for line in four.splitlines())


def test_dash_v_still_shows_compliant_items(runner, box):
    runner.invoke(app, ["run", "box", "-y"])
    assert "✓ compliant" in runner.invoke(app, ["run", "-c", "-v", "box"]).output


def test_a_failing_run_records_failed(runner, box, inventory):
    (inventory / "_roles" / "hosts" / "box" / "bogus.md").write_text(
        '---\nbastet: role\nrole: nosuchrole\napplies_to: "[[box]]"\n---\n')
    git(inventory, "add", ".")
    git(inventory, "commit", "-q", "-m", "bogus")
    result = runner.invoke(app, ["run", "-c", "box"])
    assert result.exit_code != 0
    assert events_of(records()[0])[-1]["data"]["status"] == "failed"


def test_early_exits_are_ok(runner, inventory):
    (inventory / "hosts" / "pve1.md").unlink()
    git(inventory, "add", "-A")
    git(inventory, "commit", "-q", "-m", "empty")
    result = runner.invoke(app, ["run", "-c"])
    assert result.exit_code == 0, result.output
    last = events_of(records()[0])[-1]
    assert last["kind"] == "run_finished" and last["data"]["status"] == "ok" and last["data"]["hosts"] == 0


def test_an_unwritable_record_does_not_stop_the_run(runner, box, tmp_path, monkeypatch):
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    (blocked / "bastet").write_text("in the way")
    monkeypatch.setenv("XDG_DATA_HOME", str(blocked))
    result = runner.invoke(app, ["run", "-c", "-vv", "box"])
    assert result.exit_code == 0, result.output
    assert "warning: not recording this run" in result.output
    assert "1 to change" in result.output
    assert "box: read" in result.output


def test_a_skipped_host_is_recorded(runner, box, inventory):
    (inventory / "hosts" / "tv.md").write_text("---\nbastet: host\ntype: other\nip: 10.10.0.3\n---\n# tv\n")
    git(inventory, "add", ".")
    git(inventory, "commit", "-q", "-m", "tv")
    result = runner.invoke(app, ["run", "-c", "tv", "box"])
    assert result.exit_code == 0, result.output
    events = events_of(records()[0])
    assert any(e["kind"] == "host_skipped" and e.get("host") == "tv" and e["data"]["reason"] == "not managed" for e in events)


def test_bastet_log_lists_the_run(runner, box):
    runner.invoke(app, ["run", "-c", "box"])
    listed = runner.invoke(app, ["log"])
    assert listed.exit_code == 0, listed.output
    assert "run -c" in listed.output and "ok" in listed.output


def test_secrets_never_reach_the_record(runner, box, inventory, secret_keys):
    value = "hunter2-value"
    ACTIVE.add(value)
    sp = SecretPath.parse("box/files/motd")
    note = SecretNote.new(sp, source="chosen", created="2026-10-03T00:00", applies_to="box")
    note.body = crypto.seal(sp.text, value, [secret_keys["pub"]])
    note.write(inventory)
    (inventory / "_roles" / "hosts" / "box" / "files.md").write_text(
        f'---\nbastet: role\nrole: files\napplies_to: "[[box]]"\nfiles:\n  {box}/motd:\n    content: "secret:motd"\n---\n')
    git(inventory, "add", ".")
    git(inventory, "commit", "-q", "-m", "secret")
    checked = runner.invoke(app, ["run", "-c", "-vvvv", "box"])
    applied = runner.invoke(app, ["run", "-vvvv", "box", "-y"])
    assert checked.exit_code == 0 and applied.exit_code == 0, checked.output + applied.output
    assert (box / "motd").read_text() == value
    exported = runner.invoke(app, ["log", "export", "latest"])
    for text in (checked.output, applied.output, exported.output, *(p.read_text() for p in records())):
        assert value not in text


def test_ctrl_c_during_the_check_records_interrupted(runner, box, monkeypatch):
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(run_mod, "run_parallel", interrupt)
    runner.invoke(app, ["run", "-c", "box"])
    [path] = records()
    events = events_of(path)
    assert events[-1]["kind"] == "run_finished" and events[-1]["data"]["status"] == "interrupted"
