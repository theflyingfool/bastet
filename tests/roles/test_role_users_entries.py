from pathlib import Path

import pytest
import yaml

from bastet.core.errors import BastetError
from bastet.engine.files import File
from bastet.engine.users import AuthorizedKey, Group, User
from bastet.roles.builtin import HostInfo
from bastet.roles.contract import parse_role
from bastet.roles.declarative import build


def role(tmp_path, users, options=None):
    folder = tmp_path / "demo"
    folder.mkdir(exist_ok=True)
    data = {"bastet": "role-definition", "name": "demo", "version": "1.0.0", "api": 0, "description": "A demo role",
            "options": options or {"shell": {"type": "string"}}, "users": users}
    path = folder / "demo role.md"
    path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\nNotes.\n", encoding="utf-8")
    return parse_role(path)


def built(r, values=None):
    host = HostInfo(name="vps1", type="vps", data={"os": "Arch Linux"}, root=Path("/x"), lab={})
    [batch] = build(r, values or {}, host)
    return batch.resources


def test_user_group_key_sudoer(tmp_path):
    r = role(tmp_path, [
        {"kind": "group", "name": "git", "system": True},
        {"kind": "user", "name": "git", "system": True, "shell": "{{ shell }}", "groups": ["git"]},
        {"kind": "key", "user": "git", "key": "ssh-ed25519 AAAAexample"},
        {"kind": "sudoer", "name": "git", "user": "git", "commands": ["/usr/bin/systemctl"], "nopasswd": True},
    ])
    g, u, k, s = built(r, {"shell": "/bin/bash"})
    assert isinstance(g, Group) and g.system is True
    assert isinstance(u, User) and (u.shell, u.groups, u.system) == ("/bin/bash", ("git",), True)
    assert isinstance(k, AuthorizedKey) and (k.user, k.key) == ("git", "ssh-ed25519 AAAAexample")
    assert isinstance(s, File) and s.path == "/etc/sudoers.d/git" and "NOPASSWD:" in s.content and s.validate == "visudo -cf %s"


def test_a_password_hash_from_a_secret_option_marks_only_its_entry_secret(tmp_path):
    r = role(tmp_path, [
        {"kind": "user", "name": "root", "password": "{{ pw }}", "create_home": False},
        {"kind": "group", "name": "ops"},
    ], options={"pw": {"type": "string", "secret": True}})
    host = HostInfo(name="vps1", type="vps", data={"os": "Arch Linux"}, root=Path("/x"), lab={})
    [batch] = build(r, {"pw": "correct horse"}, host, secret_options=frozenset({"pw"}))
    root, ops = batch.resources
    assert root.password == "correct horse" and root.secret is True
    assert ops.secret is False


def test_without_secret_options_nothing_is_secret(tmp_path):
    r = role(tmp_path, [{"kind": "user", "name": "root", "password": "{{ pw }}"}], options={"pw": {"type": "string", "secret": True}})
    assert built(r, {"pw": "correct horse"})[0].secret is False


def test_when_skips_an_entry(tmp_path):
    r = role(tmp_path, [{"kind": "user", "name": "git", "when": "shell"}])
    assert built(r, {}) == [] and len(built(r, {"shell": "/bin/sh"})) == 1


@pytest.mark.parametrize("entry, message", [
    ({"name": "x"}, "users\\[0\\]: needs a kind"),
    ({"kind": "role", "name": "x"}, "kind must be one of"),
    ({"kind": "user"}, "user: needs name"),
    ({"kind": "key", "user": "git"}, "key: needs key"),
    ({"kind": "user", "name": "bastet"}, "bastet account is managed by Bastet itself"),
    ({"kind": "key", "user": "bastet", "key": "k"}, "bastet account is managed by Bastet itself"),
    ({"kind": "sudoer", "name": "bastet", "user": "x"}, "bastet account is managed by Bastet itself"),
    ({"kind": "user", "name": "x", "zzz": 1}, "zzz"),
    ({"kind": "user", "name": "x", "password": "a", "password_hash": "$6$s$h"}, "password or password_hash, not both"),
    ({"kind": "user", "name": "{{ nope }}"}, "names no option or fact: nope"),
])
def test_users_entry_errors(tmp_path, entry, message):
    with pytest.raises(BastetError, match=message):
        role(tmp_path, [entry])


def test_a_bastet_name_that_comes_from_an_option_is_refused(tmp_path):
    opts = {"who": {"type": "string"}}
    for entry in ({"kind": "user", "name": "{{ who }}", "shell": "/usr/bin/nologin"},
                  {"kind": "key", "user": "{{ who }}", "key": "ssh-ed25519 AAAAexample"},
                  {"kind": "sudoer", "name": "{{ who }}", "nopasswd": True}):
        with pytest.raises(BastetError, match="bastet account is managed by Bastet itself"):
            built(role(tmp_path, [entry], options=opts), {"who": "bastet"})
    assert built(role(tmp_path, [{"kind": "user", "name": "{{ who }}"}], options=opts), {"who": "svc"})


def test_a_required_field_that_resolves_to_nothing_is_a_clear_error(tmp_path):
    opts = {"who": {"type": "string"}}
    with pytest.raises(BastetError, match="users\\[0\\]: user: name resolved to nothing"):
        built(role(tmp_path, [{"kind": "user", "name": "{{ who }}"}], options=opts), {})
    with pytest.raises(BastetError, match="users\\[0\\]: key: key resolved to nothing"):
        built(role(tmp_path, [{"kind": "key", "user": "svc", "key": "{{ who }}"}], options=opts), {})


def test_a_bad_resolved_name_is_a_bastet_error_not_a_traceback(tmp_path):
    with pytest.raises(BastetError, match="users\\[0\\]"):
        built(role(tmp_path, [{"kind": "user", "name": "{{ who }}"}], options={"who": {"type": "string"}}), {"who": "bad name"})
