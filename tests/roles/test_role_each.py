from pathlib import Path

import pytest
import yaml

from bastet.core.errors import BastetError
from bastet.roles.builtin import HostInfo
from bastet.roles.contract import parse_role
from bastet.roles.declarative import build

OPTIONS = {
    "pkgs": {"type": "list", "items": {"type": "string"}},
    "sites": {"type": "list", "items": {"type": "object", "fields": {"domain": {"type": "string"}, "upstream": {"type": "string"}}}},
    "mounts": {"type": "map", "items": {"type": "string"}},
    "tokens": {"type": "list", "secret": True, "items": {"type": "string"}},
    "zone": {"type": "string"},
}
SITES = [{"domain": "app.example.net", "upstream": "10.1.0.5:8080"}, {"domain": "wiki.example.net", "upstream": "10.1.0.6:3000"}]


def role(tmp_path, **extra):
    folder = tmp_path / "demo"
    folder.mkdir(exist_ok=True)
    data = {"bastet": "role-definition", "name": "demo", "version": "1.0.0", "api": 0, "description": "A demo role",
            "options": OPTIONS, **extra}
    path = folder / "demo role.md"
    path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\nNotes.\n", encoding="utf-8")
    return parse_role(path)


def built(r, values=None, secrets=frozenset()):
    host = HostInfo(name="media01", type="vps", data={"os": "Arch Linux"}, root=Path("/x"), lab={})
    [batch] = build(r, values or {}, host, secrets)
    return batch.resources


def ids(resources):
    return sorted(x.identity for x in resources)


def test_a_list_of_strings_builds_one_package_per_item(tmp_path):
    r = role(tmp_path, packages=[{"name": "{{ item }}", "each": "pkgs"}])
    assert [p.name for p in built(r, {"pkgs": ["htop", "tmux"]})] == ["htop", "tmux"]


def test_a_list_of_objects_builds_one_file_per_item_from_content(tmp_path):
    r = role(tmp_path, files=[{"path": "/etc/caddy/{{ item.domain }}.conf", "content": "{{ item.domain }} -> {{ item.upstream }}\n",
                               "each": "sites"}])
    files = {f.path: f.content for f in built(r, {"sites": SITES})}
    assert files == {"/etc/caddy/app.example.net.conf": "app.example.net -> 10.1.0.5:8080\n",
                     "/etc/caddy/wiki.example.net.conf": "wiki.example.net -> 10.1.0.6:3000\n"}


def test_a_template_sees_item(tmp_path):
    role(tmp_path)
    (tmp_path / "demo" / "site.j2").write_text("host {{ item.domain }}\n", encoding="utf-8")
    r = role(tmp_path, files=[{"path": "/etc/{{ item.domain }}", "template": "site.j2", "each": "sites"}])
    assert sorted(f.content for f in built(r, {"sites": SITES})) == ["host app.example.net\n", "host wiki.example.net\n"]


def test_a_map_gives_key_and_item(tmp_path):
    r = role(tmp_path, files=[{"path": "/mnt/{{ key }}.conf", "content": "{{ item }}", "each": "mounts"}])
    files = {f.path: f.content for f in built(r, {"mounts": {"media": "10.1.0.9:/media", "docs": "10.1.0.9:/docs"}})}
    assert files == {"/mnt/media.conf": "10.1.0.9:/media", "/mnt/docs.conf": "10.1.0.9:/docs"}


def test_an_empty_or_unset_option_builds_nothing(tmp_path):
    r = role(tmp_path, packages=[{"name": "{{ item }}", "each": "pkgs"}])
    assert built(r, {"pkgs": []}) == []
    assert built(r, {}) == []


def test_when_is_evaluated_per_item(tmp_path):
    r = role(tmp_path, packages=[{"name": "{{ item }}", "each": "pkgs", "when": "item != 'tmux'"}])
    assert [p.name for p in built(r, {"pkgs": ["htop", "tmux", "vim"]})] == ["htop", "vim"]


