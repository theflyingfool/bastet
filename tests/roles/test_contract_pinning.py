"""Pins behaviour of the role contract that already exists but was thinly tested: falsy values through `when:`,
`edit: ini` creating a file in a new directory, change-triggered actions, a role built with no other role,
and a bad role stopping a run before any host command."""

import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from engine_fakes import Broken, Flag
from typer.testing import CliRunner

import bastet.cli.run as run_mod
from bastet.cli.app import app
from bastet.core.errors import BastetError
from bastet.core.remote import LocalRunner
from bastet.engine.files import Settings
from bastet.engine.model import ABSENT, Trigger
from bastet.engine.run import Batch, collect_items, run_host
from bastet.engine.systemd import TimeSettings, daemon_reload, reload, restart
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import check_values, load_roles, parse_role
from bastet.roles.declarative import build
from bastet.roles.resolve import Applied


def write_role(tmp_path, options, **entries):
    folder = tmp_path / "demo"
    folder.mkdir(exist_ok=True)
    data = {"bastet": "role-definition", "name": "demo", "version": "1.0.0", "api": 0, "description": "A demo role",
            "options": options, **entries}
    path = folder / "demo role.md"
    path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\nNotes.\n", encoding="utf-8")
    return parse_role(path)


def host(**kw):
    base = dict(name="media01", type="vps", data={"os": "Arch Linux"}, root=Path("/nonexistent"), lab={})
    return HostInfo(**{**base, **kw})


def built(role, values, **kw):
    [batch] = build(role, values, host(**kw))
    return batch.resources


# A-2: unset is None; false, 0, "" and [] are values, and a bare `when: option` is plain truthiness.

KINDS = {
    "bool": ({"type": "bool"}, False, True),
    "int": ({"type": "int"}, 0, 1),
    "string": ({"type": "string"}, "", "x"),
    "list": ({"type": "list", "items": {"type": "string"}}, [], ["x"]),
}


def when_role(tmp_path, spec, condition):
    return write_role(tmp_path, {"opt": spec}, commands=[{"name": "c", "run": "true", "unless": "false", "when": condition}])


@pytest.mark.parametrize("kind", KINDS)
def test_a_falsy_value_fails_a_bare_when_but_is_not_unset(tmp_path, kind):
    spec, falsy, truthy = KINDS[kind]
    assert built(when_role(tmp_path, spec, "opt"), {"opt": falsy}) == []
    assert len(built(when_role(tmp_path, spec, "opt"), {"opt": truthy})) == 1
    assert len(built(when_role(tmp_path, spec, "opt is not none"), {"opt": falsy})) == 1
    assert built(when_role(tmp_path, spec, "opt is none"), {"opt": falsy}) == []


@pytest.mark.parametrize("kind", KINDS)
def test_an_unset_option_fails_a_bare_when_and_is_none(tmp_path, kind):
    spec = KINDS[kind][0]
    assert built(when_role(tmp_path, spec, "opt"), {}) == []
    assert built(when_role(tmp_path, spec, "opt is not none"), {}) == []
    assert len(built(when_role(tmp_path, spec, "opt is none"), {})) == 1


@pytest.mark.parametrize("kind", KINDS)
def test_when_reaches_every_kind_of_entry(tmp_path, kind):
    spec, falsy, truthy = KINDS[kind]
    role = write_role(
        tmp_path, {"opt": spec},
        files=[{"path": "/etc/a.conf", "content": "x\n", "when": "opt"}],
        packages=[{"name": "example-app", "when": "opt"}],
        systemd=[{"kind": "unit", "name": "a.service", "enabled": True, "when": "opt"}])
    assert built(role, {"opt": falsy}) == []
    assert built(role, {}) == []
    assert len(built(role, {"opt": truthy})) == 3


# A-13: `edit: ini` makes the file, its directory and its section when they do not exist.

def ini_role(tmp_path, path, options=None):
    options = options or {"tz": {"type": "string", "key": "Zone", "section": "main"}}
    return write_role(tmp_path, options, files=[{"path": str(path), "edit": "ini"}])


def test_ini_wanted_text_for_an_absent_file():
    s = Settings(path="/etc/x.conf", section="main", keys=("Zone",), lines=("Zone = UTC",))
    assert s.wanted(ABSENT) == "[main]\n### Bastet Managed ###\nZone = UTC\n### End Bastet Managed ###\n"


