import pytest

from bastet.core.shell import ProbeResult
from bastet.engine.model import ReadError, Unsupported
from bastet.engine.packages import Package


def ok(text):
    return ProbeResult(0, text)


def cur(pkg, manager, query):
    return pkg.current({"manager": ok(manager), "query": ok(query)})


@pytest.mark.parametrize("manager,query,version", [
    ("apt-get", "ii |1.8.1-1", "1.8.1-1"),
    ("apt-get", "rc |1.8.1-1", None),
    ("apt-get", "", None),
    ("pacman", "tree 2.2.1-1", "2.2.1-1"),
    ("pacman", "", None),
    ("dnf", "2.1.1-6.fc42", "2.1.1-6.fc42"),
    ("dnf", "package tree is not installed", None),
    ("zypper", "package tree is not installed", None),
    ("apk", "tree-2.1.1-r0", "2.1.1-r0"),
    ("apk", "", None),
])
def test_installed_detection(manager, query, version):
    c = cur(Package(name="tree"), manager, query)
    assert c["version"] == (version or "(absent)") and c["state"] == ("present" if version else "absent")


def test_compare_present_absent_and_version():
    p = Package(name="tree")
    assert [x.field for x in p.compare(cur(p, "apt-get", ""))] == ["state"]
    assert p.compare(cur(p, "apt-get", "ii |1.0")) == []
    pinned = Package(name="tree", version="2.0")
    assert [(x.field, x.before, x.after) for x in pinned.compare(cur(pinned, "apt-get", "ii |1.0"))] == [("version", "1.0", "2.0")]
    gone = Package(name="tree", state="absent")
    assert gone.compare(cur(gone, "apt-get", "")) == [] and [x.field for x in gone.compare(cur(gone, "pacman", "tree 1-1"))] == ["state"]


def test_no_manager_and_unhonourable_knobs():
    with pytest.raises(Unsupported):
        Package(name="tree").current({"manager": ProbeResult(127, ""), "query": ok("")})
    with pytest.raises(Unsupported):
        cur(Package(name="tree", version="1.0"), "pacman", "")
    with pytest.raises(ReadError):
        cur(Package(name="tree", manager="dnf"), "apt-get", "")


def group(*pkgs, manager="apt-get", query=""):
    return [(p, p.compare(cur(p, manager, query)), cur(p, manager, query)) for p in pkgs]


def test_apt_install_group_is_one_command():
    cmds = Package.fix_group(group(Package(name="tree"), Package(name="jq", version="1.7.1-3"), Package(name="curl")))
    assert cmds == [
        "apt-get -o DPkg::Lock::Timeout=120 update -q",
        "DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=120 -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold install -y -q --allow-downgrades -- tree jq=1.7.1-3 curl",
    ]
    no_rec = Package.fix_group(group(Package(name="tree", install_recommends=False, refresh=False)))
    assert no_rec == ["DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=120 -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold install -y -q --no-install-recommends -- tree"]


@pytest.mark.parametrize("manager,query,install,remove", [
    ("pacman", "tree 1-1", ["pacman -S --noconfirm --needed -- tree"], ["pacman -R --noconfirm -- tree"]),
    ("dnf", "1-1", ["dnf makecache -q", "dnf install -y -q -- tree"], ["dnf remove -y -q -- tree"]),
    ("zypper", "1-1", ["zypper --non-interactive refresh", "zypper --non-interactive install -- tree"],
     ["zypper --non-interactive remove -- tree"]),
    ("apk", "tree-1-r0", ["apk update -q", "apk add -q tree"], ["apk del -q tree"]),
])
def test_other_managers(manager, query, install, remove):
    assert Package.fix_group(group(Package(name="tree"), manager=manager)) == install
    assert Package.fix_group(group(Package(name="tree", state="absent"), manager=manager, query=query)) == remove


