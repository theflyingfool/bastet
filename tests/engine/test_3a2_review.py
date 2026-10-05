"""Fixes from the stage 3a.2 review: timeouts, knobs never silently ignored, shared repository files, version
matching, held packages, locked accounts, key paths, and the knobs that were missing."""

import base64

import pytest

from bastet.core.collect import ProbeResult
from bastet.core.errors import Unreachable
from bastet.core.remote import LocalRunner
from bastet.engine.model import Unsupported
from bastet.engine.packages import Package, Repository
from bastet.engine.run import Batch, run_host
from bastet.engine.users import AuthorizedKey, Group, User
from engine_fakes import Flag, GroupedFlag

HASH = "$6$bastetsalt$" + "x" * 86


def ok(text):
    return ProbeResult(0, text)


def pcur(pkg, manager, query=""):
    return pkg.current({"manager": ok(manager), "query": ok(query)})


def cmds(*pkgs, manager="apt-get", query=""):
    return Package.fix_group([(p, p.compare(pcur(p, manager, query)), pcur(p, manager, query)) for p in pkgs])


# C1: fixes get their own long timeout, and a timeout fails the group instead of losing the host

class TimingOutRunner:
    name = "slow"

    def __init__(self):
        self.timeouts = []

    def run(self, script, *, timeout=120):
        self.timeouts.append(timeout)
        if "SLOW-FIX" in script:
            raise Unreachable("bastet@203.0.113.10: timed out after 1800s")
        return LocalRunner().run(script, timeout=timeout)


def test_fix_timeout_fails_the_group_and_keeps_the_run(tmp_path):
    runner = TimingOutRunner()
    slow = [GroupedFlag(path=str(tmp_path / n), value="SLOW-FIX", log=str(tmp_path / "log")) for n in "ab"]
    run = run_host(runner, "h", [Batch("one", [*slow, Flag(path=str(tmp_path / "c"), value="x")]),
                                 Batch("two", [Flag(path=str(tmp_path / "d"), value="y")])], apply=True)
    s = {i.resource.label: (i.status, i.error) for i in run.items}
    assert s[str(tmp_path / "a")][0] == "failed" and "timed out" in s[str(tmp_path / "a")][1]
    assert s[str(tmp_path / "c")][0] == "skipped" and s[str(tmp_path / "d")][0] == "skipped"
    assert max(runner.timeouts) >= 1800


# C2: every knob works where the manager can do it, and is Unsupported where it can't

def test_install_recommends_per_manager():
    assert "--setopt=install_weak_deps=False" in cmds(Package(name="tree", install_recommends=False), manager="dnf")[-1]
    assert "--no-recommends" in cmds(Package(name="tree", install_recommends=False), manager="zypper")[-1]
    assert "--recommends" in cmds(Package(name="tree", install_recommends=True), manager="zypper")[-1]
    for manager in ("pacman", "apk"):
        with pytest.raises(Unsupported):
            pcur(Package(name="tree", install_recommends=False), manager)


@pytest.mark.parametrize("manager,upgrade", [
    ("apt-get", "apt-get -o DPkg::Lock::Timeout=120 -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold full-upgrade -y -q"),
    ("dnf", "dnf upgrade -y -q"), ("zypper", "zypper --non-interactive update"), ("apk", "apk upgrade -q"),
])
def test_full_upgrade_everywhere(manager, upgrade):
    out = cmds(Package(name="tree", full_upgrade=True), manager=manager)
    assert any(c.endswith(upgrade) for c in out)


def test_purge_per_manager():
    assert cmds(Package(name="tree", state="absent", purge=True), manager="apk", query="tree-1-r0") == ["apk del -q --purge tree"]
    for manager, query in (("dnf", "(none):1-1"), ("zypper", "(none):1-1")):
        with pytest.raises(Unsupported):
            pcur(Package(name="tree", state="absent", purge=True), manager, query)


