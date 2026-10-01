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
    assert host.run("cat /etc/bastet-ct/motd").stdout == TRICKY
    assert host.run("stat -c %a /etc/bastet-ct/motd").stdout.strip() == "640"


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
