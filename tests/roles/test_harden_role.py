from pathlib import Path

import pytest

from bastet.core.errors import BastetError
from bastet.engine.files import File
from bastet.engine.packages import Package
from bastet.engine.security import AppArmorStatus, ListeningPorts, LynisReport, ServiceExposure, VulnerablePackages
from bastet.engine.systemd import Unit
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import check_values, load_roles, with_defaults
from bastet.roles.resolve import Applied

ROLES = load_roles()
SAFE = {"kernel.kptr_restrict = 1", "kernel.dmesg_restrict = 1", "fs.protected_hardlinks = 1",
        "fs.protected_symlinks = 1", "fs.protected_fifos = 1", "fs.protected_regular = 2", "net.ipv4.tcp_syncookies = 1",
        "net.ipv4.conf.all.accept_redirects = 0", "net.ipv4.conf.default.accept_redirects = 0",
        "net.ipv6.conf.all.accept_redirects = 0", "net.ipv6.conf.default.accept_redirects = 0"}


def ap(role, values):
    r = ROLES[role]
    return Applied(r, with_defaults(r, check_values(r, values, role)))


def host(os="Debian GNU/Linux 13 (trixie)", type_="vm"):
    return HostInfo(name="h", type=type_, data={"os": os}, root=Path("/x"), lab={})


def out(*applied, h=None):
    return [r for b in batches_for(list(applied), h or host()) for r in b.resources]


def files(res):
    return {r.path: r for r in res if isinstance(r, File)}


def test_defaults_are_reports_and_safe_sysctl_only():
    res = out(ap("harden", {}))
    kinds = {type(r) for r in res}
    assert {VulnerablePackages, ServiceExposure, ListeningPorts, AppArmorStatus} <= kinds and LynisReport not in kinds
    f = files(res)
    assert set(f["/etc/sysctl.d/90-bastet.conf"].content.splitlines()[1:]) == SAFE
    assert not any("fail2ban" in p or "modprobe" in p or "coredump" in p or "sudoers" in p for p in f)
    assert not any(isinstance(r, Package) and r.name in ("lynis", "fail2ban") for r in res)


def test_lxc_skips_sysctl_defaults_and_rejects_explicit():
    assert "/etc/sysctl.d/90-bastet.conf" not in files(out(ap("harden", {}), h=host(type_="lxc")))
    with pytest.raises(BastetError, match="harden.sysctl"):
        out(ap("harden", {"sysctl": {"vm.swappiness": "10"}}), h=host(type_="lxc"))
    with pytest.raises(BastetError, match="harden.block_modules"):
        out(ap("harden", {"block_modules": ["usb-storage"]}), h=host(type_="lxc"))


def test_sysctl_entries_override_defaults_and_can_turn_defaults_off():
    text = files(out(ap("harden", {"sysctl": {"kernel.dmesg_restrict": "0", "vm.swappiness": "10"}})))["/etc/sysctl.d/90-bastet.conf"].content
    assert "kernel.dmesg_restrict = 0" in text and "kernel.dmesg_restrict = 1" not in text and "vm.swappiness = 10" in text
    assert "/etc/sysctl.d/90-bastet.conf" not in files(out(ap("harden", {"sysctl_defaults": False})))


def test_fail2ban_jail_follows_ssh_ports():
    res = out(ap("ssh", {"port": [2222, 22]}), ap("harden", {"fail2ban": True}))
    jail = files(res)["/etc/fail2ban/jail.d/bastet.local"].content
    assert "[sshd]\nenabled = true\nport = 2222,22\n" in jail and "backend = systemd" in jail
    assert any(isinstance(r, Unit) and r.name == "fail2ban.service" and r.enabled for r in res)
    default = files(out(ap("harden", {"fail2ban": True})))["/etc/fail2ban/jail.d/bastet.local"].content
    assert "port = ssh\n" in default


def test_fail2ban_extra_jails_written():
    jail = files(out(ap("harden", {"fail2ban": True, "fail2ban_jails": {"nginx-http-auth": {"enabled": True, "maxretry": 3}}})))[
        "/etc/fail2ban/jail.d/bastet.local"].content
    assert "[nginx-http-auth]\nenabled = true\nmaxretry = 3\n" in jail


def test_fail2ban_sandbox_drop_in():
    sandbox = "/etc/systemd/system/fail2ban.service.d/bastet-sandbox.conf"
    f = files(out(ap("harden", {"fail2ban": True})))
    assert "ProtectSystem=strict" in f[sandbox].content and "CAP_NET_ADMIN" in f[sandbox].content
    assert sandbox not in files(out(ap("harden", {"fail2ban": True, "fail2ban_sandbox": False})))


