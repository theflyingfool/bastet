from pathlib import Path

import pytest

from bastet.core.errors import BastetError
from bastet.core.shell import ProbeResult
from bastet.engine.files import Block, Directory, File, Line, Symlink
from bastet.engine.model import Unsupported
from bastet.engine.packages import Package
from bastet.engine.systemd import Hostname, Locale, TimeSettings, Unit
from bastet.engine.users import AuthorizedKey, Group, User
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import check_values, load_roles, with_defaults
from bastet.roles.resolve import Applied

ROLES = load_roles()
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleExampleExampleExampleExampleExample admin@laptop"


def ap(role, values):
    r = ROLES[role]
    return Applied(r, with_defaults(r, check_values(r, values, role)))


def info(type_="vm", os="Debian GNU/Linux 13 (trixie)", root=Path("/nonexistent"), **data):
    return HostInfo(name="media01", type=type_, data={"os": os, "hostname": "media01", **data}, root=root, lab={})


def resources(*applied, host=None):
    return [r for b in batches_for(list(applied), host or info()) for r in b.resources]


def ok(text):
    return ProbeResult(0, text)


def test_systemd_timesyncd_on_debian():
    out = resources(ap("systemd", {"timezone": "UTC", "ntp": True, "ntp_service": "timesyncd", "ntp_servers": ["10.0.10.1"],
                                   "fallback_ntp_servers": ["pool.ntp.org"]}))
    kinds = [(type(r).__name__, getattr(r, "name", getattr(r, "path", None))) for r in out]
    assert kinds == [("Package", "systemd-timesyncd"), ("File", "/etc/systemd/timesyncd.conf.d/bastet.conf"),
                     ("Unit", "chronyd.service"), ("Unit", "systemd-timesyncd.service"), ("TimeSettings", None),
                     ("Hostname", "media01")]
    assert out[1].content == "[Time]\nNTP=10.0.10.1\nFallbackNTP=pool.ntp.org\n"
    assert (out[2].enabled, out[2].state, out[3].enabled, out[3].state) == (False, "down", True, "up")
    assert (out[4].timezone, out[4].ntp, out[4].rtc_local) == ("UTC", None, False)


def test_systemd_chrony_debian_and_elsewhere():
    deb = resources(ap("systemd", {"ntp": True, "ntp_service": "chrony", "ntp_servers": ["10.0.10.1"]}))
    src = next(r for r in deb if isinstance(r, File))
    assert src.path == "/etc/chrony/sources.d/bastet.sources" and src.content == "server 10.0.10.1 iburst\n"
    assert src.on_change[0].command == "chronyc reload sources"
    arch = resources(ap("systemd", {"ntp": True, "ntp_service": "chrony", "ntp_servers": ["10.0.10.1"]}), host=info(os="Arch Linux"))
    assert not any(isinstance(r, Package) and r.name == "systemd-timesyncd" for r in arch)
    block = next(r for r in arch if isinstance(r, Block))
    assert block.path == "/etc/chrony.conf" and block.block == "server 10.0.10.1 iburst"


def test_systemd_lxc_only_timezone():
    out = resources(ap("systemd", {"timezone": "UTC", "ntp": True, "ntp_service": "timesyncd", "locale": "en_US.UTF-8"}),
                    host=info(type_="lxc"))
    assert [type(r).__name__ for r in out] == ["TimeSettings", "Locale"]
    assert (out[0].timezone, out[0].ntp, out[0].rtc_local) == ("UTC", None, None)


def test_systemd_keep_uses_timedatectl_and_rejects_ignored_knobs():
    out = resources(ap("systemd", {"ntp": True}))
    assert [type(r).__name__ for r in out] == ["TimeSettings", "Hostname"] and out[0].ntp is True
    with pytest.raises(BastetError):
        resources(ap("systemd", {"ntp_servers": ["10.0.10.1"]}))
    with pytest.raises(BastetError):
        resources(ap("systemd", {"ntp": True, "ntp_service": "chrony", "fallback_ntp_servers": ["a"]}))


