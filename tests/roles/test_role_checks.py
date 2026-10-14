from pathlib import Path

import pytest
import yaml

from bastet.cli.run import distinct_notes
from bastet.core.errors import BastetError
from bastet.engine.run import Batch, Note
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import _parse_yml_role, load_roles, parse_role
from bastet.roles.declarative import build
from bastet.roles.resolve import Applied

OPTIONS = {"tz": {"type": "string"}, "ntp": {"type": "bool"}}


def role(tmp_path, options=None, **extra):
    folder = tmp_path / "demo"
    folder.mkdir(exist_ok=True)
    data = {"bastet": "role-definition", "name": "demo", "version": "1.0.0", "api": 0, "description": "A demo role",
            "options": OPTIONS if options is None else options, **extra}
    path = folder / "demo role.md"
    path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\nNotes.\n", encoding="utf-8")
    return parse_role(path)


def host(type="vps", **data):
    return HostInfo(name="media01", type=type, data={"os": "Arch Linux", **data}, root=Path("/x"), lab={})


def notes_of(r, values=None, origins=None, **kw):
    return [n for b in build(r, values or {}, host(**kw), origins=origins) for n in b.notes]


def check(when="true", level="warning", message="look at this", **kw):
    return {"when": when, "level": level, "message": message, **kw}


def test_a_holding_warning_or_info_check_becomes_a_note(tmp_path):
    r = role(tmp_path, checks=[check("tz is none", "warning", "no zone set"), check("not ntp", "info", "ntp is off, tz={{ tz or '-' }}"),
                               check("tz == 'UTC'", "warning", "never shown")])
    assert notes_of(r) == [Note("warning", "demo", "no zone set"), Note("info", "demo", "ntp is off, tz=-")]
    assert notes_of(r, {"tz": "UTC"}) == [Note("info", "demo", "ntp is off, tz=UTC"), Note("warning", "demo", "never shown")]


def test_an_error_check_that_holds_stops_the_host_before_any_entry_is_built(tmp_path):
    r = role(tmp_path, checks=[check("ntp and not tz", "error", "ntp needs tz")],
             systemd=[{"kind": "time", "timezone": "{{ tz }}"}, {"kind": "unit", "name": "{{ 1 / 0 }}"}])
    with pytest.raises(BastetError, match="demo: ntp needs tz") as exc:
        build(r, {"ntp": True}, host())
    assert exc.value.file == r.path


def test_notes_ride_on_the_batch_and_default_to_none(tmp_path):
    assert Batch("x", []).notes == []
    r = role(tmp_path, checks=[check()])
    [batch] = build(r, {}, host())
    assert batch.notes == [Note("warning", "demo", "look at this")]


def test_batches_for_threads_the_notes_and_origins(tmp_path):
    r = role(tmp_path, checks=[check("applied.origin.tz != ''", "info", "tz from {{ applied.origin.tz }}")])
    [batch] = batches_for([Applied(r, {"tz": "UTC"}, origins={"tz": "group lab-vms"})], host())
    assert batch.notes == [Note("info", "demo", "tz from group lab-vms")]


def test_origin_is_empty_for_an_unset_option_and_keeps_the_override_marker(tmp_path):
    r = role(tmp_path, checks=[check(level="info", message="[{{ applied.origin.tz }}] [{{ applied.origin.ntp }}]")])
    assert notes_of(r, {"tz": "UTC"}, {"tz": "host media01 (override)"})[0].message == "[host media01 (override)] []"
    assert notes_of(r)[0].message == "[] []"


def test_origin_works_in_entry_conditions(tmp_path):
    r = role(tmp_path, systemd=[{"kind": "time", "timezone": "UTC", "when": "applied.origin.tz == 'lab'"}])
    [batch] = build(r, {"tz": "x"}, host(), origins={"tz": "lab"})
    assert len(batch.resources) == 1
    [batch] = build(r, {"tz": "x"}, host(), origins={"tz": "type vps"})
    assert batch.resources == []


