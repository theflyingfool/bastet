from bastet.engine.command import Command
from bastet.engine.files import Block, Directory, File, Line, Symlink
from bastet.engine.report import render_host
from bastet.engine.run import Batch, run_host
from bastet.engine.systemd import Hostname, Locale, TimeSettings, Unit, daemon_reload, drop_in

TRICKY = "say \"hi\" to $HOME \\ 'q' · ünïcode\nno trailing newline"
DEMO_UNIT = "[Unit]\nDescription=Bastet contract demo\n[Service]\nExecStart=/bin/sleep infinity\n[Install]\nWantedBy=multi-user.target\n"


def converge(runner, batches):
    check = run_host(runner, "ct", batches, apply=False)
    assert all(i.status == "would-change" for i in check.items), render_host(check, full=True)
    first = run_host(runner, "ct", batches, apply=True)
    assert first.ok, render_host(first, full=True)
    second = run_host(runner, "ct", batches, apply=True)
    assert all(i.status == "compliant" for i in second.items) and not second.triggers, render_host(second, full=True)
    return first


def test_files_contract(host):
    converge(host, [Batch("files", [
        Directory(path="/srv/bastet-ct", mode="0750"),
        File(path="/etc/bastet-ct/motd", content=TRICKY, mode="0640", owner="root", group="root"),
        Symlink(path="/etc/bastet-ct/link", target="/etc/bastet-ct/motd"),
        Block(path="/etc/bastet-ct/conf", block="a = 1\nb = 2", marker="bastet ct"),
        Line(path="/etc/bastet-ct/conf", line="c = 3", match=r"^c ="),
    ])])
    assert host.run("sudo -n cat /etc/bastet-ct/motd").stdout == TRICKY
    assert host.run("sudo -n stat -c %a /etc/bastet-ct/motd").stdout.strip() == "640"


def test_systemd_contract(host):
    converge(host, [
        Batch("unit file", [File(path="/etc/systemd/system/bastet-demo.service", content=DEMO_UNIT, mode="0644",
                                 on_change=(daemon_reload(),))]),
        Batch("service", [
            Unit(name="bastet-demo.service", enabled=True, state="up"),
            drop_in("bastet-demo.service", "bastet", "[Service]\nNice=5\n"),
        ]),
        Batch("system", [TimeSettings(timezone="America/Chicago"), Hostname(name="media01"),
                         Locale(lang="en_US.UTF-8")]),
    ])
    assert host.run("systemctl is-active bastet-demo.service").stdout.strip() == "active"
    assert host.run("systemctl show -p Nice --value bastet-demo.service").stdout.strip() == "5"
    assert host.run("readlink /etc/localtime").stdout.strip().endswith("America/Chicago")


def test_command_contract(host):
    converge(host, [Batch("cmd", [Command(name="marker", run="touch /var/tmp/bastet-marker",
                                          unless="test -e /var/tmp/bastet-marker")])])


from bastet.engine.packages import Package, Repository  # noqa: E402
from bastet.engine.users import AuthorizedKey, Group, User, sudoer  # noqa: E402

HASH = "$6$bastetsalt$" + "x" * 86
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleExampleExampleExampleExampleExample nick@laptop"


def users_batches():
    return [Batch("users", [
        Group(name="media", gid=2001),
        User(name="nick", uid=2000, groups=("media",), shell="/bin/bash", comment="Nick", password_hash=HASH, locked=False),
        AuthorizedKey(user="nick", key=KEY, options='from="10.0.10.0/24"'),
        sudoer("nick", user="nick", nopasswd=True),
    ])]


def check_users(runner):
    assert runner.run("getent passwd nick").stdout.startswith("nick:x:2000:")
    assert "media" in runner.run("id -Gn nick").stdout
    assert runner.run("sudo -n getent shadow nick").stdout.split(":")[1] == HASH
    assert runner.run("sudo -n stat -c '%a %U' /home/nick/.ssh /home/nick/.ssh/authorized_keys").stdout.split() == ["700", "nick", "600", "nick"]
    assert runner.run("sudo -n cat /home/nick/.ssh/authorized_keys").stdout == f'from="10.0.10.0/24" {KEY}\n'
    assert "NOPASSWD: ALL" in runner.run("sudo -n sudo -l -U nick").stdout


def test_packages_contract(host):
    converge(host, [Batch("pkgs", [Package(name="tree"), Package(name="jq", install_recommends=False)])])
    assert host.run("command -v tree && command -v jq").returncode == 0
    converge(host, [Batch("pkgs", [Package(name="tree", state="absent", purge=True)])])
    assert host.run("command -v tree").returncode != 0


def test_repository_contract(host):
    converge(host, [
        Batch("repo", [Repository(name="bastet-backports", uris=("http://deb.debian.org/debian",),
                                  suites=("trixie-backports",), components=("main",),
                                  signed_by="/usr/share/keyrings/debian-archive-keyring.gpg")]),
        Batch("pkg", [Package(name="tree")]),
    ])
    assert "trixie-backports" in host.run("apt-cache policy").stdout


def test_users_contract(host):
    converge(host, users_batches())
    check_users(host)


def test_arch_packages_contract(arch_host):
    converge(arch_host, [Batch("pkgs", [Package(name="tree"), Package(name="jq")])])
    converge(arch_host, [Batch("pkgs", [Package(name="tree", state="absent", purge=True)])])
    assert arch_host.run("command -v tree").returncode != 0


def test_arch_users_contract(arch_host):
    converge(arch_host, users_batches())
    check_users(arch_host)


from pathlib import Path  # noqa: E402

from bastet.roles.builtin import HostInfo, batches_for  # noqa: E402
from bastet.roles.contract import check_values as _check, load_roles as _roles, with_defaults as _defaults  # noqa: E402
from bastet.roles.resolve import Applied  # noqa: E402


def _applied(role, values):
    r = _roles()[role]
    return Applied(r, _defaults(r, _check(r, values, role)))


def test_roles_contract(host):
    info = HostInfo(name="media01", type="vm", data={"os": "Debian GNU/Linux 13 (trixie)", "hostname": "media01"},
                    root=Path("/nonexistent"), lab={})
    batches = batches_for([
        _applied("packages", {"install": ["tree"], "install_recommends": False}),
        _applied("users", {"groups": {"media": {"gid": 2001}},
                           "users": {"nick": {"uid": 2000, "groups": ["media"], "shell": "/bin/bash",
                                              "keys": [KEY], "sudo": {"nopasswd": True}}}}),
        _applied("files", {"files": {"/etc/systemd/system/bastet-demo.service": {"content": DEMO_UNIT, "mode": "0644"}},
                           "directories": {"/srv/bastet": {"mode": "0750"}}}),
        _applied("systemd", {"timezone": "America/Chicago", "locale": "en_US.UTF-8",
                             "services": {"bastet-demo.service": {"enabled": True, "state": "up"}},
                             "dropins": [{"unit": "bastet-demo.service", "name": "bastet", "content": "[Service]\nNice=5\n"}]}),
    ], info)
    converge(host, batches)
    assert host.run("systemctl is-active bastet-demo.service").stdout.strip() == "active"
    assert host.run("command -v tree").returncode == 0
    assert "NOPASSWD: ALL" in host.run("sudo -n sudo -l -U nick").stdout