def test_systemd_services_dropins_hostname_override():
    out = resources(ap("systemd", {"manage_hostname": True, "services": {"ssh.service": {"enabled": True, "state": "up"}},
                                   "dropins": [{"unit": "gitea.service", "name": "limits", "content": "[Service]\nNice=5\n"}]}),
                    host=info(hostname="media-01"))
    assert next(r for r in out if isinstance(r, Hostname)).name == "media-01"
    assert any(isinstance(r, Unit) and r.name == "ssh.service" and r.state == "up" for r in out)
    assert any(isinstance(r, File) and r.path == "/etc/systemd/system/gitea.service.d/limits.conf" for r in out)
    with pytest.raises(BastetError):
        resources(ap("systemd", {"dropins": [{"unit": "x.service", "content": "a"}]}))


def test_packages_role():
    out = resources(ap("packages", {
        "install_recommends": False,
        "install": ["tree", {"name": "jq", "version": "1.7", "extra_args": ["--foo"]}],
        "remove": [{"name": "nano", "purge": True}],
    }), host=info(os="Fedora Linux 42"))
    assert [type(r).__name__ for r in out] == ["Package", "Package", "Package", "Updates", "Reboot", "Unaccounted"]
    nano, tree, jq = out[:3]
    assert (nano.name, nano.state, nano.purge) == ("nano", "absent", True)
    assert tree.install_recommends is False and jq.version == "1.7" and jq.extra_args == ("--foo",)
    with pytest.raises(BastetError):
        resources(ap("packages", {"install": ["nano"], "remove": ["nano"]}))


def test_users_role():
    out = resources(ap("users", {
        "groups": {"media": {"gid": 2001}},
        "users": {"alice": {"groups": ["media"], "shell": "/bin/bash", "keys": [KEY, {"key": KEY.replace("Example", "Other0"), "state": "absent"}],
                           "sudo": {"nopasswd": True}}},
        "sudoers": {"ops": {"group": "wheel", "commands": ["/usr/bin/systemctl"]}},
    }))
    assert [type(r).__name__ for r in out] == ["Group", "User", "AuthorizedKey", "AuthorizedKey", "File", "File"]
    assert out[1].groups == ("media",) and out[3].state == "absent"
    assert out[4].path == "/etc/sudoers.d/alice" and "alice ALL=(ALL) NOPASSWD: ALL" in out[4].content
    assert out[5].path == "/etc/sudoers.d/ops" and "%wheel ALL=(ALL) /usr/bin/systemctl" in out[5].content


def test_files_role_and_templates(tmp_path):
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "motd.j2").write_text("{{ name }} · {{ host.os }}\n")
    out = resources(ap("files", {
        "directories": {"/srv/app": {"mode": "0750"}},
        "files": {"/etc/motd": {"template": "templates/motd.j2", "mode": "0644"}, "/etc/x": {"content": "x\n"}},
        "links": {"/srv/current": "/srv/app"},
        "blocks": [{"path": "/etc/ssh/sshd_config", "marker": "bastet", "block": "X11Forwarding no"}],
        "lines": [{"path": "/etc/hosts", "line": "10.0.10.5 nas"}],
    }), host=info(root=tmp_path))
    assert [type(r).__name__ for r in out] == ["Directory", "File", "File", "Symlink", "Block", "Line"]
    assert out[1].content == "media01 · Debian GNU/Linux 13 (trixie)\n"
    for bad in ({"files": {"etc/x": {"content": "a"}}}, {"files": {"/etc/x": {}}},
                {"files": {"/etc/x": {"content": "a", "template": "t"}}}):
        with pytest.raises(BastetError):
            resources(ap("files", bad), host=info(root=tmp_path))


def test_order_across_roles():
    out = batches_for([ap("systemd", {"timezone": "UTC"}), ap("files", {"files": {"/etc/x": {"content": "a"}}}),
                       ap("packages", {"install": ["tree"]}), ap("users", {"groups": {"media": {}}})], info())
    assert [b.name for b in out] == ["packages", "users", "files", "systemd"]