@pytest.mark.parametrize("bad, text", [
    ({"level": "warning", "message": "m"}, "needs when"),
    ({"when": "true", "message": "m"}, "needs level"),
    ({"when": "true", "level": "warning"}, "needs message"),
    ({"when": "true", "level": "fatal", "message": "m"}, "level must be one of info, warning, error"),
    ({"when": "true", "level": "info", "message": "m", "extra": 1}, "unknown key extra"),
    ({"when": "nope", "level": "info", "message": "m"}, "when names no option: nope"),
    ({"when": "true", "level": "info", "message": "{{ nope }}"}, "names no option or fact: nope"),
    ({"when": "host.arch_likee", "level": "info", "message": "m"}, "names no host fact: arch_likee"),
    ({"when": "true", "level": "info", "message": "{{ host.nmae }}"}, "names no host fact: nmae"),
    ({"when": "applied.origin.nope == ''", "level": "info", "message": "m"}, "applied.origin names no option: nope"),
    ({"when": "1 +", "level": "info", "message": "m"}, "when"),
])
def test_a_bad_check_is_refused_with_the_role_file_and_key(tmp_path, bad, text):
    with pytest.raises(BastetError, match=text) as exc:
        role(tmp_path, checks=[bad])
    assert exc.value.file is not None and exc.value.file.name == "demo role.md" and exc.value.key in ("checks", "extra")


def test_checks_must_be_a_list_of_maps(tmp_path):
    with pytest.raises(BastetError, match="checks must be a list"):
        role(tmp_path, checks={"when": "true"})
    with pytest.raises(BastetError, match="each check is a map"):
        role(tmp_path, checks=["x"])


def test_a_yml_role_cannot_have_checks(tmp_path):
    (tmp_path / "old").mkdir()
    (tmp_path / "old" / "role.yml").write_text("description: old\nchecks: []\n")
    with pytest.raises(BastetError, match="checks are for Markdown roles"):
        _parse_yml_role(tmp_path / "old" / "role.yml")


def test_the_shipped_roles_still_load():
    assert load_roles()


@pytest.mark.parametrize("entry_key, entry", [
    ("systemd", {"kind": "time", "timezone": "UTC", "when": "host.arch_likee"}),
    ("systemd", {"kind": "time", "timezone": "{{ host.arch_likee }}"}),
    ("packages", {"name": "x", "when": "host.nope"}),
    ("files", {"path": "/etc/x", "content": "{{ host.nope }}"}),
    ("commands", {"name": "n", "run": "r", "unless": "u", "when": "host.nope"}),
])
def test_unknown_host_facts_are_refused_in_every_entry(tmp_path, entry_key, entry):
    with pytest.raises(BastetError, match="names no host fact: ") as exc:
        role(tmp_path, **{entry_key: [entry]})
    assert exc.value.file is not None


def test_host_facts_are_found_through_the_syntax_tree_not_text(tmp_path):
    role(tmp_path, systemd=[{"kind": "time", "timezone": "UTC", "when": "host.name == 'host.nope' and host['arch_like']"}])
    with pytest.raises(BastetError, match="names no host fact: bad"):
        role(tmp_path, systemd=[{"kind": "time", "timezone": "UTC", "when": "host['bad']"}])
    role(tmp_path, systemd=[{"kind": "time", "timezone": "UTC", "when": "lab.host.whatever is none"}])


def test_a_time_entry_on_a_container_notes_the_dropped_values(tmp_path):
    r = role(tmp_path, systemd=[{"kind": "time", "timezone": "{{ tz }}", "ntp": "{{ ntp }}"}])
    [n] = notes_of(r, {"tz": "UTC", "ntp": True}, type="lxc")
    assert n.level == "info" and n.role == "demo" and "Proxmox node" in n.message and n.message.startswith("time:")
    assert notes_of(r, {"tz": "UTC"}, type="lxc") == []  # nothing was dropped
    assert notes_of(r, {"tz": "UTC", "ntp": True}) == []  # not a container


def test_a_hostname_entry_on_a_container_notes_the_skip(tmp_path):
    r = role(tmp_path, systemd=[{"kind": "hostname"}])
    [n] = notes_of(r, type="lxc")
    assert n.level == "info" and n.message.startswith("hostname:") and "Proxmox node" in n.message
    assert notes_of(r) == []


def test_distinct_notes_lists_each_role_and_message_once_in_order():
    a, b = Note("warning", "r1", "m"), Note("info", "r2", "m")
    batches = [Batch("r1", [], [a, b]), Batch("r1", [], [a]), Batch("r2", [], [b, Note("info", "r2", "other")])]
    assert distinct_notes(batches) == [a, b, Note("info", "r2", "other")]