def test_purge_and_version_syntax():
    assert Package.fix_group(group(Package(name="tree", state="absent", purge=True), query="ii |1")) == [
        "DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=120 -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold purge -y -q -- tree"]
    assert Package.fix_group(group(Package(name="tree", state="absent", purge=True), manager="pacman", query="tree 1-1")) == [
        "pacman -Rns --noconfirm -- tree"]
    assert Package.fix_group(group(Package(name="tree", version="2.1", refresh=False), manager="dnf")) == ["dnf install -y -q -- tree-2.1"]
    assert Package.fix_group(group(Package(name="tree", version="2.1", refresh=False), manager="apk")) == ["apk add -q tree=2.1"]
    assert Package.fix_group(group(Package(name="tree", full_upgrade=True), manager="pacman")) == [
        "pacman -Syu --noconfirm --needed -- tree"]


def test_group_key_and_name_validation():
    assert Package(name="a").group_key() == Package(name="b").group_key() != Package(name="c", state="absent").group_key()
    for bad in ("-rf", "a b", "a;b", ""):
        with pytest.raises(ValueError):
            Package(name=bad)
    assert Package(name="tree", version="2.0").label == "tree 2.0"


def test_aur_package_installs_with_yay_as_build_user():
    p = Package(name="yay-test", aur=True)
    c = cur(p, "pacman", "")
    cmds = p.fix(p.compare(c), c)
    assert cmds[-1] == ("runuser -u bastet-aur -- yay -S --noconfirm --needed --answerdiff None --answerclean None "
                        "-- yay-test")


def test_aur_needs_pacman():
    with pytest.raises(Unsupported, match="AUR packages need pacman"):
        cur(Package(name="x", aur=True), "apt-get", "")


def test_aur_and_repo_packages_never_share_a_command():
    assert Package(name="a", aur=True).group_key() != Package(name="a").group_key()


# every knob works where the manager can do it, and is Unsupported where it can't

def pcur(pkg, manager, query=""):
    return pkg.current({"manager": ok(manager), "query": ok(query)})


def cmds(*pkgs, manager="apt-get", query=""):
    return Package.fix_group([(p, p.compare(pcur(p, manager, query)), pcur(p, manager, query)) for p in pkgs])


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


def test_held_package_is_installed():
    assert pcur(Package(name="tree"), "apt-get", "hi |1.0-1")["state"] == "present"


def test_rpm_version_matching():
    p = Package(name="foo", version="1.2.3")
    assert p.compare(pcur(p, "dnf", "(none):1.2.3-4.fc40")) == []
    assert p.compare(pcur(p, "dnf", "2:1.2.3-4.fc40")) == []
    assert [c.field for c in Package(name="foo", version="1.2.4").compare(pcur(p, "dnf", "(none):1.2.3-4.fc40"))] == ["version"]
    k = Package(name="kernel", version="6.2")
    assert k.compare(pcur(k, "dnf", "(none):6.1-1\n(none):6.2-1")) == []
    assert pcur(Package(name="foo"), "dnf", "(none):1.2.3-4.fc40")["version"] == "1.2.3-4.fc40"


def test_pins_allow_downgrades_and_conffiles_kept():
    apt = cmds(Package(name="tree", version="1.0", refresh=False))
    assert apt == ["DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=120 -o Dpkg::Options::=--force-confdef "
                   "-o Dpkg::Options::=--force-confold install -y -q --allow-downgrades -- tree=1.0"]
    assert "--oldpackage" in cmds(Package(name="tree", version="1.0", refresh=False), manager="zypper")[-1]


def test_dpkg_options_stay_one_argument():
    last = cmds(Package(name="tree", dpkg_options=("--x; echo hi",)))[-1]
    assert "'Dpkg::Options::=--x; echo hi'" in last
    assert "-o Dpkg::Options::=--force-confnew" in cmds(Package(name="tree", dpkg_options=("--force-confnew",)))[-1]
