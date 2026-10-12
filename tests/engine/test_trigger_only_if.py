import re
import subprocess

from engine_fakes import Flag

from bastet import events
from bastet.core.remote import CommandResult, LocalRunner
from bastet.core.shell import ProbeResult
from bastet.engine import report
from bastet.engine.model import Trigger
from bastet.engine.run import Batch, run_host
from bastet.engine.systemd import Unit, daemon_reload, reload, restart
from bastet.events import runnote


class SystemctlRunner:
    """Runs everything for real except systemctl: it only answers `is-active` for the units in `active`."""

    name = "fake-systemctl"

    def __init__(self, active=()):
        self.active = set(active)
        self.calls: list[str] = []

    def run(self, script, *, timeout=120):
        if "systemctl" not in script:
            return LocalRunner().run(script, timeout=timeout)
        for line in script.splitlines():
            if line.startswith("systemctl "):
                self.calls.append(line)
                m = re.match(r"systemctl is-active --quiet (\S+)", line)
                if m and m.group(1) not in self.active:
                    return CommandResult("", "", 3)
        return CommandResult("", "", 0)


def _run(tmp_path, runner, *triggers):
    flag = Flag(path=str(tmp_path / "a"), value="1", on_change=tuple(triggers))
    return run_host(runner, "h", [Batch("one", [flag])], apply=True)


def test_restart_and_reload_only_act_on_a_running_unit():
    assert restart("x.service").only_if == "systemctl is-active --quiet x.service"
    assert reload("x.service").only_if == "systemctl is-active --quiet x.service"
    assert daemon_reload().only_if is None


def test_a_restart_is_skipped_when_the_unit_is_not_active(tmp_path):
    runner = SystemctlRunner()
    run = _run(tmp_path, runner, restart("x.service"))
    assert [(t.trigger.label, t.ok, t.skipped) for t in run.triggers] == [("restart x.service", True, True)]
    assert "systemctl restart x.service" not in runner.calls
    assert run.ok


def test_a_restart_runs_when_the_unit_is_active(tmp_path):
    runner = SystemctlRunner(active={"x.service"})
    run = _run(tmp_path, runner, restart("x.service"))
    assert [(t.ok, t.skipped) for t in run.triggers] == [(True, False)]
    assert "systemctl restart x.service" in runner.calls


def test_a_reload_is_skipped_for_a_stopped_or_failed_unit_and_runs_for_a_running_one(tmp_path):
    runner = SystemctlRunner(active={"up.service"})
    run = _run(tmp_path, runner, reload("down.service"), reload("up.service"))
    assert [t.skipped for t in run.triggers] == [True, False]
    assert "systemctl reload-or-restart up.service" in runner.calls
    assert "systemctl reload-or-restart down.service" not in runner.calls


def test_a_skipped_trigger_does_not_stop_the_later_ones(tmp_path):
    run = _run(tmp_path, SystemctlRunner(), restart("x.service"), daemon_reload())
    assert [(t.trigger.label, t.skipped) for t in run.triggers] == [("daemon-reload", False), ("restart x.service", True)]


def test_equal_triggers_run_once(tmp_path):
    run = _run(tmp_path, SystemctlRunner(active={"x.service"}), restart("x.service"), restart("x.service"))
    assert len(run.triggers) == 1


def test_only_if_with_a_plain_command(tmp_path):
    log = tmp_path / "log"
    no = Trigger("no", f"echo no >> {log}", root=False, only_if="false")
    yes = Trigger("yes", f"echo yes >> {log}", root=False, only_if="true", order=60)
    run = _run(tmp_path, LocalRunner(), no, yes)
    assert [t.skipped for t in run.triggers] == [True, False]
    assert log.read_text() == "yes\n"


def test_a_skipped_trigger_shows_in_the_report(tmp_path):
    run = _run(tmp_path, SystemctlRunner(), restart("x.service"))
    assert "restart x.service skipped: not running" in report.render_host(run, full=True)


def test_a_skipped_trigger_event_says_so(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(events, "emit", lambda kind, host=None, **data: seen.append((kind, data)))
    _run(tmp_path, SystemctlRunner(), restart("x.service"))
    fired = [d for k, d in seen if k == "trigger_fired"]
    assert fired == [{"trigger": "restart x.service", "ok": True, "error": None, "skipped": "not running"}]


def test_a_skipped_trigger_in_the_run_note():
    ev = [{"kind": "trigger_fired", "host": "h",
           "data": {"trigger": "restart x", "ok": True, "error": None, "skipped": "not running"}}]
    assert "- trigger restart x skipped: not running" in runnote._host_section("h", ev, 2)


def test_a_missing_unit_gets_a_clear_message_after_the_reload():
    u = Unit(name="gitea.service", enabled=True, state="up")
    cur = u.current({"show": ProbeResult(0, "LoadState=not-found\nActiveState=inactive")})
    cmds = u.fix(u.compare(cur), cur)
    assert cmds[0] == "systemctl daemon-reload"
    assert "unit gitea.service does not exist" in cmds[1] and "exit 1" in cmds[1]
    assert cmds[2:] == ["systemctl enable gitea.service", "systemctl start gitea.service"]


def test_the_missing_unit_message_is_what_the_shell_prints(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "systemctl"
    fake.write_text('#!/bin/sh\n[ "$1" = cat ] && exit 1\nexit 0\n')
    fake.chmod(0o755)
    u = Unit(name="gitea.service", enabled=True)
    cur = {"exists": False, "enabled": False, "state": "down"}
    r = subprocess.run(["sh", "-e", "-c", "\n".join(u.fix(u.compare(cur), cur))], capture_output=True, text=True,
                       env={"PATH": f"{bin_dir}:/usr/bin:/bin"})
    assert r.returncode == 1
    assert "unit gitea.service does not exist (is the package" in r.stderr
