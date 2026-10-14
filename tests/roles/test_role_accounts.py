import pytest
import yaml

from bastet.core.errors import BastetError
from bastet.core.osdefaults import check_accounts
from bastet.roles.contract import load_roles, parse_role


def note(tmp_path, **extra):
    folder = tmp_path / "demo"
    folder.mkdir(exist_ok=True)
    data = {"bastet": "role-definition", "name": "demo", "version": "1.0.0", "api": 0, "description": "A demo role", **extra}
    path = folder / "demo role.md"
    path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\nNotes.\n", encoding="utf-8")
    return path


def test_check_accounts_accepts_names_and_drops_duplicates():
    assert check_accounts(None, "x") == ()
    assert check_accounts(["alpm", "_talkd", "systemd-network", "alpm"], "x") == ("alpm", "_talkd", "systemd-network")


@pytest.mark.parametrize("bad", ["alpm", [1], ["bad name"], ["", "a"], [["nested"]], {"a": 1}])
def test_check_accounts_refuses_anything_else(bad):
    with pytest.raises(BastetError, match="accounts"):
        check_accounts(bad, "x")


def test_a_markdown_role_can_declare_accounts(tmp_path):
    assert parse_role(note(tmp_path, accounts=["alpm"])).accounts == ("alpm",)
    assert parse_role(note(tmp_path)).accounts == ()


def test_a_bad_accounts_key_names_the_file_and_key(tmp_path):
    with pytest.raises(BastetError) as e:
        parse_role(note(tmp_path, accounts="alpm"))
    assert "accounts" in str(e.value) and "demo role.md" in str(e.value)


def test_shipped_roles_declare_their_accounts():
    roles = load_roles()
    assert roles["pacman"].accounts == ("alpm",)
    assert set(roles["systemd"].accounts) == {"systemd-coredump", "systemd-network", "systemd-oom",
                                               "systemd-journal-remote", "systemd-resolve", "systemd-timesync", "systemd-imds"}
    assert roles["base"].accounts == ("git",)  # the account the git package creates, which base installs by default
    assert roles["caddy"].accounts == ("caddy",)  # created by the caddy package's sysusers file
    assert roles["packages"].accounts == () and roles["apt"].accounts == ()
