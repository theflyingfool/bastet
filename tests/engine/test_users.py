import pytest

from bastet.core.collect import ProbeResult
from bastet.engine.model import Unsupported
from bastet.engine.users import Group, User

HASH = "$6$bastetsalt$" + "x" * 86


def ok(text):
    return ProbeResult(0, text)


def user_state(passwd="nick:x:1000:1000:Nick:/home/nick:/bin/bash", groups="nick|nick wheel media",
               shadow=f"nick:{HASH}:19000:0:99999:7:::", tools="/usr/sbin/useradd"):
    return {"passwd": ok(passwd), "groups": ok(groups), "shadow": ok(shadow), "tools": ok(tools)}


def test_current_user():
    c = User(name="nick").current(user_state())
    assert c == {"exists": True, "uid": "1000", "group": "nick", "groups": ("media", "wheel"), "comment": "Nick",
                 "home": "/home/nick", "shell": "/bin/bash", "password": HASH, "locked": False, "expires": "never",
                 "min_days": "0", "max_days": "99999", "warn_days": "7", "inactive_days": "(absent)"}
    locked = User(name="nick").current(user_state(shadow=f"nick:!{HASH}:19000:0:99999:7::20089:"))
    assert locked["locked"] is True and locked["password"] == HASH and locked["expires"] == "2025-01-01"


def test_new_user_command():
    u = User(name="nick", uid=2000, group="users", groups=("media", "wheel"), comment="Nick", shell="/bin/bash",
             password_hash=HASH, locked=False, expires="2030-01-01")
    cur = u.current(user_state(passwd="", groups="|", shadow=""))
    assert cur["exists"] is False
    cmds = u.fix(u.compare(cur), cur)
    assert cmds[0] == "useradd -u 2000 -g users -G media,wheel -c Nick -s /bin/bash -e 2030-01-01 -m nick"
    assert cmds[1] == f"printf '%s:%s\\n' nick '{HASH}' | chpasswd -e"
    assert "usermod -U nick" in cmds


def test_groups_append_vs_exact():
    base = user_state(groups="nick|nick wheel media")
    add = User(name="nick", groups=("media",))
    assert add.compare(add.current(base)) == []
    more = User(name="nick", groups=("docker",))
    changes = more.compare(more.current(base))
    assert [(c.field, c.before, c.after) for c in changes] == [("groups", "media, wheel", "docker, media, wheel")]
    assert more.fix(changes, more.current(base)) == ["usermod -a -G docker nick"]
    exact = User(name="nick", groups=("docker",), append=False)
    changes = exact.compare(exact.current(base))
    assert [(c.before, c.after) for c in changes] == [("media, wheel", "docker")]
    assert exact.fix(changes, exact.current(base)) == ["usermod -G docker nick"]


def test_password_hidden_and_not_in_argv():
    u = User(name="nick", password_hash="$6$new$" + "y" * 86)
    cur = u.current(user_state())
    [change] = u.compare(cur)
    assert (change.field, change.before, change.after) == ("password", "(hidden)", "(new)")
    [cmd] = u.fix([change], cur)
    assert cmd.startswith("printf '%s:%s\\n' nick ") and cmd.endswith("| chpasswd -e")


def test_modify_fields_and_expiry_never():
    u = User(name="nick", shell="/bin/zsh", comment="Nick K", home="/srv/nick", move_home=True, expires="never", locked=True)
    cur = u.current(user_state(shadow=f"nick:{HASH}:19000:0:99999:7::20089:"))
    cmds = u.fix(u.compare(cur), cur)
    assert cmds == ["usermod -c 'Nick K' -d /srv/nick -m -s /bin/zsh -e '' nick", "usermod -L nick"]


def test_no_useradd_is_unsupported_and_names_validated():
    with pytest.raises(Unsupported) as e:
        User(name="nick").current(user_state(tools=""))
    assert "shadow" in str(e.value)
    for bad in ("-x", "a b", "ROOT;", ""):
        with pytest.raises(ValueError):
            User(name=bad)


def test_group():
    g = Group(name="media", gid=2001, members=("nick", "jellyfin"))
    absent = g.current({"group": ok("")})
    assert absent["exists"] is False
    assert g.fix(g.compare(absent), absent) == ["groupadd -g 2001 media", "gpasswd -M jellyfin,nick media"]
    present = g.current({"group": ok("media:x:2001:nick")})
    assert [(c.field, c.before, c.after) for c in g.compare(present)] == [("members", "nick", "jellyfin, nick")]
    assert Group(name="media").compare(present) == []
    assert Group(name="svc", system=True).fix([], {"exists": False}) == ["groupadd -r svc"]


def test_useradd_looked_up_as_root():
    """/usr/sbin isn't on a normal user's PATH; sudo's secure_path has it."""
    assert {r.name: r.root for r in User(name="nick").reads()}["tools"] is True
