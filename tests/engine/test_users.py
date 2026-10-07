import pytest

from bastet.core.shell import ProbeResult
from bastet.engine.model import Unsupported
from bastet.engine.users import Group, User

HASH = "$6$bastetsalt$" + "x" * 86


def ok(text):
    return ProbeResult(0, text)


def user_state(passwd="alice:x:1000:1000:Alice:/home/alice:/bin/bash", groups="alice|alice wheel media",
               shadow=f"alice:{HASH}:19000:0:99999:7:::", tools="/usr/sbin/useradd"):
    return {"passwd": ok(passwd), "groups": ok(groups), "shadow": ok(shadow), "tools": ok(tools)}


def test_current_user():
    c = User(name="alice").current(user_state())
    assert c == {"exists": True, "uid": "1000", "group": "alice", "groups": ("media", "wheel"), "comment": "Alice",
                 "home": "/home/alice", "shell": "/bin/bash", "password": HASH, "locked": False, "expires": "never",
                 "min_days": "0", "max_days": "99999", "warn_days": "7", "inactive_days": "(absent)"}
    locked = User(name="alice").current(user_state(shadow=f"alice:!{HASH}:19000:0:99999:7::20089:"))
    assert locked["locked"] is True and locked["password"] == HASH and locked["expires"] == "2025-01-01"


def test_new_user_command():
    u = User(name="alice", uid=2000, group="users", groups=("media", "wheel"), comment="Alice", shell="/bin/bash",
             password_hash=HASH, locked=False, expires="2030-01-01")
    cur = u.current(user_state(passwd="", groups="|", shadow=""))
    assert cur["exists"] is False
    cmds = u.fix(u.compare(cur), cur)
    assert cmds[0] == "useradd -u 2000 -g users -G media,wheel -c Alice -s /bin/bash -e 2030-01-01 -m alice"
    assert cmds[1] == f"printf '%s:%s\\n' alice '{HASH}' | chpasswd -e"
    assert "usermod -U alice" in cmds


def test_groups_append_vs_exact():
    base = user_state(groups="alice|alice wheel media")
    add = User(name="alice", groups=("media",))
    assert add.compare(add.current(base)) == []
    more = User(name="alice", groups=("docker",))
    changes = more.compare(more.current(base))
    assert [(c.field, c.before, c.after) for c in changes] == [("groups", "media, wheel", "docker, media, wheel")]
    assert more.fix(changes, more.current(base)) == ["usermod -a -G docker alice"]
    exact = User(name="alice", groups=("docker",), append=False)
    changes = exact.compare(exact.current(base))
    assert [(c.before, c.after) for c in changes] == [("media, wheel", "docker")]
    assert exact.fix(changes, exact.current(base)) == ["usermod -G docker alice"]


def test_password_hidden_and_not_in_argv():
    u = User(name="alice", password_hash="$6$new$" + "y" * 86)
    cur = u.current(user_state())
    [change] = u.compare(cur)
    assert (change.field, change.before, change.after) == ("password", "(hidden)", "(new)")
    [cmd] = u.fix([change], cur)
    assert cmd.startswith("printf '%s:%s\\n' alice ") and cmd.endswith("| chpasswd -e")


def test_modify_fields_and_expiry_never():
    u = User(name="alice", shell="/bin/zsh", comment="Alice K", home="/srv/alice", move_home=True, expires="never", locked=True)
    cur = u.current(user_state(shadow=f"alice:{HASH}:19000:0:99999:7::20089:"))
    cmds = u.fix(u.compare(cur), cur)
    assert cmds == ["usermod -c 'Alice K' -d /srv/alice -m -s /bin/zsh -e '' alice", "usermod -L alice"]


def test_no_useradd_is_unsupported_and_names_validated():
    with pytest.raises(Unsupported) as e:
        User(name="alice").current(user_state(tools=""))
    assert "shadow" in str(e.value)
    for bad in ("-x", "a b", "ROOT;", ""):
        with pytest.raises(ValueError):
            User(name=bad)


def test_group():
    g = Group(name="media", gid=2001, members=("alice", "jellyfin"))
    absent = g.current({"group": ok("")})
    assert absent["exists"] is False
    assert g.fix(g.compare(absent), absent) == ["groupadd -g 2001 media", "gpasswd -M alice,jellyfin media"]
    present = g.current({"group": ok("media:x:2001:alice")})
    assert [(c.field, c.before, c.after) for c in g.compare(present)] == [("members", "alice", "alice, jellyfin")]
    assert Group(name="media").compare(present) == []
    assert Group(name="svc", system=True).fix([], {"exists": False}) == ["groupadd -r svc"]


def test_useradd_looked_up_as_root():
    """/usr/sbin isn't on a normal user's PATH; sudo's secure_path has it."""
    assert {r.name: r.root for r in User(name="alice").reads()}["tools"] is True


# a new password never unlocks a locked account; password ageing and creation knobs; group member append

def password_state(shadow):
    return {"passwd": ok("alice:x:1000:1000:Alice:/home/alice:/bin/bash"), "groups": ok("alice|alice"),
            "shadow": ok(shadow), "tools": ok("/usr/sbin/useradd")}


def test_new_password_keeps_lock():
    for locked in (True, None):
        u = User(name="alice", password_hash="$6$new$" + "y" * 86, locked=locked)
        cur = u.current(password_state(f"alice:!{HASH}:19000:0:99999:7:::"))
        out = u.fix(u.compare(cur), cur)
        assert out[-1] == "usermod -L alice"


def test_password_only_on_create():
    u = User(name="alice", password_hash="$6$new$" + "y" * 86, update_password="on_create")
    assert u.compare(u.current(password_state(f"alice:{HASH}:19000:0:99999:7:::"))) == []


def test_password_ageing_and_creation_knobs():
    u = User(name="alice", max_days=90, min_days=1, warn_days=14, inactive_days=30)
    cur = u.current(password_state(f"alice:{HASH}:19000:0:99999:7:::"))
    assert [c.field for c in u.compare(cur)] == ["max_days", "min_days", "warn_days", "inactive_days"]
    assert u.fix(u.compare(cur), cur) == ["chage -M 90 -m 1 -W 14 -I 30 alice"]
    new = User(name="svc", uid=0, non_unique=True, skeleton="/etc/skel-svc")
    absent = new.current({"passwd": ok(""), "groups": ok("|"), "shadow": ok(""), "tools": ok("/usr/sbin/useradd")})
    assert new.fix(new.compare(absent), absent)[0] == "useradd -u 0 -o -k /etc/skel-svc -m svc"


def test_group_members_append():
    g = Group(name="media", members=("jellyfin",), append_members=True)
    present = g.current({"group": ok("media:x:2001:alice")})
    assert g.fix(g.compare(present), present) == ["gpasswd -a jellyfin media"]
    assert Group(name="media", members=("alice",), append_members=True).compare(present) == []
