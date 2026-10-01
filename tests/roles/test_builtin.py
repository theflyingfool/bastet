from pathlib import Path

import pytest

from bastet.core.errors import BastetError
from bastet.engine.files import Block, Directory, File, Line, Symlink
from bastet.engine.packages import Package, Repository
from bastet.engine.systemd import Hostname, Locale, TimeSettings, Unit
from bastet.engine.users import AuthorizedKey, Group, User
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import check_values, load_roles, with_defaults
from bastet.roles.resolve import Applied

ROLES = load_roles()
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleExampleExampleExampleExampleExample nick@laptop"


def ap(role, values):
    r = ROLES[role]
    return Applied(r, with_defaults(r, check_values(r, values, role)))


def info(type_="vm", os="Debian GNU/Linux 13 (trixie)", root=Path("/nonexistent"), **data):
    return HostInfo(name="media01", type=type_, data={"os": os, "hostname": "media01", **data}, root=root, lab={})


def resources(*applied, host=None):
    return [r for b in batches_for(list(applied), host or info()) for r in b.resources]


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
        "repositories": [{"name": "b", "uris": ["http://deb.debian.org/debian"], "suites": ["trixie-backports"],
                          "options": {"X-Repolib-Name": "Backports"}}],
    }))
    assert [type(r).__name__ for r in out] == ["Repository", "Package", "Package", "Package"]
    repo, nano, tree, jq = out
    assert repo.options == (("X-Repolib-Name", "Backports"),) and repo.suites == ("trixie-backports",)
    assert (nano.name, nano.state, nano.purge) == ("nano", "absent", True)
    assert tree.install_recommends is False and jq.version == "1.7" and jq.extra_args == ("--foo",)
    with pytest.raises(BastetError):
        resources(ap("packages", {"install": ["nano"], "remove": ["nano"]}))


def test_users_role():
    out = resources(ap("users", {
        "groups": {"media": {"gid": 2001}},
        "users": {"nick": {"groups": ["media"], "shell": "/bin/bash", "keys": [KEY, {"key": KEY.replace("Example", "Other0"), "state": "absent"}],
                           "sudo": {"nopasswd": True}}},
        "sudoers": {"ops": {"group": "wheel", "commands": ["/usr/bin/systemctl"]}},
    }))
    assert [type(r).__name__ for r in out] == ["Group", "User", "AuthorizedKey", "AuthorizedKey", "File", "File"]
    assert out[1].groups == ("media",) and out[3].state == "absent"
    assert out[4].path == "/etc/sudoers.d/nick" and "nick ALL=(ALL) NOPASSWD: ALL" in out[4].content
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
