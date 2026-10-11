import shutil

import pytest

from bastet.core.shell import ProbeResult
from bastet.engine import passwords
from bastet.engine.model import FieldChange
from bastet.engine.users import User

needs_openssl = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not installed")
PLAIN = "not-a-real-password"


def ok(text):
    return ProbeResult(0, text)


def state(shadow_hash):
    return {"passwd": ok("alice:x:1000:1000:Alice:/home/alice:/bin/bash"), "groups": ok("alice|alice"),
            "shadow": ok(f"alice:{shadow_hash}:19000:0:99999:7:::"), "tools": ok("/usr/sbin/useradd")}


def test_password_and_password_hash_together_are_refused():
    with pytest.raises(ValueError, match="password or password_hash, not both"):
        User(name="root", password="a", password_hash="$6$s$h")


@needs_openssl
def test_same_plain_text_with_any_salt_is_no_change():
    u = User(name="alice", password=PLAIN)
    assert u.compare(u.current(state(passwords.hash(PLAIN, "somesalt")))) == []
    assert u.compare(u.current(state(passwords.hash(PLAIN, passwords.new_salt())))) == []


@needs_openssl
@pytest.mark.parametrize("stored", [None, "", "!", "*"])
def test_other_text_or_no_usable_hash_is_a_hidden_change(stored):
    u = User(name="alice", password=PLAIN)
    have = passwords.hash("other text", "somesalt") if stored is None else stored
    assert u.compare(u.current(state(have))) == [FieldChange("password", "(hidden)", "(new)")]


@needs_openssl
def test_on_create_leaves_an_existing_password_alone():
    u = User(name="alice", password=PLAIN, update_password="on_create")
    assert u.compare(u.current(state(passwords.hash("other text", "somesalt")))) == []


@needs_openssl
def test_fix_sends_only_a_hash_and_the_report_hides_the_text():
    u = User(name="alice", password=PLAIN)
    cur = u.current(state("!"))
    changes = u.compare(cur)
    cmds = u.fix(changes, cur)
    [pw] = [c for c in cmds if "chpasswd -e" in c]
    assert "$6$" in pw and not any(PLAIN in c for c in cmds)
    assert all(PLAIN not in f"{c.field} {c.before} {c.after}" for c in changes)


@needs_openssl
def test_a_new_account_gets_a_hashed_password():
    u = User(name="alice", password=PLAIN)
    changes = u.compare({"exists": False})
    cmds = u.fix(changes, {"exists": False})
    assert any("chpasswd -e" in c and "$6$" in c for c in cmds) and not any(PLAIN in c for c in cmds)
    assert all(PLAIN not in str(c) for c in changes)
