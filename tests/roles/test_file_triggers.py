from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from engine_fakes import Flag

from bastet.core.errors import BastetError
from bastet.core.remote import LocalRunner
from bastet.engine.files import Line, Settings
from bastet.engine.run import Batch, run_host
from bastet.roles.builtin import HostInfo
from bastet.roles.contract import parse_role
from bastet.roles.declarative import build


def role(tmp_path, files, options=None):
    folder = tmp_path / "demo"
    folder.mkdir(exist_ok=True)
    data = {"bastet": "role-definition", "name": "demo", "version": "1.0.0", "api": 0, "description": "A demo role",
            "options": options or {"cmd": {"type": "string"}}, "files": files}
    path = folder / "demo role.md"
    path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\nNotes.\n", encoding="utf-8")
    return parse_role(path)


def built(r, values=None):
    host = HostInfo(name="vps1", type="vps", data={"os": "Arch Linux"}, root=Path("/x"), lab={})
    [batch] = build(r, values or {}, host, frozenset())
    return batch.resources


def labels(res):
    return [t.label for t in res.on_change]


def test_daemon_reload_comes_first_then_restart_reload_and_on_change(tmp_path):
    r = role(tmp_path, [{"path": "/etc/systemd/system/a.service", "content": "x\n", "restart": ["a.service"],
                         "reload": ["b.service"], "daemon_reload": True,
                         "on_change": [{"name": "apply sysctl", "run": "sysctl --system"}]}])
    [f] = built(r)
    assert labels(f) == ["daemon-reload", "restart a.service", "reload b.service", "apply sysctl"]
    assert [t.order for t in f.on_change] == [10, 50, 50, 50]
    assert f.on_change[-1].command == "sysctl --system" and f.on_change[-1].root and f.on_change[-1].only_if is None


def test_daemon_reload_false_adds_nothing(tmp_path):
    [f] = built(role(tmp_path, [{"path": "/etc/a", "content": "x", "daemon_reload": False}]))
    assert f.on_change == ()


def test_on_change_resolves_expressions(tmp_path):
    r = role(tmp_path, [{"path": "/etc/a", "content": "x", "on_change": [{"name": "run {{ cmd }}", "run": "{{ cmd }} --now"}]}])
    [f] = built(r, {"cmd": "tool"})
    assert (f.on_change[0].label, f.on_change[0].command) == ("run tool", "tool --now")


@pytest.mark.parametrize("entry", [
    {"content": "x"}, {"template": "t.j2"}, {"line": "a=b"}, {"block": "b", "marker": "m"},
])
def test_both_keys_are_allowed_on_the_trigger_forms(tmp_path, entry):
    (tmp_path / "demo").mkdir(exist_ok=True)
    (tmp_path / "demo" / "t.j2").write_text("x\n")
    role(tmp_path, [{"path": "/etc/a", **entry, "daemon_reload": True, "on_change": [{"name": "n", "run": "r"}]}])


def test_edit_gets_the_new_triggers(tmp_path):
    r = role(tmp_path, [{"path": "/etc/pacman.conf", "edit": "ini", "daemon_reload": True,
                         "on_change": [{"name": "n", "run": "r"}]}], options={"n": {"type": "int", "key": "N", "section": "options"}})
    [s] = built(r, {"n": 1})
    assert isinstance(s, Settings) and labels(s) == ["daemon-reload", "n"]


def test_a_line_gets_the_new_triggers(tmp_path):
    [line] = built(role(tmp_path, [{"path": "/etc/a", "line": "a=b", "on_change": [{"name": "n", "run": "r"}]}]))
    assert isinstance(line, Line) and labels(line) == ["n"]


@pytest.mark.parametrize("form", [{"directory": True}, {"link": "/y"}])
@pytest.mark.parametrize("key, value", [("daemon_reload", True), ("on_change", [{"name": "n", "run": "r"}])])
def test_directory_and_link_refuse_the_keys(tmp_path, form, key, value):
    with pytest.raises(BastetError, match=f"{key} doesn't apply"):
        role(tmp_path, [{"path": "/x", **form, key: value}])


@pytest.mark.parametrize("entry, message", [
    ({"daemon_reload": "yes"}, "daemon_reload must be true or false"),
    ({"on_change": "r"}, "on_change must be a list"),
    ({"on_change": []}, "on_change must be a list"),
    ({"on_change": [{"name": "n"}]}, "on_change must be a list"),
    ({"on_change": [{"name": "", "run": "r"}]}, "on_change must be a list"),
    ({"on_change": [{"name": "n", "run": " "}]}, "on_change must be a list"),
    ({"on_change": [{"name": "n", "run": "{{ nope }}"}]}, "names no option or fact: nope"),
])
def test_bad_values_are_refused(tmp_path, entry, message):
    with pytest.raises(BastetError, match=message):
        role(tmp_path, [{"path": "/x", "content": "a", **entry}])


def test_conf_d_drop_in_through_files_has_no_daemon_reload(tmp_path):
    [f] = built(role(tmp_path, [{"path": "/etc/example/conf.d/10-a.conf", "content": "x\n", "restart": ["example-app.service"]}]))
    assert labels(f) == ["restart example-app.service"]


def test_a_dropin_systemd_entry_keeps_daemon_reload_and_restart():
    from bastet.engine.systemd import drop_in
    assert labels(drop_in("example-app.service", "10-a", "x")) == ["daemon-reload", "restart example-app.service"]


def unrooted(files):
    """The same resources run as the test user: no sudo here."""
    return [replace(f, root=False, on_change=tuple(replace(t, root=False) for t in f.on_change)) for f in files]


def _run(tmp_path, runner, *flags):
    return run_host(runner, "h", [Batch("one", list(flags))], apply=True)


def test_two_entries_naming_the_same_on_change_command_run_it_once(tmp_path):
    log = tmp_path / "log"
    r = role(tmp_path, [{"path": str(tmp_path / n), "content": "x\n", "on_change": [{"name": "apply", "run": f"echo ran >> {log}"}]}
                        for n in ("one", "two")])
    files = built(r)
    run = run_host(LocalRunner(), "h", [Batch("demo", unrooted(files))], apply=True)
    assert run.ok
    assert [t.trigger.label for t in run.triggers] == ["apply"]
    assert log.read_text() == "ran\n"


def test_an_unchanged_file_runs_no_triggers(tmp_path):
    log = tmp_path / "log"
    target = tmp_path / "one"
    target.write_text("x\n")
    r = role(tmp_path, [{"path": str(target), "content": "x\n", "on_change": [{"name": "apply", "run": f"echo ran >> {log}"}]}])
    run = run_host(LocalRunner(), "h", [Batch("demo", unrooted(built(r)))], apply=True)
    assert run.triggers == [] and not log.exists()


def test_a_failing_resource_does_not_run_its_triggers(tmp_path):
    from engine_fakes import Broken
    log = tmp_path / "log"
    from bastet.engine.model import Trigger
    flag = Broken(path=str(tmp_path / "a"), value="1", on_change=(Trigger("t", f"echo ran >> {log}", root=False),))
    run = _run(tmp_path, LocalRunner(), flag)
    assert run.triggers == [] and not log.exists()
    assert not run.ok
    assert Flag is not None