def test_each_works_inside_a_section_with_a_combined_when(tmp_path):
    r = role(tmp_path, sections=[{"when": "zone == 'UTC'", "packages": [{"name": "{{ item }}", "each": "pkgs", "when": "item != 'tmux'"}]}])
    assert [p.name for p in built(r, {"pkgs": ["htop", "tmux"], "zone": "UTC"})] == ["htop"]
    assert built(r, {"pkgs": ["htop"], "zone": "CET"}) == []


def test_two_items_building_the_same_resource_are_refused_naming_both(tmp_path):
    r = role(tmp_path, packages=["first"], files=[{"path": "/etc/{{ item.domain }}", "content": "x", "each": "sites"}])
    with pytest.raises(BastetError) as exc:
        built(r, {"sites": [SITES[0], SITES[1], SITES[0]]})
    for text in ("demo", "files[0]", "item 0", "item 2"):
        assert text in exc.value.message


def test_reordering_the_list_builds_the_same_resources(tmp_path):
    r = role(tmp_path, files=[{"path": "/etc/{{ item.domain }}", "content": "x", "each": "sites"}])
    assert ids(built(r, {"sites": SITES})) == ids(built(r, {"sites": SITES[::-1]}))


def test_there_is_no_index_name(tmp_path):
    with pytest.raises(BastetError, match="names no option"):
        role(tmp_path, packages=[{"name": "{{ item }}-{{ index }}", "each": "pkgs"}])


def test_item_and_key_are_refused_outside_an_each_entry(tmp_path):
    with pytest.raises(BastetError, match="item"):
        role(tmp_path, packages=[{"name": "{{ item }}"}])
    with pytest.raises(BastetError, match="item"):
        role(tmp_path, packages=[{"name": "x", "when": "item"}])
    with pytest.raises(BastetError, match="key"):
        role(tmp_path, packages=[{"name": "{{ key }}", "each": "pkgs"}])  # key only for a map


def test_each_must_name_a_list_or_map_option(tmp_path):
    with pytest.raises(BastetError, match="list or map"):
        role(tmp_path, packages=[{"name": "x", "each": "zone"}])
    with pytest.raises(BastetError, match="no option"):
        role(tmp_path, packages=[{"name": "x", "each": "nope"}])


def test_each_is_refused_on_edit_and_render_entries(tmp_path):
    with pytest.raises(BastetError, match="each"):
        role(tmp_path, files=[{"path": "/etc/x.ini", "edit": "ini", "each": "pkgs"}])


def test_a_secret_list_marks_the_entries_secret(tmp_path):
    r = role(tmp_path, files=[{"path": "/etc/{{ item }}", "content": "x", "each": "tokens"}], packages=[{"name": "plain"}])
    made = built(r, {"tokens": ["a", "b"]}, frozenset({"tokens"}))
    assert sorted(x.secret for x in made) == [False, True, True]


def test_a_unit_loop(tmp_path):
    r = role(tmp_path, systemd=[{"kind": "unit", "name": "{{ item }}.service", "enabled": True, "each": "pkgs"}])
    assert [u.name for u in built(r, {"pkgs": ["a", "b"]})] == ["a.service", "b.service"]


def test_a_user_loop(tmp_path):
    r = role(tmp_path, users=[{"kind": "user", "name": "{{ item }}", "each": "pkgs"}])
    assert [u.name for u in built(r, {"pkgs": ["ann", "bob"]})] == ["ann", "bob"]


def test_a_command_loop_and_its_duplicate(tmp_path):
    r = role(tmp_path, commands=[{"name": "init {{ item }}", "run": "init {{ item }}", "unless": "test -e /srv/{{ item }}",
                                  "each": "pkgs"}])
    assert [c.name for c in built(r, {"pkgs": ["a", "b"]})] == ["init a", "init b"]
    with pytest.raises(BastetError, match="item 0.*item 1"):
        built(r, {"pkgs": ["a", "a"]})
