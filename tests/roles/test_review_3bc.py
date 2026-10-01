"""Fixes from the stage 3b/3c review: crashes, silently ignored settings, wrong reports, lockout, missing knobs."""

from pathlib import Path

import pytest

from bastet.core.collect import ProbeResult
from bastet.core.errors import BastetError
from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from bastet.engine.command import Command
from bastet.engine.files import Block, File, Line
from bastet.engine.model import ReadError, Unsupported
from bastet.engine.packages import Package, Unaccounted, Updates
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import check_values, load_roles, with_defaults
from bastet.roles.resolve import Applied, resolve

ROLES = load_roles()
TYPES = load_host_types()


def ap(role, values):
    r = ROLES[role]
    return Applied(r, with_defaults(r, check_values(r, values, role)))


def info(**data):
    return HostInfo(name="media01", type="vm", data={"os": "Arch Linux", "hostname": "media01", **data},
                    root=Path("/nonexistent"), lab={})


def resources(*applied, host=None):
    return [r for b in batches_for(list(applied), host or info()) for r in b.resources]


def ok(text):
    return ProbeResult(0, text)


# 1: values that pass the menu can't crash the run

@pytest.mark.parametrize("role,values", [
    ("packages", {"install": [{"version": "1.7"}]}),
    ("packages", {"remove": [{"purge": True}]}),
    ("files", {"lines": [{"line": "x"}]}),
    ("systemd", {"dropins": [{"unit": "a.service"}]}),
])
def test_missing_required_fields_are_named(role, values):
    with pytest.raises(BastetError) as e:
        check_values(ROLES[role], values, role)
    assert "needs" in str(e.value)


