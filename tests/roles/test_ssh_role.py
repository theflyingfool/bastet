from pathlib import Path

import pytest

from bastet.core.errors import BastetError
from bastet.engine.command import Command
from bastet.engine.files import File
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import check_values, load_roles, with_defaults
from bastet.roles.resolve import Applied

ROLES = load_roles()


def ap(values):
    r = ROLES["ssh"]
    return Applied(r, with_defaults(r, check_values(r, values, "ssh")))


def host(os="Debian GNU/Linux 13 (trixie)"):
    return HostInfo(name="h", type="vm", data={"os": os}, root=Path("/x"), lab={})


def out(values, os="Debian GNU/Linux 13 (trixie)"):
    return [r for b in batches_for([ap(values)], host(os)) for r in b.resources]


def conf(values, os="Debian GNU/Linux 13 (trixie)"):
    return next(r for r in out(values, os) if isinstance(r, File)).content


def test_nothing_set_writes_nothing():
    assert out({}) == []


def test_kinds_render():
    text = conf({"password_authentication": False, "port": [2222, 22], "allow_users": ["bastet", "nick"],
                 "ciphers": ["chacha20-poly1305@openssh.com", "aes256-gcm@openssh.com"], "permit_root_login": "prohibit-password"})
    assert "PasswordAuthentication no\n" in text and "Port 2222\nPort 22\n" in text
    assert "AllowUsers bastet nick\n" in text and "Ciphers chacha20-poly1305@openssh.com,aes256-gcm@openssh.com\n" in text
    assert "PermitRootLogin prohibit-password\n" in text


def test_match_blocks_end_with_match_all():
    text = conf({"match": [{"criteria": "User nick", "settings": {"x11_forwarding": True}}]})
    assert text.rstrip().endswith("Match all")
    assert "Match User nick\n    X11Forwarding yes\n" in text


def test_drop_in_validated_and_reloads_right_unit():
    f = next(r for r in out({"x11_forwarding": False}) if isinstance(r, File))
    assert f.path == "/etc/ssh/sshd_config.d/10-bastet.conf" and f.validate == "/usr/sbin/sshd -t -f %s"
    assert any("ssh.service" in t.command for t in f.on_change)
    arch = next(r for r in out({"x11_forwarding": False}, os="Arch Linux") if isinstance(r, File))
    assert any("sshd.service" in t.command for t in arch.on_change)
    assert any(isinstance(r, Command) and "Include" in r.unless and "sshd_config" in r.unless for r in out({"x11_forwarding": False}))


@pytest.mark.parametrize("values", [
    {"pubkey_authentication": False},
    {"authentication_methods": "password"},
    {"allow_users": ["nick"]},
    {"allow_groups": ["wheel"]},
    {"deny_users": ["bastet"]},
    {"match": [{"criteria": "Address 10.0.0.0/8", "settings": {"pubkey_authentication": False}}]},
    {"match": [{"criteria": "User bastet", "settings": {"force_command": "/bin/false"}}]},
])
def test_lockout_guard(values):
    with pytest.raises(BastetError, match="lock Bastet out"):
        out(values)


def test_allow_groups_ok_with_bastet_group_or_user():
    assert out({"allow_groups": ["bastet", "wheel"]})
    assert out({"allow_groups": ["wheel"], "allow_users": ["bastet", "nick"]})


def test_match_setting_names_are_checked():
    with pytest.raises(BastetError, match="nope"):
        out({"match": [{"criteria": "User nick", "settings": {"nope": "x"}}]})


def test_role_yml_matches_the_table():
    import importlib.util
    spec = importlib.util.spec_from_file_location("gen", Path(__file__).parents[2] / "scripts" / "gen_ssh_role.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    shipped = (Path(__file__).parents[2] / "src/bastet/data/roles/ssh/role.yml").read_text()
    assert gen.render() == shipped


def test_option_names_unique_and_snake_case():
    from bastet.roles.system import SSHD_KEYWORDS
    import re
    assert all(re.fullmatch(r"[a-z][a-z0-9_]*", k) for k in SSHD_KEYWORDS)
    assert len({kw for kw, _ in SSHD_KEYWORDS.values()}) == len(SSHD_KEYWORDS)
    assert set(ROLES["ssh"].options) == set(SSHD_KEYWORDS) | {"match"}
