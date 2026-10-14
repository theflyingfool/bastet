from pathlib import Path

import pytest
import yaml

from bastet.core.errors import BastetError
from bastet.engine.files import Settings
from bastet.engine.packages import Package
from bastet.roles.builtin import HostInfo
from bastet.roles.contract import parse_role
from bastet.roles.declarative import build


def role(tmp_path, packages, options=None, extra=None):
    folder = tmp_path / "demo"
    folder.mkdir(exist_ok=True)
    data = {"bastet": "role-definition", "name": "demo", "version": "1.0.0", "api": 0, "description": "A demo role",
            "options": options or {"tools": {"type": "list", "items": {"type": "string"}}}, "packages": packages, **(extra or {})}
    path = folder / "demo role.md"
    path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\nNotes.\n", encoding="utf-8")
    return parse_role(path)


def built(r, values, secret_options=frozenset(), **host_kw):
    host = HostInfo(name="vps1", type="vps", data={"os": "Arch Linux"}, root=Path("/x"), lab={}, **host_kw)
    [batch] = build(r, values, host, secret_options)
    return batch.resources


def test_bare_names_and_maps_become_packages(tmp_path):
    r = role(tmp_path, ["example-app", {"name": "git", "state": "absent"}, {"name": "ripgrep", "purge": True}])
    assert [(p.name, p.state) for p in built(r, {})] == [("example-app", "present"), ("git", "absent"), ("ripgrep", "present")]
    assert all(isinstance(p, Package) for p in built(r, {}))


def test_aur_is_refused_naming_the_key(tmp_path):
    with pytest.raises(BastetError, match="aur"):
        built(role(tmp_path, [{"name": "yay-bin", "aur": True}]), {})


def test_a_name_that_resolves_to_a_list_expands(tmp_path):
    r = role(tmp_path, [{"name": "{{ tools }}"}])
    assert [p.name for p in built(r, {"tools": ["git", "vim"]})] == ["git", "vim"]
    assert built(r, {"tools": []}) == []


def test_a_name_that_resolves_to_nothing_is_an_error(tmp_path):
    r = role(tmp_path, [{"name": "{{ tools }}"}])
    with pytest.raises(BastetError, match="packages\\[0\\]: name resolved to nothing"):
        built(r, {})


def test_when_filters_on_host_facts(tmp_path):
    r = role(tmp_path, [{"name": "amd-ucode", "when": "host.physical"}, "git"])
    assert [p.name for p in built(r, {}, physical=False)] == ["git"]
    assert [p.name for p in built(r, {}, physical=True)] == ["amd-ucode", "git"]


def test_before_after_land_on_the_resource(tmp_path):
    [p] = built(role(tmp_path, [{"name": "git", "after": "files"}]), {})
    assert p.run_after == "files" and p.run_before is None


def test_only_entries_using_a_secret_option_are_marked_secret(tmp_path):
    options = {"tools": {"type": "list", "items": {"type": "string"}}, "tok": {"type": "string"}}
    r = role(tmp_path, [{"name": "{{ tools }}"}, {"name": "x-{{ tok }}"}], options)
    resources = built(r, {"tools": ["git"], "tok": "abc"}, secret_options=frozenset({"tok"}))
    assert [(p.name, p.secret) for p in resources] == [("git", False), ("x-abc", True)]


def test_edit_resources_stay_marked_secret_when_any_option_is_secret(tmp_path):
    options = {"port": {"type": "int", "key": "Port", "section": "main"}, "tok": {"type": "string"}}
    r = role(tmp_path, ["git"], options, {"files": [{"path": "/etc/demo.conf", "edit": "ini"}]})
    plain = built(r, {"port": 22, "tok": "abc"})
    secret = built(r, {"port": 22, "tok": "abc"}, secret_options=frozenset({"tok"}))
    assert [p.secret for p in plain if isinstance(p, Settings)] == [False]
    assert [p.secret for p in secret if isinstance(p, Settings)] == [True]
    assert [p.secret for p in secret if isinstance(p, Package)] == [False]


@pytest.mark.parametrize("entry, message", [
    ({"state": "present"}, "packages\\[0\\]: needs a name"),
    ({"name": "x", "state": "held"}, "state must be present or absent"),
    ({"name": "x", "zzz": 1}, "zzz"),
    ({"name": "{{ nope }}"}, "names no option or fact: nope"),
    ({"name": "x", "when": "nope"}, "when names no option: nope"),
    ({"name": "x", "before": "packages", "after": "files"}, "before or after, not both"),
    ({"name": "x", "before": "nonsense"}, "unknown block"),
])
def test_package_entry_errors(tmp_path, entry, message):
    with pytest.raises(BastetError, match=message):
        role(tmp_path, [entry])


def test_an_unset_option_inside_a_name_or_a_list_never_becomes_the_package_none(tmp_path):
    r = role(tmp_path, [{"name": "{{ app }}-tools"}], options={"app": {"type": "string"}})
    with pytest.raises(BastetError, match="unset"):
        built(r, {})
    r = role(tmp_path, [{"name": "{{ [app, 'git'] }}"}], options={"app": {"type": "string"}})
    with pytest.raises(BastetError, match="packages\\[0\\].*resolved to nothing"):
        built(r, {})
    assert [p.name for p in built(r, {"app": "vim"})] == ["vim", "git"]
