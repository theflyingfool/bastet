from pathlib import Path

from bastet.core.shell import ProbeResult
from bastet.engine.users import UnaccountedUsers, User
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import check_values, load_roles, with_defaults
from bastet.roles.resolve import Applied

PASSWD = ("root:x:0:0:root:/root:/bin/bash\n"
          "bastet:x:1000:1000::/home/bastet:/bin/bash\n"
          "nobody:x:65534:65534:Kernel Overflow User:/:/usr/bin/nologin\n"
          "daemon:x:1:1::/:/usr/bin/nologin\n"
          "alice:x:1001:1001::/home/alice:/bin/bash\n"
          "bob:x:1002:1002::/home/bob:/bin/zsh\n"
          "broken-line\n"
          "odd:x:abc:1::/:/bin/sh\n")


def ok(text):
    return ProbeResult(0, text)


def current(resource, defs=""):
    return resource.current({"passwd": ok(PASSWD), "defs": ok(defs)})["unaccounted"]


def host():
    return HostInfo(name="vps1", type="vps", data={"os": "Arch Linux"}, root=Path("/x"), lab={})


def test_everything_not_tracked_or_allowed_is_reported_with_uid_and_shell():
    r = UnaccountedUsers(tracked=("alice",), allowed=("daemon",))
    assert current(r) == ("root (uid 0, /bin/bash)", "bastet (uid 1000, /bin/bash)", "bob (uid 1002, /bin/zsh)",
                          "nobody (uid 65534, /usr/bin/nologin)")


def test_root_and_bastet_show_up_until_tracked_or_allowed_and_a_broken_line_is_skipped():
    names = " ".join(current(UnaccountedUsers()))
    assert "root (uid 0" in names and "bastet (uid 1000" in names and "broken" not in names and "odd" not in names
    quiet = " ".join(current(UnaccountedUsers(allowed=("root",), tracked=("bastet",))))
    assert "root" not in quiet and "bastet" not in quiet


def test_system_accounts_can_be_left_out_using_login_defs_or_the_defaults():
    r = UnaccountedUsers(system_accounts=False)
    both = ("bastet (uid 1000, /bin/bash)", "alice (uid 1001, /bin/bash)", "bob (uid 1002, /bin/zsh)")
    assert current(r, "UID_MIN 1000\nUID_MAX 60000\n") == both
    assert current(r) == both


def test_it_is_a_report_and_never_a_fix():
    r = UnaccountedUsers()
    assert r.report_only() is True and r.compare({"unaccounted": ()}) == []
    [change] = r.compare({"unaccounted": ("bob (uid 1002, /bin/zsh)",)})
    assert (change.field, change.before, change.after) == ("unaccounted", "1 accounts", "none")
    assert r.fix([change], {"unaccounted": ("x",)}) == []


def test_diff_text_lists_sixty_then_counts_the_rest():
    r = UnaccountedUsers()
    assert r.diff_text({"unaccounted": ()}) is None
    lines = r.diff_text({"unaccounted": tuple(f"u{i}" for i in range(63))}).splitlines()
    assert len(lines) == 61 and lines[-1] == "… 3 more"


def test_users_from_every_role_are_tracked_and_the_options_apply():
    role = load_roles()["users"]
    values = with_defaults(role, check_values(role, {"users": {"alice": {}}, "allowed": ["daemon"], "report_system_accounts": False}, "users"))
    batches = batches_for([Applied(role, values)], host())
    [report] = [r for b in batches for r in b.resources if isinstance(r, UnaccountedUsers)]
    assert "alice" in report.tracked and report.allowed == ("daemon",) and report.system_accounts is False
    assert any(isinstance(r, User) and r.name == "alice" for b in batches for r in b.resources)


def test_report_unaccounted_false_adds_no_report():
    role = load_roles()["users"]
    values = with_defaults(role, check_values(role, {"report_unaccounted": False}, "users"))
    assert not [r for b in batches_for([Applied(role, values)], host()) for r in b.resources if isinstance(r, UnaccountedUsers)]