def test_non_numeric_group_priority(tmp_path):
    files = {
        "Homelab.md": "---\nbastet: lab\n---\n",
        "groups/a.md": "---\nbastet: group\npriority: high\n---\n",
        "hosts/x.md": '---\nbastet: host\ntype: vm\nip: 10.0.10.30\ngroups:\n  - "[[a]]"\n---\n',
        "_roles/groups/a/systemd.md": '---\nbastet: role\nrole: systemd\napplies_to: "[[a]]"\ntimezone: UTC\n---\n',
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    inv = load_inventory(tmp_path, TYPES)
    with pytest.raises(BastetError) as e:
        resolve(inv, inv.get("x"), TYPES, ROLES)
    assert "priority" in str(e.value)


# 3: NTP servers without ntp: true

def test_ntp_servers_need_ntp_on():
    with pytest.raises(BastetError) as e:
        resources(ap("systemd", {"ntp_service": "timesyncd", "ntp_servers": ["10.0.10.1"]}))
    assert "ntp: true" in str(e.value)


# 4: what Bastet installs is never unaccounted

def test_packages_installed_by_other_roles_are_tracked():
    out = resources(ap("systemd", {"ntp": True, "ntp_service": "chrony"}), ap("packages", {"install": ["tree"]}))
    unacc = next(r for r in out if isinstance(r, Unaccounted))
    assert set(unacc.tracked) >= {"tree", "chrony"}


# 5 + 6: security policy and zypper excludes

def test_security_policy_reports_the_rest():
    out = resources(ap("packages", {"updates": "security"}))
    ups = [r for r in out if isinstance(r, Updates)]
    assert [(u.policy, u.rest) for u in ups] == [("security", False), ("manual", True)]
    rest = ups[1]
    cur = rest.current({"manager": ok("apt-get"), "pending": ok("tree/trixie 2 amd64 [upgradable from: 1]\nssl/trixie-security 2 amd64 [upgradable from: 1]\n"),
                        "security": ok("")})
    assert rest.report_only() and [c.before for c in rest.compare(cur)] == ["1 pending"] and rest.identity != ups[0].identity
    forced = resources(ap("packages", {"updates": "security"}), host=HostInfo("m", "vm", {"os": "Arch"}, Path("/x"), {}, apply_updates=True))
    assert [u.policy for u in forced if isinstance(u, Updates)] == ["auto"]


def test_zypper_security_with_exclude_unsupported():
    u = Updates(policy="security", exclude=("kernel-default",))
    with pytest.raises(Unsupported):
        u.current({"manager": ok("zypper"), "pending": ok(""), "security": ok("")})


# 7: held and ignored packages aren't pending

def test_held_and_ignored_packages_not_pending():
    u = Updates(policy="auto")
    cur = u.current({"manager": ok("apt-get"), "security": ok(""),
                     "pending": ok("Listing...\npve-kernel/trixie 2 amd64 [upgradable from: 1]\ntree/trixie 2 amd64 [upgradable from: 1]\n@@HELD@@\npve-kernel\n")})
    assert cur["pending"] == ("tree",)
    p = u.current({"manager": ok("pacman"), "security": ok(""), "pending": ok("linux 1 -> 2 [ignored]\ntree 1 -> 2\n@@RC 0\n")})
    assert p["pending"] == ("tree",)


# 8: a failed refresh is an error, not "up to date"

@pytest.mark.parametrize("manager,pending", [("pacman", "@@RC 1\n"), ("dnf", "@@RC 1\n"), ("apt-get", "@@RC refresh-failed\n")])
def test_failed_update_check_is_an_error(manager, pending):
    with pytest.raises(ReadError):
        Updates().current({"manager": ok(manager), "pending": ok(pending), "security": ok("")})
    assert Updates().current({"manager": ok("pacman"), "pending": ok("@@RC 2\n"), "security": ok("")})["pending"] == ()


# 9: roles can't lock Bastet out

@pytest.mark.parametrize("values", [
    {"users": {"bastet": {"expires": "2020-01-01"}}},
    {"users": {"bastet": {"locked": True}}},
    {"users": {"bastet": {"shell": "/usr/sbin/nologin"}}},
    {"users": {"bastet": {"keys": [{"key": "ssh-ed25519 AAAAx bastet", "state": "absent"}]}}},
    {"users": {"bastet": {"sudo": {"nopasswd": True}}}},
    {"sudoers": {"bastet": {"rules": ["bastet ALL=(ALL) /usr/bin/true"]}}},
])
def test_roles_cannot_lock_bastet_out(values):
    with pytest.raises(BastetError) as e:
        resources(ap("users", values))
    assert "lock Bastet out" in str(e.value)


# 10: Proxmox nodes don't manage their hostname by default

def test_proxmox_baseline_leaves_hostname_alone():
    assert TYPES["proxmox-node"].roles["systemd"]["manage_hostname"] is False


# knobs: on-change triggers, secret, commands, remove knobs, updates extra_args

def test_files_restart_reload_secret_and_commands():
    out = resources(ap("files", {
        "files": {"/etc/caddy/Caddyfile": {"content": "x", "reload": ["caddy.service"]}},
        "lines": [{"path": "/etc/ssh/sshd_config", "line": "PermitRootLogin no", "restart": ["sshd.service"], "secret": True}],
        "blocks": [{"path": "/etc/x", "marker": "m", "block": "b", "reload": ["x.service"]}],
        "commands": [{"name": "init db", "run": "gitea migrate", "unless": "test -e /var/lib/gitea/done"}],
    }))
    f = next(r for r in out if isinstance(r, File))
    line = next(r for r in out if isinstance(r, Line))
    assert [t.label for t in f.on_change] == ["reload caddy.service"]
    assert [t.label for t in line.on_change] == ["restart sshd.service"] and line.secret is True
    assert [t.label for t in next(r for r in out if isinstance(r, Block)).on_change] == ["reload x.service"]
    assert any(isinstance(r, Command) and r.name == "init db" for r in out)


def test_remove_knobs_and_updates_extra_args():
    out = resources(ap("packages", {"remove": [{"name": "nano", "manager": "pacman"}], "extra_args": ["--needed"]}))
    nano = next(r for r in out if isinstance(r, Package))
    assert nano.manager == "pacman"
    upd = next(r for r in out if isinstance(r, Updates))
    assert upd.extra_args == ("--needed",)