def test_apt_only_package_knobs():
    out = cmds(Package(name="tree", default_release="trixie-backports", allow_change_held=True))
    assert "-t trixie-backports" in out[-1] and "--allow-change-held-packages" in out[-1]
    for knob in ({"default_release": "x"}, {"allow_change_held": True}, {"dpkg_options": ("--force-confnew",)}):
        with pytest.raises(Unsupported):
            pcur(Package(name="tree", **knob), "dnf")


def test_extra_args_everywhere():
    assert cmds(Package(name="tree", extra_args=("--enablerepo=crb",), refresh=False), manager="dnf") == [
        "dnf install -y -q --enablerepo=crb -- tree"]


def test_repository_knobs_unsupported_off_apt():
    for manager in ("dnf", "pacman", "apk"):
        for knob in ({"suites": ("x",)}, {"components": ("main",)}, {"architectures": ("amd64",)}, {"types": ("deb-src",)}):
            repo = Repository(name="r", uris=("http://a",), **knob)
            with pytest.raises(Unsupported):
                repo.current(repo_results(repo, manager))
    for knob in ({"options": (("a", "b"),)}, {"signed_by": "/k"}, {"trusted": True}):
        repo = Repository(name="r", uris=("http://a",), **knob)
        with pytest.raises(Unsupported):
            repo.current(repo_results(repo, "apk"))
    for knob in ({"signed_by": "/k"}, {"trusted": False}):
        repo = Repository(name="r", uris=("http://a",), **knob)
        with pytest.raises(Unsupported):
            repo.current(repo_results(repo, "pacman"))
    two = Repository(name="two", uris=("http://a", "http://b"))
    with pytest.raises(Unsupported):
        two.current(repo_results(two, "zypper"))
    with pytest.raises(ValueError):
        Repository(name="r", uris=("http://a",), key="K", signed_by="/k")


def test_untrusted_means_signature_required_on_dnf():
    repo = Repository(name="r", uris=("http://a",), trusted=False)
    assert "gpgcheck=1" in repo._ini("dnf")


def repo_results(repo, manager, files=None):
    return {r.name: ok(manager) if r.name == "manager" else (files or {}).get(r.name, ok("absent")) for r in repo.reads()}


# I1: parts on one shared file see each other; two repositories in one run re-read

def test_shared_file_parts_are_threaded():
    repo = Repository(name="alp", uris=("https://a/main", "https://a/community"))
    cur = repo.current(repo_results(repo, "apk"))
    final = [part.wanted(state["content"]) for part, state in repo._threaded(cur)][-1]
    assert final == "https://a/main\nhttps://a/community\n"
    script = "\n".join(repo.fix(repo.compare(cur), cur))
    last = [line for line in script.splitlines() if "base64 -d" in line][-1]
    assert base64.b64decode(last.split("'")[3]).decode() == final
    assert repo.touches() == Repository(name="other", uris=("http://b",)).touches() is not None


# I2: held packages are installed

def test_held_package_is_installed():
    assert pcur(Package(name="tree"), "apt-get", "hi |1.0-1")["state"] == "present"


# I4: rpm versions with epoch and release; any installed version counts

def test_rpm_version_matching():
    p = Package(name="foo", version="1.2.3")
    assert p.compare(pcur(p, "dnf", "(none):1.2.3-4.fc40")) == []
    assert p.compare(pcur(p, "dnf", "2:1.2.3-4.fc40")) == []
    assert [c.field for c in Package(name="foo", version="1.2.4").compare(pcur(p, "dnf", "(none):1.2.3-4.fc40"))] == ["version"]
    k = Package(name="kernel", version="6.2")
    assert k.compare(pcur(k, "dnf", "(none):6.1-1\n(none):6.2-1")) == []
    assert pcur(Package(name="foo"), "dnf", "(none):1.2.3-4.fc40")["version"] == "1.2.3-4.fc40"


# I6 + I7: downgrades, conffile prompts, zypper old packages

def test_pins_allow_downgrades_and_conffiles_kept():
    apt = cmds(Package(name="tree", version="1.0", refresh=False))
    assert apt == ["DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=120 -o Dpkg::Options::=--force-confdef "
                   "-o Dpkg::Options::=--force-confold install -y -q --allow-downgrades -- tree=1.0"]
    assert "--oldpackage" in cmds(Package(name="tree", version="1.0", refresh=False), manager="zypper")[-1]


