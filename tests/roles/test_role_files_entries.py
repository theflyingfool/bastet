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
                                 "reload": ["example-app.service"]}]), {"domain": "example.com"})
    assert isinstance(f, File) and f.content == "host example.com\n" and f.mode == "0644"
    assert [t.label for t in f.on_change] == ["reload example-app.service"]


def test_template_from_the_roles_folder(tmp_path):
    r = role(tmp_path, [{"path": "/etc/site", "template": "site.j2"}], template="{{ domain }}.{{ host.name }}\n")
    [f] = built(r, {"domain": "example.com"})
    assert f.content == "example.com.vps1\n"


def test_a_template_that_fails_at_build_names_itself(tmp_path):
    r = role(tmp_path, [{"path": "/etc/site", "template": "site.j2"}], template="{{ domain }}\n")
    with pytest.raises(BastetError, match="site.j2"):
        built(r)


def test_a_template_using_an_unknown_name_is_refused_when_the_role_is_read(tmp_path):
    with pytest.raises(BastetError, match=r"files\[0\].template \(site.j2\).*nope"):
        role(tmp_path, [{"path": "/etc/site", "template": "site.j2"}], template="{{ nope }}\n")


def test_a_template_file_that_does_not_exist_is_refused_when_the_role_is_read(tmp_path):
    with pytest.raises(BastetError, match="site.j2.*can.t read the template"):
        role(tmp_path, [{"path": "/etc/site", "template": "site.j2"}])


def test_role_templates_are_sandboxed(tmp_path):
    r = role(tmp_path, [{"path": "/etc/site", "template": "site.j2"}], template="{{ ''.__class__ }}\n")
    with pytest.raises(BastetError, match="site.j2"):
        built(r)


def test_a_template_never_writes_an_unset_option_as_none(tmp_path):
    r = role(tmp_path, [{"path": "/etc/site", "template": "site.j2"}], template="zone={{ domain }}\n")
    with pytest.raises(BastetError, match="site.j2.*unset"):
        built(r)
    r = role(tmp_path, [{"path": "/etc/site", "template": "site.j2"}], template="{% if domain %}zone={{ domain }}{% endif %}\n")
    assert built(r)[0].content == "\n"


def test_a_template_naming_a_secret_option_makes_its_file_secret(tmp_path):
    r = role(tmp_path, [{"path": "/etc/site", "template": "site.j2"}, {"path": "/etc/b", "content": "plain"}],
             options={"token": {"type": "string"}}, template="t={{ token }}\n")
    site, b = built(r, {"token": "t"}, frozenset({"token"}))
    assert site.secret and not b.secret


def test_every_field_of_the_new_forms_resolves_expressions(tmp_path):
    opts = {"app": {"type": "string"}, "m": {"type": "string"}, "who": {"type": "string"}, "unit": {"type": "string"}}
    r = role(tmp_path, [
        {"path": "/etc/{{ app }}.conf", "content": "x", "mode": "{{ m }}", "owner": "{{ who }}", "group": "{{ who }}",
         "validate": "{{ app }} -t %s", "restart": ["{{ unit }}"], "reload": ["{{ app }}.service"]},
        {"path": "/etc/{{ app }}/d", "directory": True, "mode": "{{ m }}", "owner": "{{ who }}"},
        {"path": "/srv/{{ app }}", "link": "/opt/{{ app }}"},
        {"path": "/etc/{{ app }}.default", "line": "A=1", "match": "^{{ app }}=", "validate": "{{ app }} -t %s"},
        {"path": "/etc/{{ app }}.x", "block": "k", "marker": "bastet {{ app }}", "comment": "{{ m }}"},
    ], options=opts)
    f, d, link, line, block = built(r, {"app": "demo", "m": "0640", "who": "svc", "unit": "demo.service"})
    assert (f.path, f.mode, f.owner, f.group, f.validate) == ("/etc/demo.conf", "0640", "svc", "svc", "demo -t %s")
    assert [t.label for t in f.on_change] == ["restart demo.service", "reload demo.service"]
    assert (d.path, d.mode, d.owner) == ("/etc/demo/d", "0640", "svc")
    assert (link.path, link.target) == ("/srv/demo", "/opt/demo")
    assert (line.path, line.match, line.validate) == ("/etc/demo.default", "^demo=", "demo -t %s")
    assert (block.path, block.marker, block.comment) == ("/etc/demo.x", "bastet demo", "0640")


def test_optional_fields_that_resolve_to_nothing_are_dropped(tmp_path):
    r = role(tmp_path, [{"path": "/etc/x", "content": "x", "mode": "{{ domain }}", "owner": "{{ domain }}"}])
    [f] = built(r)
    assert f.mode is None and f.owner is None


def test_a_path_that_resolves_to_nothing_is_an_error(tmp_path):
    with pytest.raises(BastetError, match="files\\[0\\]: path resolved to nothing"):
        built(role(tmp_path, [{"path": "{{ domain }}", "content": "x"}]))


def test_edit_and_backup_resolve_the_path_and_quote_it(tmp_path):
    r = role(tmp_path, [{"path": "/etc/{{ domain }}.conf", "edit": "ini", "backup": True, "validate": "{{ domain }} -t %s"}],
             options={"domain": {"type": "string"}, "n": {"type": "int", "key": "N", "section": "options"}})
    backup, settings = built(r, {"domain": "my app", "n": 1})
    assert backup.run == "cp -p '/etc/my app.conf' '/etc/my app.conf.bastet-orig'"
    assert "'/etc/my app.conf.bastet-orig'" in backup.unless
    assert settings.path == "/etc/my app.conf" and settings.validate == "my app -t %s"


@pytest.mark.parametrize("path", ["/etc/sudoers.d/bastet", "/home/bastet/.ssh/authorized_keys", "/var/lib/bastet/.ssh/authorized_keys"])
def test_files_entries_cannot_touch_the_bastet_accounts_access(tmp_path, path):
    with pytest.raises(BastetError, match="bastet account is managed by Bastet itself"):
        role(tmp_path, [{"path": path, "content": "x"}])
    r = role(tmp_path, [{"path": "{{ domain }}", "content": "x"}])
    with pytest.raises(BastetError, match="bastet account is managed by Bastet itself"):
        built(r, {"domain": path})


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
