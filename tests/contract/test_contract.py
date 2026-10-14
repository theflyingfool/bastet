from bastet.engine.command import Command
from bastet.engine.files import Block, Directory, File, Line, Symlink
from bastet.engine.report import render_host
from bastet.engine.run import Batch, run_host
from bastet.engine.systemd import Hostname, Locale, TimeSettings, Unit, daemon_reload, drop_in

TRICKY = "say \"hi\" to $HOME \\ 'q' · ünïcode\nno trailing newline"
DEMO_UNIT = "[Unit]\nDescription=Bastet contract demo\n[Service]\nExecStart=/bin/sleep infinity\n[Install]\nWantedBy=multi-user.target\n"


def converge(runner, batches):
    check = run_host(runner, "ct", batches, apply=False)
    assert all(i.status == "would-change" or i.resource.report_only() for i in check.items), render_host(check, full=True)
    first = run_host(runner, "ct", batches, apply=True)
    assert first.ok, render_host(first, full=True)
    second = run_host(runner, "ct", batches, apply=True)
    assert all(i.status in ("compliant", "attention") for i in second.items) and not second.triggers, render_host(second, full=True)
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


from bastet.engine.packages import Package  # noqa: E402
from bastet.engine.users import AuthorizedKey, Group, User, sudoer  # noqa: E402

HASH = "$6$bastetsalt$" + "x" * 86
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleExampleExampleExampleExampleExample admin@laptop"


def users_batches():
    return [Batch("users", [
        Group(name="media", gid=2001),
        User(name="alice", uid=2000, groups=("media",), shell="/bin/bash", comment="Alice", password_hash=HASH, locked=False),
        AuthorizedKey(user="alice", key=KEY, options='from="10.0.10.0/24"'),
        sudoer("alice", user="alice", nopasswd=True),
    ])]


def check_users(runner):
    assert runner.run("getent passwd alice").stdout.startswith("alice:x:2000:")
    assert "media" in runner.run("id -Gn alice").stdout
    assert runner.run("sudo -n getent shadow alice").stdout.split(":")[1] == HASH
    assert runner.run("sudo -n stat -c '%a %U' /home/alice/.ssh /home/alice/.ssh/authorized_keys").stdout.split() == ["700", "alice", "600", "alice"]
    assert runner.run("sudo -n cat /home/alice/.ssh/authorized_keys").stdout == f'from="10.0.10.0/24" {KEY}\n'
    assert "NOPASSWD: ALL" in runner.run("sudo -n sudo -l -U alice").stdout


def test_packages_contract(host):
    converge(host, [Batch("pkgs", [Package(name="tree"), Package(name="jq", install_recommends=False)])])
    assert host.run("command -v tree && command -v jq").returncode == 0
    converge(host, [Batch("pkgs", [Package(name="tree", state="absent", purge=True)])])
    assert host.run("command -v tree").returncode != 0


def test_repository_contract(host):
    info = HostInfo(name="media01", type="vm", data={"os": "Debian GNU/Linux 13 (trixie)", "hostname": "media01"},
                    root=Path("/x"), lab={})
    apt = _applied("apt", {"repositories": [{"name": "bastet-backports", "uris": ["http://deb.debian.org/debian"],
                                             "suites": ["trixie-backports"], "components": ["main"],
                                             "signed_by": "/usr/share/keyrings/debian-archive-keyring.gpg"}]})
    converge(host, [*batches_for([apt], info), Batch("pkg", [Package(name="tree")])])
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
from bastet.roles.contract import check_values as _check  # noqa: E402
from bastet.roles.contract import load_roles as _roles
from bastet.roles.contract import with_defaults as _defaults
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
                           "users": {"alice": {"uid": 2000, "groups": ["media"], "shell": "/bin/bash",
                                              "keys": [KEY], "sudo": {"nopasswd": True}}}}),
        _applied("files", {"files": {"/etc/systemd/system/bastet-demo.service": {"content": DEMO_UNIT, "mode": "0644"}},
                           "directories": {"/srv/bastet": {"mode": "0750"}}}),
        _applied("systemd", {"locale": "en_US.UTF-8",
                             "services": {"bastet-demo.service": {"enabled": True, "state": "up"}},
                             "dropins": [{"unit": "bastet-demo.service", "name": "bastet", "content": "[Service]\nNice=5\n"}]}),
    ], info)
    converge(host, batches)
    assert host.run("systemctl is-active bastet-demo.service").stdout.strip() == "active"
    assert host.run("command -v tree").returncode == 0
    assert "NOPASSWD: ALL" in host.run("sudo -n sudo -l -U alice").stdout


from bastet.engine.packages import Unaccounted, Updates  # noqa: E402


def test_updates_and_unaccounted_contract(host):
    check = run_host(host, "ct", [Batch("p", [Updates(policy="auto"), Unaccounted(tracked=("systemd",))])], apply=False)
    unacc = next(i for i in check.items if i.resource.identity == "unaccounted")
    assert unacc.status == "attention" and "sudo" in unacc.diff
    run_host(host, "ct", [Batch("p", [Updates(policy="auto")])], apply=True)
    again = run_host(host, "ct", [Batch("p", [Updates(policy="auto")])], apply=False)
    assert again.items[0].status == "compliant", render_host(again, full=True)


