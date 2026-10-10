from bastet.cli.app import app
from bastet.core.config import data_dir
from bastet.events.jsonl import JsonlSink, runs_dir
from bastet.events.recorder import recording
from bastet import events


def record(run_id, command="run -c"):
    sink = JsonlSink(runs_dir(data_dir()), run_id)
    with recording(command, [sink], run_id=run_id):
        events.emit("host_finished", "pve1", status="ok", changed=1, failed=0, skipped=0)
    return sink.path


def test_runs_with_nothing_recorded(runner, inventory):
    result = runner.invoke(app, ["runs"])
    assert result.exit_code == 0 and "No runs recorded yet." in result.output


def test_runs_lists_newest_first_with_status_and_command(runner, inventory):
    record("20261010-120000-aaaa", "run -c")
    record("20261011-120000-bbbb", "run -a pve1")
    result = runner.invoke(app, ["runs"])
    assert result.exit_code == 0
    lines = [line for line in result.output.splitlines() if "2026" in line]
    assert lines[0].startswith("  20261011-120000-bbbb") and "run -a pve1" in lines[0] and "ok" in lines[0]
    assert lines[1].startswith("  20261010-120000-aaaa")


def test_runs_shows_twenty_unless_all(runner, inventory):
    for i in range(25):
        record(f"202610{i:02d}-120000-aaaa")
    assert len([l for l in runner.invoke(app, ["runs"]).output.splitlines() if "2026" in l]) == 20
    assert len([l for l in runner.invoke(app, ["runs", "--all"]).output.splitlines() if "2026" in l]) == 25


def test_export_prints_the_file_or_writes_it(runner, inventory, tmp_path):
    path = record("20261010-120000-aaaa")
    result = runner.invoke(app, ["runs", "export", "latest"])
    assert result.exit_code == 0 and result.output == path.read_text()
    dest = tmp_path / "out.jsonl"
    result = runner.invoke(app, ["runs", "export", "20261010", "--out", str(dest)])
    assert result.exit_code == 0 and dest.read_text() == path.read_text()


def test_export_errors_are_clean(runner, inventory):
    record("20261010-120000-aaaa")
    for ident in ("../etc/passwd", "nope"):
        result = runner.invoke(app, ["runs", "export", ident])
        assert result.exit_code == 1 and "Traceback" not in result.output