def test_full_upgrade_without_packages_is_an_error():
    with pytest.raises(BastetError) as e:
        resources(ap("packages", {"full_upgrade": True}))
    assert "full_upgrade only applies while installing" in str(e.value)
    assert [type(r).__name__ for r in resources(ap("packages", {}))] == ["Updates", "Reboot", "Unaccounted"]


def test_packages_role_adds_updates_reboot_unaccounted():
    from bastet.engine.packages import Reboot, Unaccounted, Updates
    out = resources(ap("packages", {"install": ["tree"], "updates": "auto", "updates_exclude": ["linux"],
                                    "allowed": ["steam"]}), host=info(bastet_tools=["dmidecode"]))
    upd, reboot, unacc = out[-3:]
    assert isinstance(upd, Updates) and upd.policy == "auto" and upd.exclude == ("linux",)
    assert isinstance(reboot, Reboot)
    assert isinstance(unacc, Unaccounted) and unacc.tracked == ("tree", "dmidecode") and unacc.allowed == ("steam",)
    lxc = resources(ap("packages", {"report_unaccounted": False}), host=info(type_="lxc"))
    assert [type(r).__name__ for r in lxc] == ["Updates"]


def test_host_info_os_id_and_physical():
    h = HostInfo(name="h", type="server", data={"os": "Arch Linux"}, root=Path("/x"), physical=True)
    assert h.os_id == "arch" and h.physical


def test_packages_reboot_policy_reaches_reboot():
    from bastet.engine.packages import Reboot
    out = resources(ap("packages", {"reboot": "auto", "reboot_timeout": 900}))
    reboot = next(r for r in out if isinstance(r, Reboot))
    assert (reboot.policy, reboot.timeout) == ("auto", 900)
    default = next(r for r in resources(ap("packages", {})) if isinstance(r, Reboot))
    assert default.policy == "ask"


def test_aur_bootstrap_only_when_aur_listed():
    from bastet.engine.command import Command
    plain = resources(ap("packages", {"install": ["tree"]}), host=info(os="Arch Linux"))
    assert not any(isinstance(r, Command) for r in plain)
    out = resources(ap("packages", {"install": [{"name": "paru-bin", "aur": True}, "tree"]}), host=info(os="Arch Linux"))
    names = [getattr(r, "name", getattr(r, "path", "")) for r in out]
    assert names.index("bastet-aur") < names.index("yay") < names.index("paru-bin")
    yay = next(r for r in out if isinstance(r, Command))
    assert yay.unless == "command -v yay" and "yay-bin" in yay.run and "makepkg -si --noconfirm" in yay.run
    sudo = next(r for r in out if getattr(r, "path", "") == "/etc/sudoers.d/bastet-aur")
    assert "NOPASSWD: /usr/bin/pacman" in sudo.content


def test_aur_names_are_checked():
    with pytest.raises(BastetError, match="packages.aur_user: "):
        resources(ap("packages", {"aur_user": "x; rm -rf /", "install": [{"name": "a", "aur": True}]}),
                  host=info(os="Arch Linux"))


# NTP servers without ntp: true

def test_ntp_servers_need_ntp_on():
    with pytest.raises(BastetError) as e:
        resources(ap("systemd", {"ntp_service": "timesyncd", "ntp_servers": ["10.0.10.1"]}), host=info(os="Arch Linux"))
    assert "ntp: true" in str(e.value)


# what Bastet installs is never unaccounted

def test_packages_installed_by_other_roles_are_tracked():
    from bastet.engine.packages import Unaccounted
    out = resources(ap("systemd", {"ntp": True, "ntp_service": "chrony"}), ap("packages", {"install": ["tree"]}),
                    host=info(os="Arch Linux"))
    unacc = next(r for r in out if isinstance(r, Unaccounted))
    assert set(unacc.tracked) >= {"tree", "chrony"}


# security policy and zypper excludes

