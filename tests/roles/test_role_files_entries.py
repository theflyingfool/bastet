from pathlib import Path

import pytest
import yaml

from bastet.core.errors import BastetError
from bastet.engine.command import Command
from bastet.engine.files import Block, Directory, File, Line, Settings, Symlink
from bastet.roles.builtin import HostInfo
from bastet.roles.contract import parse_role
from bastet.roles.declarative import build


def role(tmp_path, files, options=None, template=None):
    folder = tmp_path / "demo"
    folder.mkdir(exist_ok=True)
    if template is not None:
        (folder / "site.j2").write_text(template, encoding="utf-8")
    data = {"bastet": "role-definition", "name": "demo", "version": "1.0.0", "api": 0, "description": "A demo role",
            "options": options or {"domain": {"type": "string"}, "on": {"type": "bool"}}, "files": files}
    path = folder / "demo role.md"
    path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\nNotes.\n", encoding="utf-8")
    return parse_role(path)


def built(r, values=None, secrets=frozenset()):
    host = HostInfo(name="vps1", type="vps", data={"os": "Arch Linux"}, root=Path("/x"), lab={})
    [batch] = build(r, values or {}, host, secrets)
    return batch.resources


def test_content_becomes_a_file_with_triggers(tmp_path):
    [f] = built(role(tmp_path, [{"path": "/etc/x.conf", "content": "host {{ domain }}\n", "mode": "0644",
                                 "reload": ["example-app.service"]}]), {"domain": "example.net"})
    assert isinstance(f, File) and f.content == "host example.net\n" and f.mode == "0644"
    assert [t.label for t in f.on_change] == ["reload example-app.service"]


def test_template_from_the_roles_folder(tmp_path):
    r = role(tmp_path, [{"path": "/etc/site", "template": "site.j2"}], template="{{ domain }}.{{ host.name }}\n")
    [f] = built(r, {"domain": "example.net"})
    assert f.content == "example.net.vps1\n"


def test_a_template_that_fails_names_itself(tmp_path):
    r = role(tmp_path, [{"path": "/etc/site", "template": "site.j2"}], template="{{ nope }}\n")
    with pytest.raises(BastetError, match="site.j2"):
        built(r)


def test_directory_link_line_block(tmp_path):
    r = role(tmp_path, [
        {"path": "/etc/example-app/conf.d", "directory": True, "mode": "0755"},
        {"path": "/srv/current", "link": "/srv/app"},
        {"path": "/etc/default/x", "line": "A=1", "match": "^A=", "unique": True},
        {"path": "/etc/x.conf", "block": "k = v", "marker": "bastet x", "comment": ";", "restart": ["a.service"]},
    ])
    d, link, ln, b = built(r)
    assert isinstance(d, Directory) and d.mode == "0755"
    assert isinstance(link, Symlink) and link.target == "/srv/app"
    assert isinstance(ln, Line) and (ln.line, ln.match, ln.unique) == ("A=1", "^A=", True)
    assert isinstance(b, Block) and (b.marker, b.comment) == ("bastet x", ";")
    assert [t.label for t in b.on_change] == ["restart a.service"]


def test_when_skips_an_entry_and_its_backup(tmp_path):
    r = role(tmp_path, [{"path": "/etc/pacman.conf", "edit": "ini", "backup": True, "when": "on"}], options={
        "on": {"type": "bool"}, "n": {"type": "int", "key": "N", "section": "options"}})
    assert built(r, {"on": False, "n": 1}) == []
    assert any(isinstance(x, Command) for x in built(r, {"on": True, "n": 1}))


def test_edit_gets_triggers(tmp_path):
    r = role(tmp_path, [{"path": "/etc/pacman.conf", "edit": "ini", "reload": ["a.service"]}], options={
        "n": {"type": "int", "key": "N", "section": "options"}})
    [s] = built(r, {"n": 1})
    assert isinstance(s, Settings) and [t.label for t in s.on_change] == ["reload a.service"]


def test_only_entries_using_a_secret_are_marked(tmp_path):
    r = role(tmp_path, [{"path": "/etc/a", "content": "{{ token }}"}, {"path": "/etc/b", "content": "plain"}],
             options={"token": {"type": "string"}})
    a, b = built(r, {"token": "t"}, frozenset({"token"}))
    assert a.secret and not b.secret


def test_content_that_resolves_to_nothing_is_an_error(tmp_path):
    with pytest.raises(BastetError, match="files\\[0\\]: content resolved to nothing"):
        built(role(tmp_path, [{"path": "/etc/x", "content": "{{ domain }}"}]))


@pytest.mark.parametrize("entry, message", [
    ({"path": "/x"}, "exactly one of"),
    ({"path": "/x", "content": "a", "link": "/y"}, "exactly one of"),
    ({"path": "/x", "directory": True, "restart": ["a.service"]}, "restart doesn't apply"),
    ({"path": "/x", "directory": False}, "directory must be true"),
    ({"path": "/x", "link": "/y", "mode": "0644"}, "mode doesn't apply"),
    ({"path": "/x", "block": "b"}, "block needs a marker"),
    ({"path": "/x", "template": "../site.j2"}, "template must be a file in the role's own folder"),
    ({"path": "/x", "template": "/etc/passwd"}, "template must be a file in the role's own folder"),
    ({"path": "/x", "content": "{{ nope }}"}, "names no option or fact: nope"),
    ({"path": "/x", "content": "a", "reload": "example-app.service"}, "reload must be a list"),
    ({"path": "/x", "edit": "ini", "mode": "0644"}, "don't apply to edit"),
    ({"path": "/x", "edit": "ini", "content": "a"}, "exactly one of"),
])
def test_files_entry_errors(tmp_path, entry, message):
    with pytest.raises(BastetError, match=message):
        role(tmp_path, [entry])