def test_core_dumps_off_and_block_modules_and_sudo_defaults():
    f = files(out(ap("harden", {"core_dumps": "off", "block_modules": ["usb-storage", "dccp"],
                                "sudo_defaults": ["use_pty", "logfile=/var/log/sudo.log"]})))
    assert "Storage=none" in f["/etc/systemd/coredump.conf.d/bastet.conf"].content
    assert "fs.suid_dumpable = 0" in f["/etc/sysctl.d/90-bastet.conf"].content
    blocklist = f["/etc/modprobe.d/bastet-blocklist.conf"].content
    assert "install usb-storage /bin/false\nblacklist usb-storage\n" in blocklist and "blacklist dccp" in blocklist
    assert "Defaults use_pty" in f["/etc/sudoers.d/bastet_defaults"].content


def test_vulnerable_packages_tool_by_os():
    def tool(os):
        return next(r for r in out(ap("harden", {}), h=host(os=os)) if isinstance(r, VulnerablePackages)).tool
    assert tool("Arch Linux") == "arch-audit" and tool("Debian GNU/Linux 13 (trixie)") == "debsecan"
    with pytest.raises(BastetError, match="harden.vulnerable_packages"):
        out(ap("harden", {}), h=host(os="Alpine Linux v3.20"))
    assert not any(isinstance(r, VulnerablePackages) for r in out(ap("harden", {"vulnerable_packages": False}), h=host(os="Alpine Linux v3.20")))


def test_exposure_managed_units_filled():
    res = out(ap("harden", {"fail2ban": True, "exposure_target": 4.5}))
    exposure = next(r for r in res if isinstance(r, ServiceExposure))
    assert "fail2ban.service" in exposure.managed and exposure.target == 4.5


def test_listening_ports_account_for_ssh():
    res = out(ap("ssh", {"port": [2222]}), ap("harden", {"allowed_ports": ["tcp/8006"]}))
    ports = next(r for r in res if isinstance(r, ListeningPorts))
    assert {"tcp/2222", "tcp/8006", "sshd"} <= set(ports.accounted)
    assert any(isinstance(r, Package) and r.name == "iproute2" for r in res)


def test_lynis_installs_and_turns_the_package_timer_off():
    res = out(ap("harden", {"lynis": True}))
    assert any(isinstance(r, LynisReport) for r in res) and any(isinstance(r, Package) and r.name == "lynis" for r in res)
    from bastet.engine.files import Symlink
    mask = next(i for i, r in enumerate(res) if isinstance(r, Symlink) and r.path == "/etc/systemd/system/lynis.timer")
    lynis = next(i for i, r in enumerate(res) if isinstance(r, Package) and r.name == "lynis")
    assert res[mask].target == "/dev/null" and mask < lynis  # masked before the package can enable it
    kept = out(ap("harden", {"lynis": True, "lynis_timer": True}))
    assert not any(isinstance(r, Symlink) for r in kept)


def test_requiretty_refused():
    with pytest.raises(BastetError, match="requiretty"):
        out(ap("harden", {"sudo_defaults": ["use_pty", "requiretty"]}))
    with pytest.raises(BastetError, match="requiretty"):
        out(ap("harden", {"sudo_defaults": ["!requiretty", "requiretty"]}))
    assert out(ap("harden", {"sudo_defaults": ["!requiretty"]}))


def test_sshd_jail_settings_merge_into_the_builtin_section():
    jail = files(out(ap("harden", {"fail2ban": True, "fail2ban_jails": {"sshd": {"mode": "aggressive"}}})))[
        "/etc/fail2ban/jail.d/bastet.local"].content
    assert jail.count("[sshd]") == 1 and "mode = aggressive" in jail


def test_fail2ban_sandbox_creates_its_runtime_dir():
    sandbox = files(out(ap("harden", {"fail2ban": True})))["/etc/systemd/system/fail2ban.service.d/bastet-sandbox.conf"].content
    assert "RuntimeDirectory=fail2ban" in sandbox and "/run/fail2ban" not in sandbox


def test_sysctl_ignores_missing_keys():
    f = files(out(ap("harden", {})))["/etc/sysctl.d/90-bastet.conf"]
    assert f.on_change[0].command.startswith("sysctl -q -e -p ")


def test_debsecan_only_on_debian_proper():
    with pytest.raises(BastetError, match="harden.vulnerable_packages"):
        out(ap("harden", {}), h=host(os="Ubuntu 24.04.1 LTS"))
    assert any(isinstance(r, VulnerablePackages) for r in out(ap("harden", {}), h=host(os="Debian GNU/Linux 12 (bookworm)")))