def test_zypper_key_imported_and_apk_key_name():
    repo = Repository(name="z", uris=("http://a",), key="-----BEGIN PGP PUBLIC KEY BLOCK-----\nX\n-----END PGP PUBLIC KEY BLOCK-----\n")
    cur = repo.current(repo_results(repo, "zypper"))
    assert repo.fix(repo.compare(cur), cur)[-1] == "rpm --import /etc/pki/rpm-gpg/RPM-GPG-KEY-bastet-z"
    apk = Repository(name="edge", uris=("http://a",), key="K", key_name="alpine-devel@lists.alpinelinux.org-6165ee59.rsa.pub")
    assert apk.parts("apk")[-1].path == "/etc/apk/keys/alpine-devel@lists.alpinelinux.org-6165ee59.rsa.pub"
    with pytest.raises(ValueError):
        Repository(name="e", uris=("http://a",), key_name="../x")


# I3: custom key path leaves its directory alone

def test_custom_key_path_keeps_directory():
    k = AuthorizedKey(user="nick", key="ssh-ed25519 AAAAbody nick@laptop", path="/etc/ssh/authorized_keys/nick")
    cur = k.current({"keys": ok("nouser")})
    script = "\n".join(k.fix(k.compare(cur), cur))
    assert "chmod 700" not in script and "chmod 600" in script


def test_key_can_be_revoked():
    k = AuthorizedKey(user="nick", key="ssh-ed25519 AAAAbody nick@laptop", state="absent")
    assert k.wanted("ssh-ed25519 AAAAbody nick@laptop\nssh-rsa AAAAother x\n") == "ssh-rsa AAAAother x\n"
    assert k.wanted("ssh-rsa AAAAother x\n") == "ssh-rsa AAAAother x\n"


# I5: a new password never unlocks a locked account

def user_state(shadow):
    return {"passwd": ok("nick:x:1000:1000:Nick:/home/nick:/bin/bash"), "groups": ok("nick|nick"),
            "shadow": ok(shadow), "tools": ok("/usr/sbin/useradd")}


def test_new_password_keeps_lock():
    for locked in (True, None):
        u = User(name="nick", password_hash="$6$new$" + "y" * 86, locked=locked)
        cur = u.current(user_state(f"nick:!{HASH}:19000:0:99999:7:::"))
        out = u.fix(u.compare(cur), cur)
        assert out[-1] == "usermod -L nick"


def test_password_only_on_create():
    u = User(name="nick", password_hash="$6$new$" + "y" * 86, update_password="on_create")
    assert u.compare(u.current(user_state(f"nick:{HASH}:19000:0:99999:7:::"))) == []


def test_password_ageing_and_creation_knobs():
    u = User(name="nick", max_days=90, min_days=1, warn_days=14, inactive_days=30)
    cur = u.current(user_state(f"nick:{HASH}:19000:0:99999:7:::"))
    assert [c.field for c in u.compare(cur)] == ["max_days", "min_days", "warn_days", "inactive_days"]
    assert u.fix(u.compare(cur), cur) == ["chage -M 90 -m 1 -W 14 -I 30 nick"]
    new = User(name="svc", uid=0, non_unique=True, skeleton="/etc/skel-svc")
    absent = new.current({"passwd": ok(""), "groups": ok("|"), "shadow": ok(""), "tools": ok("/usr/sbin/useradd")})
    assert new.fix(new.compare(absent), absent)[0] == "useradd -u 0 -o -k /etc/skel-svc -m svc"


def test_group_members_append():
    g = Group(name="media", members=("jellyfin",), append_members=True)
    present = g.current({"group": ok("media:x:2001:nick")})
    assert g.fix(g.compare(present), present) == ["gpasswd -a jellyfin media"]
    assert Group(name="media", members=("nick",), append_members=True).compare(present) == []