def test_arch_updates_reported(arch_host):
    check = run_host(arch_host, "ct", [Batch("p", [Updates(), Unaccounted()])], apply=False)
    assert all(i.status in ("compliant", "attention") for i in check.items), render_host(check, full=True)


def test_arch_pacman_contract(arch_host):
    info = HostInfo(name="ct", type="vm", data={"os": "Arch Linux"}, root=Path("/nonexistent"), lab={})
    converge(arch_host, batches_for([_applied("pacman", {"parallel_downloads": 8})], info))
    conf = arch_host.run("cat /etc/pacman.conf").stdout
    assert "\nColor\n" in conf and "\nILoveCandy\n" in conf and "ParallelDownloads = 8" in conf
    assert arch_host.run("pacman-conf >/dev/null").returncode == 0  # still a valid config


def test_arch_pacman_managed_block_contract(arch_host):
    info = HostInfo(name="ct", type="vm", data={"os": "Arch Linux"}, root=Path("/nonexistent"), lab={})
    arch_host.run("printf '[options]\\nParallelDownloads = 5\\nColor\\n\\n[custom]\\nSigLevel = Never\\nServer = file:///nonexistent\\n' > /etc/pacman.conf")
    seeded = arch_host.run("cat /etc/pacman.conf").stdout
    batches = batches_for([_applied("pacman", {"parallel_downloads": 7, "color": False})], info)
    assert run_host(arch_host, "ct", batches, apply=True).ok
    assert arch_host.run("pacman-conf ParallelDownloads").stdout.strip() == "7"
    assert arch_host.run("pacman-conf --config /etc/pacman.conf | grep -c '^Color'").stdout.strip() == "0"
    assert arch_host.run("pacman-conf --repo-list").stdout.split() == ["custom"]
    assert arch_host.run("grep -c '^SigLevel = Never' /etc/pacman.conf").stdout.strip() == "1"
    assert arch_host.run("cat /etc/pacman.conf.bastet-orig").stdout == seeded
    again = run_host(arch_host, "ct", batches, apply=True)
    assert all(i.status == "compliant" for i in again.items), render_host(again, full=True)


def test_arch_pacman_all_kinds_contract(arch_host):
    info = HostInfo(name="ct", type="vm", data={"os": "Arch Linux"}, root=Path("/nonexistent"), lab={})
    batches = batches_for([_applied("pacman", {
        "ignore_pkg": ["linux", "linux-headers"], "no_extract": ["usr/share/doc/*"], "clean_method": ["KeepCurrent"],
        "verbose_pkg_lists": True, "check_space": False})], info)
    assert run_host(arch_host, "ct", batches, apply=True).ok  # this image already has some of these set
    again = run_host(arch_host, "ct", batches, apply=True)
    assert all(i.status == "compliant" for i in again.items), render_host(again, full=True)
    assert arch_host.run("pacman-conf IgnorePkg").stdout.split() == ["linux", "linux-headers"]
    assert arch_host.run("pacman-conf NoExtract").stdout.strip() == "usr/share/doc/*"
    assert arch_host.run("pacman-conf CleanMethod").stdout.strip() == "KeepCurrent"
    assert "VerbosePkgLists" in arch_host.run("pacman-conf").stdout and "CheckSpace" not in arch_host.run("pacman-conf").stdout


def test_debian_apt_role_contract(host):
    info = HostInfo(name="ct", type="vm", data={"os": "Debian GNU/Linux 13 (trixie)"}, root=Path("/nonexistent"), lab={})
    batches = batches_for([_applied("apt", {"install_recommends": False, "acquire_retries": 3})], info)
    first = run_host(host, "ct", batches, apply=True)
    assert first.ok, render_host(first, full=True)
    dump = host.run("apt-config dump").stdout
    assert 'APT::Install-Recommends "false"' in dump and 'Acquire::Retries "3"' in dump
    again = run_host(host, "ct", batches, apply=True)
    assert all(i.status == "compliant" for i in again.items) and not again.triggers, render_host(again, full=True)


def test_debian_apt_modernize_sources_contract(host):
    info = HostInfo(name="ct", type="vm", data={"os": "Debian GNU/Linux 13 (trixie)"}, root=Path("/nonexistent"), lab={})
    host.run("printf 'deb http://deb.debian.org/debian trixie main\\n' | sudo -n tee /etc/apt/sources.list.d/legacy.list "
             "|| printf 'deb http://deb.debian.org/debian trixie main\\n' > /etc/apt/sources.list.d/legacy.list")
    batches = batches_for([_applied("apt", {"modernize_sources": True})], info)
    first = run_host(host, "ct", batches, apply=True)
    assert first.ok, render_host(first, full=True)
    assert host.run("test -e /etc/apt/sources.list.d/legacy.sources").returncode == 0
    assert host.run("test -e /etc/apt/sources.list.d/legacy.list.bak").returncode == 0
    again = run_host(host, "ct", batches, apply=True)
    assert all(i.status == "compliant" for i in again.items) and not again.triggers, render_host(again, full=True)