def test_ini_creates_a_new_file_in_a_new_directory_and_is_idempotent(tmp_path):
    target = tmp_path / "new" / "deeper" / "x.conf"
    [s] = [replace(r, root=False) for r in built(ini_role(tmp_path, target), {"tz": "UTC"})]
    first = run_host(LocalRunner(), "h", [Batch("t", [s])], apply=True)
    assert first.ok and [i.status for i in first.items] == ["changed"]
    assert target.read_text() == "[main]\n### Bastet Managed ###\nZone = UTC\n### End Bastet Managed ###\n"
    second = run_host(LocalRunner(), "h", [Batch("t", [s])], apply=True)
    assert [i.status for i in second.items] == ["compliant"]


def test_ini_with_nothing_to_write_does_not_create_the_file(tmp_path):
    target = tmp_path / "new" / "x.conf"
    options = {"on": {"type": "bool", "key": "On", "section": "main", "as": "flag"}}
    [s] = [replace(r, root=False) for r in built(ini_role(tmp_path, target, options), {"on": False})]
    run = run_host(LocalRunner(), "h", [Batch("t", [s])], apply=True)
    assert run.ok and not target.exists()


# A-9: change-triggered actions run once, after all fixes, in order, only for what changed.

def log_trigger(label, log, order=50):
    return Trigger(label, f"echo '{label}' >> {log}", order=order, root=False)


def fired(run):
    return [t.trigger.label for t in run.triggers]


def test_a_trigger_named_by_two_changed_items_runs_once(tmp_path):
    log = tmp_path / "log"
    t = log_trigger("restart a", log)
    items = [Flag(path=str(tmp_path / n), value="1", on_change=(t,)) for n in "ab"]
    run = run_host(LocalRunner(), "h", [Batch("one", items)], apply=True)
    assert fired(run) == ["restart a"] and log.read_text().splitlines() == ["restart a"]


def test_triggers_run_by_order_then_first_seen_after_every_fix(tmp_path):
    log = tmp_path / "log"
    restart_b, restart_a = log_trigger("restart b", log), log_trigger("restart a", log)
    reload_all = log_trigger("daemon-reload", log, order=10)
    one = Flag(path=str(tmp_path / "1"), value="1", on_change=(restart_b, restart_a))
    two = Flag(path=str(tmp_path / "2"), value="1", on_change=(reload_all, restart_b))
    run = run_host(LocalRunner(), "h", [Batch("one", [one, two])], apply=True)
    assert fired(run) == ["daemon-reload", "restart b", "restart a"]
    assert log.read_text().splitlines() == ["daemon-reload", "restart b", "restart a"]


def test_no_trigger_when_nothing_changed(tmp_path):
    log = tmp_path / "log"
    (tmp_path / "a").write_text("1")
    flag = Flag(path=str(tmp_path / "a"), value="1", on_change=(log_trigger("t", log),))
    run = run_host(LocalRunner(), "h", [Batch("one", [flag])], apply=True)
    assert run.triggers == [] and not log.exists() and run.ok


def test_only_the_item_that_changed_fires_its_trigger(tmp_path):
    log = tmp_path / "log"
    (tmp_path / "same").write_text("1")
    same = Flag(path=str(tmp_path / "same"), value="1", on_change=(log_trigger("from same", log),))
    new = Flag(path=str(tmp_path / "new"), value="1", on_change=(log_trigger("from new", log),))
    run = run_host(LocalRunner(), "h", [Batch("one", [same, new])], apply=True)
    assert fired(run) == ["from new"]


def test_no_trigger_for_a_failed_or_skipped_item(tmp_path):
    log = tmp_path / "log"
    broken = Broken(path=str(tmp_path / "a"), value="1", on_change=(log_trigger("from broken", log),))
    later = Flag(path=str(tmp_path / "b"), value="1", on_change=(log_trigger("from later", log),))
    run = run_host(LocalRunner(), "h", [Batch("one", [broken, later])], apply=True)
    assert [i.status for i in run.items] == ["failed", "skipped"]
    assert run.triggers == [] and not log.exists()


def test_a_role_with_entries_naming_one_unit_builds_the_same_trigger_for_each(tmp_path):
    role = write_role(
        tmp_path, {"on": {"type": "bool"}},
        files=[{"path": "/etc/a.conf", "content": "a\n", "restart": ["x.service"], "reload": ["y.service"]},
               {"path": "/etc/b.conf", "line": "k=v", "restart": ["x.service"]},
               {"path": "/etc/c.conf", "block": "k=v", "marker": "demo", "reload": ["y.service"], "when": "on"}])
    [(_, items)] = collect_items([Batch("demo", built(role, {"on": True}))])
    assert [[t.label for t in i.triggers] for i in items] == [
        ["restart x.service", "reload y.service"], ["restart x.service"], ["reload y.service"]]
    assert items[0].triggers == [restart("x.service"), reload("y.service")]
    assert restart("x.service").order > daemon_reload().order


