import json
import os
import stat
import time

import pytest

from bastet import events
from bastet.core.errors import BastetError
from bastet.events.jsonl import JsonlSink, prune, resolve_run, summarize
from bastet.events.recorder import recording


def make_run(directory, run_id="20261010-120000-aaaa", notes=2):
    sink = JsonlSink(directory, run_id)
    with recording("run -c", [sink], run_id=run_id):
        for i in range(notes):
            events.emit("note", "pve1", message=f"n{i}")
    return sink.path


def test_one_json_object_per_line_with_private_modes(tmp_path):
    path = make_run(tmp_path / "runs")
    lines = path.read_text().splitlines()
    parsed = [json.loads(line) for line in lines]
    assert [p["kind"] for p in parsed] == ["run_started", "note", "note", "run_finished"]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_an_existing_run_id_is_refused(tmp_path):
    make_run(tmp_path / "runs")
    with pytest.raises(FileExistsError):
        JsonlSink(tmp_path / "runs", "20261010-120000-aaaa")


def test_prune_by_count_and_age_only_touches_jsonl(tmp_path):
    d = tmp_path / "runs"
    paths = [make_run(d, f"2026101{i}-120000-aaaa") for i in range(5)]
    (d / "notes.txt").write_text("keep")
    old = time.time() - 200 * 86400
    os.utime(paths[0], (old, old))
    removed = prune(d, keep_runs=3, keep_days=90)
    assert sorted(p.name for p in removed) == sorted(p.name for p in paths[:2])
    assert sorted(p.name for p in d.glob("*.jsonl")) == sorted(p.name for p in paths[2:])
    assert (d / "notes.txt").exists()


def test_prune_with_no_limits_keeps_everything(tmp_path):
    d = tmp_path / "runs"
    paths = [make_run(d, f"2026101{i}-120000-aaaa") for i in range(3)]
    old = time.time() - 4000 * 86400
    os.utime(paths[0], (old, old))
    assert prune(d, keep_runs=None, keep_days=None) == []
    assert len(list(d.glob("*.jsonl"))) == 3
    assert [p.name for p in prune(d, keep_runs=None, keep_days=90)] == [paths[0].name]


def test_prune_reports_a_file_it_cannot_remove_and_goes_on(tmp_path, monkeypatch, capsys):
    d = tmp_path / "runs"
    paths = [make_run(d, f"2026101{i}-120000-aaaa") for i in range(3)]
    real = type(paths[0]).unlink

    def flaky(self, *a, **k):
        if self.name.startswith("20261010"):
            raise PermissionError("nope")
        return real(self, *a, **k)

    monkeypatch.setattr(type(paths[0]), "unlink", flaky)
    removed = prune(d, keep_runs=1, keep_days=90)
    assert [p.name for p in removed] == [paths[1].name]
    assert "could not remove" in capsys.readouterr().err


def test_summarize_finished_unfinished_torn_and_empty(tmp_path):
    d = tmp_path / "runs"
    done = make_run(d, "20261010-120000-aaaa")
    info = summarize(done)
    assert info["id"] == "20261010-120000-aaaa" and info["command"] == "run -c" and info["status"] == "ok"
    unfinished = d / "20261010-130000-bbbb.jsonl"
    unfinished.write_text(done.read_text().splitlines()[0] + "\n")
    assert summarize(unfinished)["status"] == "unfinished"
    torn = d / "20261010-140000-cccc.jsonl"
    torn.write_text(done.read_text().splitlines()[0] + '\n{"kind": "run_fini')
    assert summarize(torn)["status"] == "unfinished"
    empty = d / "20261010-150000-dddd.jsonl"
    empty.write_text("")
    assert summarize(empty)["status"] == "unfinished" and summarize(empty)["command"] == ""


def test_resolve_run_by_id_prefix_latest_and_errors(tmp_path):
    d = tmp_path / "runs"
    a, b = make_run(d, "20261010-120000-aaaa"), make_run(d, "20261011-120000-bbbb")
    assert resolve_run(d, "20261010-120000-aaaa") == a
    assert resolve_run(d, "20261011") == b
    assert resolve_run(d, "latest") == b
    with pytest.raises(BastetError, match="more than one"):
        resolve_run(d, "2026101")
    with pytest.raises(BastetError, match="no run"):
        resolve_run(d, "20269999")
    for bad in ("../x", "a/b", "", ".."):
        with pytest.raises(BastetError):
            resolve_run(d, bad)


def test_latest_with_no_runs_is_a_clear_error(tmp_path):
    with pytest.raises(BastetError, match="no runs"):
        resolve_run(tmp_path / "runs", "latest")
