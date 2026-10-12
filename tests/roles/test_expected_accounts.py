from pathlib import Path

import pytest

from bastet.core.errors import BastetError
from bastet.core.shell import ProbeResult
from bastet.engine.users import UnaccountedUsers, User
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import check_values, load_roles, with_defaults
from bastet.roles.resolve import Applied

ROLES = load_roles()
ARCH_PASSWD = ("root:x:0:0::/root:/bin/bash\nbastet:x:1000:1000::/home/bastet:/bin/bash\n"
               "bin:x:1:1::/:/usr/bin/nologin\ndaemon:x:2:2::/:/usr/bin/nologin\n"
               "nobody:x:65534:65534::/:/usr/bin/nologin\ndbus:x:81:81::/:/usr/bin/nologin\n"
               "systemd-network:x:980:980::/:/usr/bin/nologin\nalpm:x:970:970::/:/usr/bin/nologin\n"
               "alice:x:1001:1001::/home/alice:/bin/bash\n")


def host(os="Arch Linux"):
    data = {"os": os} if os else {}
    return HostInfo(name="vps1", type="vps", data=data, root=Path("/nonexistent"), lab={})


def applied(name, values=None):
    role = ROLES[name]
    return Applied(role, with_defaults(role, check_values(role, values or {}, name)))


def build(roles, h=None):
    return batches_for(roles, h or host())


def of(batches, kind):
    return [r for b in batches for r in b.resources if isinstance(r, kind)]


def report_of(batches):
    [report] = of(batches, UnaccountedUsers)
    return report


def listed(report):
    out = report.current({"passwd": ProbeResult(0, ARCH_PASSWD), "defs": ProbeResult(0, "")})["unaccounted"]
    return [line.split()[0] for line in out]


def test_defaults_alone_build_root_and_bastet_and_track_both():
    batches = build([applied("users")])
    users = {u.name: u for u in of(batches, User)}
    assert set(users) == {"root", "bastet"} and users["bastet"].system is True
    assert {"root", "bastet"} <= set(report_of(batches).tracked)


def test_listing_another_user_keeps_root_and_bastet():
    names = {u.name for u in of(build([applied("users", {"users": {"alice": {}}})]), User)}
    assert names == {"root", "bastet", "alice"}


def test_a_root_entry_merges_with_the_default_root():
    users = of(build([applied("users", {"users": {"root": {"password": "x"}}})]), User)
    [root] = [u for u in users if u.name == "root"]
    assert root.password == "x" and {u.name for u in users} == {"root", "bastet"}


def test_the_lockout_guard_still_applies():
    with pytest.raises(BastetError, match="lock Bastet out"):
        build([applied("users", {"users": {"bastet": {"locked": True}}})])


def test_an_arch_host_expects_the_os_and_applied_role_accounts():
    batches = build([applied("users"), applied("systemd"), applied("pacman")])
    report = report_of(batches)
    assert {"bin", "nobody", "dbus", "alpm", "systemd-network", "systemd-timesync"} <= set(report.tracked)
    assert listed(report) == ["alice"]


def test_roles_not_applied_hide_nothing_of_theirs():
    report = report_of(build([applied("users")]))
    assert "alpm" in listed(report) and "systemd-network" in listed(report)


def test_a_debian_host_does_not_hide_alpm():
    report = report_of(build([applied("users")], host("Debian GNU/Linux 13 (trixie)")))
    assert "alpm" in listed(report) and "bin" in listed(report)


def test_an_unknown_os_tracks_only_the_managed_users():
    assert set(report_of(build([applied("users")], host(None))).tracked) == {"root", "bastet"}


def test_allowed_still_hides():
    report = report_of(build([applied("users", {"allowed": ["alice"]})]))
    assert "alice" not in listed(report)


PASSWD_STATE = {"passwd": ProbeResult(0, "root:x:0:0::/root:/bin/bash"), "groups": ProbeResult(0, "root|root"),
                "shadow": ProbeResult(0, "root:$6$salt$hash:19000:0:99999:7:::"), "tools": ProbeResult(0, "/usr/sbin/useradd")}
BASTET_STATE = {"passwd": ProbeResult(0, "bastet:x:1000:1000::/home/bastet:/bin/bash"),
                "groups": ProbeResult(0, "bastet|bastet wheel"), "shadow": ProbeResult(0, "bastet:!:19000:0:99999:7:::"),
                "tools": ProbeResult(0, "/usr/sbin/useradd")}


def test_a_secret_password_hides_only_the_password_not_the_rest_of_the_users_role():
    role = ROLES["users"]
    values = with_defaults(role, check_values(role, {
        "users": {"root": {"password": "hunter2"},
                  "alice": {"keys": ["ssh-ed25519 AAAAC3Nza...example alice@laptop"], "sudo": {"nopasswd": True}}},
        "groups": {"media": {"gid": 2001}}}, "users"))
    batches = build([Applied(role, values, secret=True, secret_options=frozenset({"users"}))])
    resources = [r for b in batches for r in b.resources]
    assert {type(r).__name__ for r in resources} >= {"User", "Group", "AuthorizedKey", "File", "UnaccountedUsers"}
    assert [r.label for r in resources if r.secret] == []
    [root] = [u for u in of(batches, User) if u.name == "root"]
    text = " ".join(str(c.before) + str(c.after) for c in root.compare(root.current(PASSWD_STATE)))
    assert "hunter2" not in text and "(new)" in text


def test_the_default_root_and_bastet_entries_compare_clean_on_a_normal_host():
    users = {u.name: u for u in of(build([applied("users")]), User)}
    assert users["root"].compare(users["root"].current(PASSWD_STATE)) == []
    assert users["bastet"].compare(users["bastet"].current(BASTET_STATE)) == []
