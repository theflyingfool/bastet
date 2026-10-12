import pytest
import yaml

import bastet.cli.add as add_mod
import bastet.cli.run as run_mod
import bastet.cli.secret as secret_mod
import bastet.roles.contract as contract_mod
from bastet.cli.app import app
from bastet.cli.common import load_context
from bastet.core.errors import BastetError
from bastet.roles.contract import load_roles, parse_role
from bastet.roles.resolve import resolve

MINIMAL_BODY = "No values set; this role uses its defaults."
STARTER_BODY = "These entries are listed so you can change them; delete any you do not need."


def _note(inventory, host, role):
    return inventory / "_roles" / "hosts" / host / f"{role}.md"


def _frontmatter(path):
    return yaml.safe_load(path.read_text().split("---\n")[1])


def _users_values(host):
    ctx = load_context()
    applied = {a.role.name: a for a in resolve(ctx.inventory, ctx.inventory.get(host), ctx.types, load_roles())}
    return applied["users"].values["users"]


@pytest.fixture
def starter_roles(tmp_path, monkeypatch):
    """Test-only roles: needsecret (derived references), explicit (an explicit starter wins)."""
    root = tmp_path / "roles"
    for name, text in {
        "needsecret": (
            "description: derived secret references\n"
            "options:\n"
            "  token: {type: string, secret: true, required: true}\n"
            "  optional_token: {type: string, secret: true}\n"
            "  name: {type: string, required: true}\n"
        ),
        "explicit": (
            "description: the starter wins\n"
            "options:\n"
            "  token: {type: string, secret: true, required: true}\n"
            "starter: {token: 'secret:other_token'}\n"
        ),
    }.items():
        (root / name).mkdir(parents=True)
        (root / name / "role.yml").write_text(text)
    merged = {**load_roles(), **load_roles(root)}
    monkeypatch.setattr(secret_mod, "load_roles", lambda: merged)
    monkeypatch.setattr(run_mod, "load_roles", lambda: merged)
    monkeypatch.setattr(add_mod, "load_roles", lambda: merged)
    monkeypatch.setattr(contract_mod, "load_roles",
                        lambda directory=None: merged if directory is None else load_roles(directory))
    return merged


def test_users_note_carries_root_password_and_bastet(runner, inventory):
    result = runner.invoke(app, ["add", "role", "users", "pve1", "-y"])
    assert result.exit_code == 0, result.output
    path = _note(inventory, "pve1", "users")
    assert _frontmatter(path)["users"] == {"root": {"password": "secret:root_password"}, "bastet": {"system": True}}
    assert STARTER_BODY in path.read_text() and MINIMAL_BODY not in path.read_text()
    assert "bastet secret set pve1 users root_password" in result.output


def test_users_note_offers_the_secret_and_prints_command_when_declined(runner, inventory):
    result = runner.invoke(app, ["add", "role", "users", "pve1"], input="y\nn\n")
    assert result.exit_code == 0, result.output
    assert "Set them now?" in result.output
    assert "bastet secret set pve1 users root_password" in result.output


def test_users_note_resolves_with_merged_defaults(runner, inventory):
    assert runner.invoke(app, ["add", "role", "users", "pve1", "-y"]).exit_code == 0
    users = _users_values("pve1")
    assert users["root"] == {"password": "secret:root_password"}
    assert users["bastet"] == {"system": True}


def test_removing_the_password_line_keeps_default_root_and_bastet(runner, inventory):
    assert runner.invoke(app, ["add", "role", "users", "pve1", "-y"]).exit_code == 0
    path = _note(inventory, "pve1", "users")
    # the password line and the `root:` line above it (a bare `root:` with nothing under it is not a map)
    kept = [ln for ln in path.read_text().splitlines(keepends=True)
            if "root_password" not in ln and ln.strip() != "root:"]
    path.write_text("".join(kept))
    users = _users_values("pve1")
    assert users["root"] == {} and users["bastet"] == {"system": True}


def test_role_without_starter_is_written_as_before(runner, inventory):
    assert runner.invoke(app, ["add", "role", "pacman", "pve1", "-y"]).exit_code == 0
    assert _note(inventory, "pve1", "pacman").read_text() == (
        '---\nbastet: role\nrole: pacman\napplies_to: "[[pve1]]"\n---\n'
        "Docs: [[Using roles]] · Options: ![[pacman role#Options]]\n\n" + MINIMAL_BODY + "\n")


def test_bad_starter_option_is_refused_with_the_file(tmp_path):
    folder = tmp_path / "roles" / "badstart"
    folder.mkdir(parents=True)
    (folder / "role.yml").write_text("description: x\noptions:\n  a: {type: string}\nstarter: {nope: 1}\n")
    with pytest.raises(BastetError) as exc:
        load_roles(tmp_path / "roles")
    assert exc.value.file is not None and exc.value.file.name == "role.yml" and exc.value.key == "nope"


def test_bad_starter_type_is_refused(tmp_path):
    folder = tmp_path / "roles" / "badtype"
    folder.mkdir(parents=True)
    (folder / "role.yml").write_text("description: x\noptions:\n  a: {type: bool}\nstarter: {a: [1]}\n")
    with pytest.raises(BastetError) as exc:
        load_roles(tmp_path / "roles")
    assert exc.value.file is not None and exc.value.key == "a"


def test_markdown_role_reads_a_starter(tmp_path):
    folder = tmp_path / "mdrole"
    folder.mkdir()
    path = folder / "mdrole role.md"
    path.write_text(
        "---\nbastet: role-definition\nname: mdrole\nversion: 1.0.0\napi: 0\ndescription: x\n"
        "options:\n  a: {type: string}\nstarter: {a: hello}\n---\n")
    assert parse_role(path).starter == {"a": "hello"}


def test_required_secret_option_is_written_and_offered(runner, secret_keys, inventory, starter_roles):
    result = runner.invoke(app, ["add", "role", "needsecret", "pve1"], input="y\nn\n")
    assert result.exit_code == 0, result.output
    data = _frontmatter(_note(inventory, "pve1", "needsecret"))
    assert data["token"] == "secret:token"
    assert "optional_token" not in data and "name" not in data
    assert "Set them now?" in result.output
    assert "bastet secret set pve1 needsecret token" in result.output


def test_explicit_starter_wins_over_derived_reference(runner, inventory, starter_roles):
    assert runner.invoke(app, ["add", "role", "explicit", "pve1", "-y"]).exit_code == 0
    assert _frontmatter(_note(inventory, "pve1", "explicit"))["token"] == "secret:other_token"
