import os
from pathlib import Path

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


def notes(inventory):
    folder = inventory / "_bastet" / "runs"
    return sorted(folder.glob("*.md")) if folder.is_dir() else []


def commit_count(inventory):
    return int(git(inventory, "rev-list", "--count", "HEAD").strip())


def test_a_check_that_writes_something_gets_a_note_in_its_one_commit(runner, box, inventory):
    before = commit_count(inventory)
    result = runner.invoke(app, ["run", "-c", "box"])
    assert result.exit_code == 0, result.output
    assert commit_count(inventory) == before + 1
    [note] = notes(inventory)
    assert " check " in note.name
    assert note.relative_to(inventory).as_posix() in git(inventory, "show", "--stat", "--name-only", "HEAD")
    text = note.read_text()
    assert "bastet: run" in text and "mode: check" in text and "command: run -c box" in text and "detail: 1" in text


def test_a_second_identical_check_writes_nothing_and_makes_no_commit_and_no_note(runner, box, inventory):
    runner.invoke(app, ["run", "-c", "box"])
    count, existing = commit_count(inventory), notes(inventory)
    result = runner.invoke(app, ["run", "-c", "box"])
    assert result.exit_code == 0, result.output
    assert commit_count(inventory) == count and notes(inventory) == existing


def test_an_apply_note_is_in_the_apply_commit_with_the_changes(runner, box, inventory):
    result = runner.invoke(app, ["run", "box", "-y"])
    assert result.exit_code == 0, result.output
    apply_notes = [n for n in notes(inventory) if " apply " in n.name]
    assert apply_notes and "changed" in apply_notes[-1].read_text()


def test_an_interrupted_run_that_commits_gets_a_note_saying_so(runner, box, inventory, monkeypatch):
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(run_mod, "run_parallel", interrupt)
    runner.invoke(app, ["run", "-c", "box"])
    notes_made = notes(inventory)
    assert notes_made and "status: interrupted" in notes_made[-1].read_text()


def test_a_failing_note_never_costs_the_commit(runner, box, inventory, monkeypatch):
    import bastet.events.runnote as runnote

    def boom(*args, **kwargs):
        raise RuntimeError("render exploded")

    monkeypatch.setattr(runnote, "render_run_note", boom)
    before = commit_count(inventory)
    result = runner.invoke(app, ["run", "-c", "box"])
    assert result.exit_code == 0, result.output
    assert "could not write the run note: render exploded" in result.output
    assert commit_count(inventory) == before + 1 and notes(inventory) == []


def test_the_configured_detail_is_used(runner, box, inventory):
    cfg = Path(os.environ["BASTET_CONFIG"])
    cfg.write_text(cfg.read_text() + "runs:\n  note_detail: 3\n")
    result = runner.invoke(app, ["run", "-c", "box"])
    assert result.exit_code == 0, result.output
    [note] = notes(inventory)
    assert "detail: 3" in note.read_text() and "$ " in note.read_text()


def test_the_note_never_holds_a_secret(runner, box, inventory, secret_keys):
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
    cfg = Path(os.environ["BASTET_CONFIG"])
    cfg.write_text(cfg.read_text() + "runs:\n  note_detail: 3\n")
    checked = runner.invoke(app, ["run", "-c", "-vvvv", "box"])
    applied = runner.invoke(app, ["run", "-vvvv", "box", "-y"])
    assert checked.exit_code == 0 and applied.exit_code == 0, checked.output + applied.output
    made = list((inventory / "_bastet" / "runs").glob("*.md"))
    assert made
    assert all(value not in p.read_text() for p in made)


def test_a_failure_with_no_event_still_makes_the_note_say_failed(runner, box, inventory, monkeypatch):
    def refuse(*args, **kwargs):
        raise run_mod.BastetError("box: cannot decide about a reboot")

    monkeypatch.setattr(run_mod, "reboot_decision", refuse)
    result = runner.invoke(app, ["run", "box", "-y"])
    assert result.exit_code == 1, result.output
    apply_notes = [n for n in notes(inventory) if " apply " in n.name]
    assert apply_notes and "status: failed" in apply_notes[-1].read_text()


def test_a_skipped_refresh_with_writes_still_commits_the_note(runner, box, inventory, monkeypatch):
    import bastet.cli.common as common

    def write_something(ctx, doc, items):
        path = ctx.root / "hosts" / "scratch.md"
        path.write_text("scratch\n")
        ctx.written.add(path)
        return True

    monkeypatch.setattr(common, "refresh_generated", lambda *a, **k: [])
    monkeypatch.setattr(run_mod, "_write_security_note", write_something)
    before = commit_count(inventory)
    result = runner.invoke(app, ["run", "-c", "box"])
    assert result.exit_code == 0, result.output
    assert commit_count(inventory) == before + 1
    [note] = notes(inventory)
    assert note.relative_to(inventory).as_posix() in git(inventory, "show", "--name-only", "HEAD")


def test_the_note_survives_the_dashboard_catch_up_amend(runner, box, inventory):
    result = runner.invoke(app, ["run", "-c", "box"])
    assert result.exit_code == 0, result.output
    [note] = notes(inventory)
    assert note.relative_to(inventory).as_posix() in git(inventory, "show", "--name-only", "HEAD")


def test_a_run_that_raises_before_finish_leaves_no_note(runner, box, inventory, monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(run_mod, "run_parallel", explode)
    runner.invoke(app, ["run", "-c", "box"])
    assert notes(inventory) == []
    assert "_bastet/runs" not in git(inventory, "status", "--porcelain", "-uall")
