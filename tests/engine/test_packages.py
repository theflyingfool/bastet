import pytest

from bastet.core.collect import ProbeResult
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
        "DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=120 install -y -q -- tree jq=1.7.1-3 curl",
    ]
    no_rec = Package.fix_group(group(Package(name="tree", install_recommends=False, refresh=False)))
    assert no_rec == ["DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=120 install -y -q --no-install-recommends -- tree"]


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
        "DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=120 purge -y -q -- tree"]
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
