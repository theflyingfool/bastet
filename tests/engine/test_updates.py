import pytest

from bastet.core.shell import ProbeResult
from bastet.core.remote import LocalRunner
from bastet.engine.model import Unsupported
from bastet.engine.packages import Reboot, Unaccounted, Updates
from bastet.engine.run import Batch, run_host
from engine_fakes import Flag


def ok(text):
    return ProbeResult(0, text)


def upd(policy="manual", manager="apt-get", pending="", security="", **kw):
    u = Updates(policy=policy, **kw)
    return u, u.current({"manager": ok(manager), "pending": ok(pending), "security": ok(security)})


APT = ("Listing...\ntree/trixie 2.2.1-1 amd64 [upgradable from: 2.1.1-2]\n"
       "openssl/trixie-security 3.5.1-1 amd64 [upgradable from: 3.5.0-1]\nlinux-image-amd64/trixie 6.12.9 amd64 [upgradable from: 6.12.8]\n")


def test_apt_pending_security_and_fix():
    u, cur = upd(pending=APT, policy="auto")
    assert cur["pending"] == ("linux-image-amd64", "openssl", "tree") and cur["security"] == ("openssl",)
    [c] = u.compare(cur)
    assert (c.field, c.before, c.after) == ("updates", "3 pending", "up to date")
    assert u.fix([c], cur)[-1].endswith("full-upgrade -y -q")
    s, scur = upd(pending=APT, policy="security")
    assert s.fix(s.compare(scur), scur)[-1].endswith("install --only-upgrade -y -q -- openssl")


def test_manual_updates_are_report_only():
    assert Updates(policy="manual").report_only() and not Updates(policy="manual", apply_updates=True).report_only()
    assert not Updates(policy="auto").report_only()


def test_updates_exclude_per_manager():
    u, cur = upd(pending=APT, policy="auto", exclude=("linux-image-amd64",))
    assert cur["pending"] == ("openssl", "tree")
    assert u.fix(u.compare(cur), cur)[-1].endswith("install --only-upgrade -y -q -- openssl tree")
    p, pcur = upd(manager="pacman", pending="linux 6.1.1-1 -> 6.1.2-1\nlinux-lts 6.6.1-1 -> 6.6.2-1\n", policy="auto",
                  exclude=("linux-lts",))
    assert pcur["pending"] == ("linux",) and p.fix(p.compare(pcur), pcur) == ["pacman -Syu --noconfirm --ignore linux-lts"]


def test_other_managers():
    d, dcur = upd(manager="dnf", pending="\ntree.x86_64   2.2.1-1.fc42   updates\nbash.x86_64  5.3-1.fc42  updates\n",
                  security="FEDORA-2026-1 Important/Sec. bash-5.3-1.fc42.x86_64\n", policy="security")
    assert dcur["pending"] == ("bash", "tree") and dcur["security"] == ("bash",)
    assert d.fix(d.compare(dcur), dcur) == ["dnf upgrade -y -q --security"]
    z, zcur = upd(manager="zypper", pending="S | Repository | Name | Current | Available | Arch\n--+--\nv | repo-oss | tree | 2.1 | 2.2 | x86_64\n",
                  policy="auto")
    assert zcur["pending"] == ("tree",) and z.fix(z.compare(zcur), zcur) == ["zypper --non-interactive update"]
    a, acur = upd(manager="apk", pending="tree-2.1.1-r0 < 2.2.1-r0\n", policy="auto")
    assert acur["pending"] == ("tree",) and a.fix(a.compare(acur), acur) == ["apk upgrade -q"]


def test_no_security_channel_and_up_to_date():
    with pytest.raises(Unsupported):
        upd(manager="pacman", policy="security")
    u, cur = upd(pending="Listing...\n")
    assert u.compare(cur) == []


def test_arch_needs_checkupdates():
    with pytest.raises(Unsupported) as e:
        Updates().current({"manager": ok("pacman"), "pending": ProbeResult(127, ""), "security": ok("")})
    assert "pacman-contrib" in str(e.value)


def test_reboot():
    r = Reboot()
    assert r.report_only() and r.compare(r.current({"reboot": ok("")})) == []
    [c] = r.compare(r.current({"reboot": ok("debian\n")}))
    assert (c.field, c.before) == ("reboot", "needed (debian)")


def test_unaccounted_arch():
    u = Unaccounted(tracked=("tree",), allowed=("neovim",))
    cur = u.current({"manager": ok("pacman"), "explicit": ok("base\nbase-devel\ntree\nneovim\nsteam\nhtop\n"), "system": ok("base\nbase-devel\n")})
    assert cur["unaccounted"] == ("htop", "steam")
    [c] = u.compare(cur)
    assert (c.field, c.before, c.after) == ("unaccounted", "2 packages", "none") and u.diff_text(cur) == "htop\nsteam"


def test_unaccounted_debian_priorities():
    u = Unaccounted(tracked=("tree",))
    system = "bash required\ncoreutils required\nopenssh-server standard\nvim-tiny important\ntree optional\n"
    cur = u.current({"manager": ok("apt-get"), "explicit": ok("bash\ncoreutils\nopenssh-server\ntree\n"), "system": ok(system)})
    assert cur["unaccounted"] == () and u.compare(cur) == []
    with pytest.raises(Unsupported):
        u.current({"manager": ok("zypper"), "explicit": ok(""), "system": ok("")})


def test_apk_world_constraints_stripped():
    u = Unaccounted()
    cur = u.current({"manager": ok("apk"), "explicit": ok("alpine-base\nopenssh>9\ncurl=8.1-r0\n"), "system": ok("alpine-base\n")})
    assert cur["unaccounted"] == ("curl", "openssh")


def test_attention_items_are_reported_not_fixed(tmp_path):
    from dataclasses import dataclass

    @dataclass(frozen=True, kw_only=True)
    class Finding(Flag):
        def report_only(self):
            return True

    run = run_host(LocalRunner(), "h", [Batch("t", [Finding(path=str(tmp_path / "a"), value="1")])], apply=True)
    assert run.items[0].status == "attention" and run.ok and not (tmp_path / "a").exists()
