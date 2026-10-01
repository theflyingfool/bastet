from bastet.core.remote import LocalRunner
from bastet.engine.command import Command
from bastet.engine.run import Batch, run_host


def test_guarded_command_runs_once(tmp_path):
    marker = tmp_path / "done"
    c = Command(name="make marker", run=f"touch {marker}", unless=f"test -e {marker}", root=False)
    first = run_host(LocalRunner(), "h", [Batch("t", [c])], apply=True)
    assert first.ok and first.items[0].status == "changed" and marker.exists()
    assert run_host(LocalRunner(), "h", [Batch("t", [c])], apply=True).items[0].status == "compliant"
