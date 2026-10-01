import pytest

from bastet.core.collect import ProbeResult
from bastet.engine.model import Unsupported
from bastet.engine.systemd import Hostname, Locale, TimeSettings, Unit, daemon_reload, drop_in, restart


def ok(text):
    return ProbeResult(0, text)


def test_unit_parse_and_fix():
    u = Unit(name="chrony.service", enabled=True, state="up")
    cur = u.current({"show": ok("LoadState=loaded\nUnitFileState=disabled\nActiveState=inactive")})
    assert cur == {"exists": True, "enabled": False, "state": "down"}
    changes = u.compare(cur)
    assert [c.field for c in changes] == ["enabled", "state"]
    assert u.fix(changes, cur) == ["systemctl enable chrony.service", "systemctl start chrony.service"]


def test_unit_running_and_enabled_is_compliant():
    u = Unit(name="ssh.service", enabled=True, state="up")
    assert u.compare(u.current({"show": ok("LoadState=loaded\nUnitFileState=enabled\nActiveState=active")})) == []


def test_unit_not_found_reads_absent_and_reloads_first():
    u = Unit(name="gitea.service", enabled=True, state="up")
    cur = u.current({"show": ok("LoadState=not-found\nUnitFileState=\nActiveState=inactive")})
    assert cur["exists"] is False
    assert u.fix(u.compare(cur), cur)[0] == "systemctl daemon-reload"


def test_unit_without_systemd_is_unsupported():
    with pytest.raises(Unsupported):
        Unit(name="x", state="up").current({"show": ProbeResult(127, "")})


def test_drop_in_and_trigger_order():
    f = drop_in("gitea.service", "bastet", "[Service]\nNice=5\n")
    assert f.path == "/etc/systemd/system/gitea.service.d/bastet.conf" and f.mode == "0644"
    assert [t.label for t in f.on_change] == ["daemon-reload", "restart gitea.service"]
    assert daemon_reload().order < restart("x").order
    assert drop_in("a", "b", "c", restart_unit=False).on_change == (daemon_reload(),)


def test_time_settings_with_systemd():
    t = TimeSettings(timezone="America/Chicago", ntp=True, rtc_local=False)
    cur = t.current({"timedatectl": ok("Timezone=Etc/UTC\nLocalRTC=no\nCanNTP=yes\nNTP=no\nNTPSynchronized=no"),
                     "localtime": ok("/usr/share/zoneinfo/Etc/UTC")})
    changes = t.compare(cur)
    assert [(c.field, c.before, c.after) for c in changes] == [("timezone", "Etc/UTC", "America/Chicago"), ("ntp", False, True)]
    assert t.fix(changes, cur) == ["timedatectl set-timezone America/Chicago", "timedatectl set-ntp true"]


def test_time_settings_without_systemd():
    results = {"timedatectl": ProbeResult(127, ""), "localtime": ok("/usr/share/zoneinfo/Europe/Amsterdam")}
    t = TimeSettings(timezone="UTC")
    cur = t.current(results)
    assert cur["timezone"] == "Europe/Amsterdam"
    assert "ln -sf /usr/share/zoneinfo/UTC /etc/localtime" in t.fix(t.compare(cur), cur)
    with pytest.raises(Unsupported):
        TimeSettings(timezone="UTC", ntp=True).current(results)


def test_hostname():
    h = Hostname(name="media01")
    cur = h.current({"static": ok("# set by installer\nlocalhost\n")})
    assert cur == {"hostname": "localhost"}
    [cmd] = h.fix(h.compare(cur), cur)
    assert "hostnamectl set-hostname media01" in cmd and "/etc/hostname" in cmd


def test_locale():
    loc = Locale(lang="en_US.UTF-8", keymap="us")
    cur = loc.current({"localectl": ok("   System Locale: LANG=C.UTF-8\n                  LC_TIME=en_GB.UTF-8\n       VC Keymap: (unset)\n      X11 Layout: us")})
    assert cur == {"lang": "C.UTF-8", "keymap": "(absent)", "tool": "localectl"}
    assert loc.fix(loc.compare(cur), cur) == ["localectl set-locale LANG=en_US.UTF-8", "localectl set-keymap us"]
    with pytest.raises(Unsupported):
        loc.current({"localectl": ProbeResult(127, "")})


def test_locale_on_debian_uses_update_locale():
    status = ok("   System Locale: LANG=C.UTF-8\n       VC Keymap: (unset)")
    loc = Locale(lang="en_US.UTF-8")
    cur = loc.current({"localectl": status, "update_locale": ok("/usr/sbin/update-locale")})
    assert loc.fix(loc.compare(cur), cur) == ["update-locale LANG=en_US.UTF-8"]
    with pytest.raises(Unsupported) as e:
        Locale(lang="en_US.UTF-8", keymap="us").current({"localectl": status, "update_locale": ok("/usr/sbin/update-locale")})
    assert "console-setup" in str(e.value)
    assert Locale(lang="en_US.UTF-8").current({"localectl": status, "update_locale": ProbeResult(1, "")})["tool"] == "localectl"
