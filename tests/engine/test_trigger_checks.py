from bastet.core.remote import LocalRunner
from bastet.engine.model import Trigger
from bastet.engine.run import Batch, run_host
from bastet.engine.systemd import reload, restart
from engine_fakes import Flag


def _run(tmp_path, *triggers):
    flag = Flag(path=str(tmp_path / "a"), value="1", on_change=tuple(triggers))
    return run_host(LocalRunner(), "h", [Batch("one", [flag])], apply=True)


def test_a_check_that_passes_at_once(tmp_path):
    log = tmp_path / "log"
    t = Trigger("t", f"echo ran >> {log}", root=False, check=f"echo checked >> {log}", check_wait=0.01)
    run = _run(tmp_path, t)
    assert run.triggers[0].ok
    assert log.read_text().split() == ["ran", "checked"]


def test_a_check_that_passes_on_the_third_try(tmp_path):
    counter = tmp_path / "n"
    check = f"n=$(cat {counter} 2>/dev/null || echo 0); echo $((n+1)) > {counter}; [ $n -ge 2 ]"
    run = _run(tmp_path, Trigger("t", "true", root=False, check=check, check_wait=0.01))
    assert run.triggers[0].ok
    assert counter.read_text().strip() == "3"


def test_a_check_that_never_passes_fails_the_trigger_and_skips_later_ones(tmp_path):
    log = tmp_path / "log"
    bad = Trigger("restart x", "true", root=False, check="false", check_tries=2, check_wait=0.01)
    later = Trigger("later", f"echo later >> {log}", order=60, root=False)
    run = _run(tmp_path, bad, later)
    assert [t.ok for t in run.triggers] == [False]
    assert run.triggers[0].error == "restart x: still not running after 2 checks"
    assert not log.exists()
    assert not run.ok


def test_restart_has_a_check_and_reload_does_not():
    assert restart("x.service").check == "systemctl is-active --quiet x.service"
    assert reload("x.service").check is None
