from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import bastet.cli.run as run_mod
from bastet.core.errors import BastetError
from bastet.engine.packages import Package, Unaccounted
from bastet.engine.users import UnaccountedUsers, User
from bastet.roles import builtin
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import check_values, load_roles, parse_role, with_defaults
from bastet.roles.resolve import Applied


def host():
    return HostInfo(name="vps1", type="vps", data={"os": "Arch Linux"}, root=Path("/x"), lab={})


def secret_role(tmp_path, users=None):
    folder = tmp_path / "demo"
    folder.mkdir()
    data = {"bastet": "role-definition", "name": "demo", "version": "1.0.0", "api": 0, "description": "A demo role",
            "options": {"pw": {"type": "string", "secret": True}},
            "packages": ["example-app"],
            "users": users or [{"kind": "user", "name": "root", "password": "{{ pw }}", "create_home": False}]}
    path = folder / "demo role.md"
    path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\nNotes.\n", encoding="utf-8")
    return parse_role(path)


def test_applied_secret_options_reach_the_entries_through_batches_for(tmp_path):
    role = secret_role(tmp_path)
    applied = Applied(role=role, values={"pw": "correct horse"}, secret=True, secret_options=frozenset({"pw"}))
    resources = [r for b in batches_for([applied], host()) for r in b.resources]
    [package] = [r for r in resources if isinstance(r, Package) and r.name == "example-app"]
    [user] = [r for r in resources if isinstance(r, User)]
    assert user.secret is True and package.secret is False


def test_plan_for_records_which_options_became_secret(tmp_path, monkeypatch):
    role = secret_role(tmp_path)
    monkeypatch.setattr(run_mod, "resolve", lambda *a, **k: [Applied(role=role, values={"pw": "secret:demo/pw"})])
    monkeypatch.setattr(run_mod, "resolve_refs", lambda values, **k: ({"pw": "correct horse"}, ["pw"]))
    monkeypatch.setattr(run_mod, "host_info", lambda ctx, doc, updates=False: host())
    ctx = SimpleNamespace(inventory=None, types={}, secrets=None)
    applied, batches = run_mod.plan_for(ctx, SimpleNamespace(name="vps1"), {})
    assert applied[0].secret_options == frozenset({"pw"}) and applied[0].secret is True
    [user] = [r for b in batches for r in b.resources if isinstance(r, User)]
    [package] = [r for b in batches for r in b.resources if isinstance(r, Package) and r.name == "example-app"]
    assert user.secret is True and package.secret is False


def test_a_markdown_role_that_raises_a_plain_error_comes_back_as_a_bastet_error(tmp_path, monkeypatch):
    role = secret_role(tmp_path)

    def boom(*args, **kwargs):
        raise ValueError("not a user name")
    monkeypatch.setattr(builtin.declarative, "build", boom)
    with pytest.raises(BastetError, match="demo: not a user name"):
        batches_for([Applied(role=role, values={})], host())


def test_the_blanket_secret_rule_of_an_old_format_role_leaves_the_unaccounted_lists_readable():
    role = load_roles()["users"]
    values = with_defaults(role, check_values(role, {"users": {"alice": {"password_hash": "$6$salt$hash"}}}, "users"))
    resources = [r for b in batches_for([Applied(role=role, values=values, secret=True)], host()) for r in b.resources]
    [report] = [r for r in resources if isinstance(r, UnaccountedUsers)]
    [alice] = [r for r in resources if isinstance(r, User)]
    assert report.secret is False and alice.secret is True


def test_the_unaccounted_package_list_stays_readable_too():
    role = load_roles()["packages"]
    values = with_defaults(role, check_values(role, {"install": [{"name": "example-app"}]}, "packages"))
    resources = [r for b in batches_for([Applied(role=role, values=values, secret=True)], host()) for r in b.resources]
    [report] = [r for r in resources if isinstance(r, Unaccounted)]
    [package] = [r for r in resources if isinstance(r, Package)]
    assert report.secret is False and package.secret is True