def test_security_policy_reports_the_rest():
    from bastet.engine.packages import Updates
    out = resources(ap("packages", {"updates": "security"}), host=info(os="Arch Linux"))
    ups = [r for r in out if isinstance(r, Updates)]
    assert [(u.policy, u.rest) for u in ups] == [("security", False), ("manual", True)]
    rest = ups[1]
    cur = rest.current({"manager": ok("apt-get"), "pending": ok("tree/trixie 2 amd64 [upgradable from: 1]\nssl/trixie-security 2 amd64 [upgradable from: 1]\n"),
                        "security": ok("")})
    assert rest.report_only() and [c.before for c in rest.compare(cur)] == ["1 pending"] and rest.identity != ups[0].identity
    forced = resources(ap("packages", {"updates": "security"}), host=HostInfo("m", "vm", {"os": "Arch"}, Path("/x"), {}, apply_updates=True))
    assert [u.policy for u in forced if isinstance(u, Updates)] == ["auto"]


def test_zypper_security_with_exclude_unsupported():
    from bastet.engine.packages import Updates
    u = Updates(policy="security", exclude=("kernel-default",))
    with pytest.raises(Unsupported):
        u.current({"manager": ok("zypper"), "pending": ok(""), "security": ok("")})


# held and ignored packages aren't pending

def test_held_and_ignored_packages_not_pending():
    from bastet.engine.packages import Updates
    u = Updates(policy="auto")
    cur = u.current({"manager": ok("apt-get"), "security": ok(""),
                     "pending": ok("Listing...\npve-kernel/trixie 2 amd64 [upgradable from: 1]\ntree/trixie 2 amd64 [upgradable from: 1]\n@@HELD@@\npve-kernel\n")})
    assert cur["pending"] == ("tree",)
    p = u.current({"manager": ok("pacman"), "security": ok(""), "pending": ok("linux 1 -> 2 [ignored]\ntree 1 -> 2\n@@RC 0\n")})
    assert p["pending"] == ("tree",)


# a failed refresh is an error, not "up to date"

@pytest.mark.parametrize("manager,pending", [("pacman", "@@RC 1\n"), ("dnf", "@@RC 1\n"), ("apt-get", "@@RC refresh-failed\n")])
def test_failed_update_check_is_an_error(manager, pending):
    from bastet.engine.model import ReadError
    from bastet.engine.packages import Updates
    with pytest.raises(ReadError):
        Updates().current({"manager": ok(manager), "pending": ok(pending), "security": ok("")})
    assert Updates().current({"manager": ok("pacman"), "pending": ok("@@RC 2\n"), "security": ok("")})["pending"] == ()


# roles can't lock Bastet out

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
        resources(ap("users", values), host=info(os="Arch Linux"))
    assert "lock Bastet out" in str(e.value)


# knobs: on-change triggers, secret, commands, remove knobs, updates extra_args

def test_files_restart_reload_secret_and_commands():
    from bastet.engine.command import Command
    out = resources(ap("files", {
        "files": {"/etc/caddy/Caddyfile": {"content": "x", "reload": ["caddy.service"]}},
        "lines": [{"path": "/etc/ssh/sshd_config", "line": "PermitRootLogin no", "restart": ["sshd.service"], "secret": True}],
        "blocks": [{"path": "/etc/x", "marker": "m", "block": "b", "reload": ["x.service"]}],
        "commands": [{"name": "init db", "run": "gitea migrate", "unless": "test -e /var/lib/gitea/done"}],
    }), host=info(os="Arch Linux"))
    f = next(r for r in out if isinstance(r, File))
    line = next(r for r in out if isinstance(r, Line))
    assert [t.label for t in f.on_change] == ["reload caddy.service"]
    assert [t.label for t in line.on_change] == ["restart sshd.service"] and line.secret is True
    assert [t.label for t in next(r for r in out if isinstance(r, Block)).on_change] == ["reload x.service"]
    assert any(isinstance(r, Command) and r.name == "init db" for r in out)


def test_remove_knobs_and_updates_extra_args():
    from bastet.engine.packages import Updates
    out = resources(ap("packages", {"remove": [{"name": "nano", "manager": "pacman"}], "extra_args": ["--needed"]}),
                    host=info(os="Arch Linux"))
    nano = next(r for r in out if isinstance(r, Package))
    assert nano.manager == "pacman"
    upd = next(r for r in out if isinstance(r, Updates))
    assert upd.extra_args == ("--needed",)