def test_ini_settings_carry_the_entrys_triggers(tmp_path):
    role = write_role(tmp_path, {"tz": {"type": "string", "key": "Zone", "section": "main"}},
                      files=[{"path": "/etc/x.conf", "edit": "ini", "restart": ["x.service"]}])
    [s] = built(role, {"tz": "UTC"})
    assert [t.label for t in s.on_change] == ["restart x.service"]


# A-18: the time entries are blocks; no other role is involved.

def time_role(tmp_path):
    return write_role(tmp_path, {"tz": {"type": "string"}, "ntp": {"type": "bool"}},
                      systemd=[{"kind": "time", "timezone": "{{ tz }}", "ntp": "{{ ntp }}"}])


@pytest.mark.parametrize("os_name", ["Arch Linux", "Debian GNU/Linux 12"])
def test_time_entries_build_with_no_other_role(tmp_path, os_name):
    applied = [Applied(role=time_role(tmp_path), values={"tz": "UTC", "ntp": True})]
    batches = batches_for(applied, host(data={"os": os_name}))
    assert [b.name for b in batches] == ["demo"]
    [t] = batches[0].resources
    assert isinstance(t, TimeSettings) and (t.timezone, t.ntp) == ("UTC", True)


def test_time_entries_with_nothing_set_build_nothing(tmp_path):
    batches = batches_for([Applied(role=time_role(tmp_path), values={})], host())
    assert [b.resources for b in batches] == [[]]


# A-15: a bad role stops the run before any host command.

def test_a_role_that_does_not_parse_is_refused_at_load(tmp_path):
    folder = tmp_path / "roles" / "broken"
    folder.mkdir(parents=True)
    data = {"bastet": "role-definition", "name": "broken", "version": "1.0.0", "api": 0, "description": "x",
            "options": {"tz": {"type": "string"}}, "commands": [{"name": "c", "run": "true", "unless": "false", "when": "nope"}]}
    (folder / "broken role.md").write_text("---\n" + yaml.safe_dump(data) + "---\n", encoding="utf-8")
    with pytest.raises(BastetError, match="when names no option: nope"):
        load_roles(tmp_path / "roles")


def test_a_note_value_of_the_wrong_type_is_refused_before_any_resource_exists(tmp_path):
    role = write_role(tmp_path, {"tz": {"type": "string"}}, files=[{"path": "/etc/tz", "content": "{{ tz }}\n"}])
    with pytest.raises(BastetError):
        check_values(role, {"tz": 5}, "note")


def test_an_entry_that_cannot_resolve_stops_the_build(tmp_path):
    role = write_role(tmp_path, {"p": {"type": "string"}}, files=[{"path": "{{ p }}", "content": "x\n"}])
    with pytest.raises(BastetError, match="path resolved to nothing"):
        batches_for([Applied(role=role, values={})], host())


def git(root, *args):
    subprocess.run(["git", "-C", str(root), "-c", "user.name=T", "-c", "user.email=t@example.com", *args],
                   check=True, capture_output=True)


def test_a_bad_role_stops_a_run_before_any_connection(tmp_path, monkeypatch):
    inv = tmp_path / "Homelab"
    (inv / "hosts").mkdir(parents=True)
    (inv / "Homelab.md").write_text(
        "---\nbastet: lab\nnetworks:\n  servers:\n    cidr: 10.0.20.0/24\n    reserved: .1-.9\n---\n# Homelab\n")
    (inv / "hosts" / "media01.md").write_text("---\nbastet: host\ntype: vps\nip: 10.0.20.11\n---\n# media01\n")
    notes = inv / "_roles" / "hosts" / "media01"
    notes.mkdir(parents=True)
    (notes / "demo.md").write_text('---\nbastet: role\nrole: demo\napplies_to: "[[media01]]"\n---\n')
    git(inv, "init", "-q", "-b", "main")
    git(inv, "add", ".")
    git(inv, "commit", "-q", "-m", "seed")
    cfg = tmp_path / "bastet.yml"
    cfg.write_text(f"inventory:\n  path: {inv}\n")
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))

    role = write_role(tmp_path, {"p": {"type": "string"}}, files=[{"path": "{{ p }}", "content": "x\n"}])
    calls: list[str] = []
    monkeypatch.setattr(run_mod, "load_roles", lambda: {"demo": role})
    monkeypatch.setattr(run_mod, "connect", lambda *a, **k: calls.append("connect"))
    monkeypatch.setattr(run_mod, "run_host", lambda *a, **k: calls.append("run_host"))
    result = CliRunner().invoke(app, ["run", "-c"])
    assert "path resolved to nothing" in result.output, result.output
    assert result.exit_code != 0
    assert calls == []
