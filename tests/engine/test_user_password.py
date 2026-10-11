import pytest

from bastet.core.shell import ProbeResult
from bastet.engine import passwords
from bastet.engine.model import FieldChange
from bastet.engine.users import User

PLAIN = "not-a-real-password"


def ok(text):
    return ProbeResult(0, text)


def state(shadow_hash, login_defs="ENCRYPT_METHOD SHA512"):
    return {"passwd": ok("alice:x:1000:1000:Alice:/home/alice:/bin/bash"), "groups": ok("alice|alice"),
            "shadow": ok(f"alice:{shadow_hash}:19000:0:99999:7:::"), "tools": ok("/usr/sbin/useradd"),
            "login_defs": ok(login_defs)}


def test_password_and_password_hash_together_are_refused():
    with pytest.raises(ValueError, match="password or password_hash, not both"):
        User(name="root", password="a", password_hash="$6$s$h")


@pytest.mark.parametrize("scheme", ["sha512", "sha256", "yescrypt"])
def test_the_right_password_in_any_scheme_is_no_change(scheme):
    u = User(name="alice", password=PLAIN)
    assert u.compare(u.current(state(passwords.hash(PLAIN, scheme)))) == []


@pytest.mark.parametrize("stored", [None, "", "!", "*"])
def test_other_text_or_no_usable_hash_is_a_hidden_change(stored):
    u = User(name="alice", password=PLAIN)
    have = passwords.hash("other text") if stored is None else stored
    assert u.compare(u.current(state(have))) == [FieldChange("password", "(hidden)", "(new)")]


def test_on_create_leaves_an_existing_password_alone():
    u = User(name="alice", password=PLAIN, update_password="on_create")
    assert u.compare(u.current(state(passwords.hash("other text")))) == []


@pytest.mark.parametrize("defs,prefix", [("ENCRYPT_METHOD YESCRYPT", "$y$"), ("ENCRYPT_METHOD SHA512", "$6$"), ("", "$6$")])
def test_fix_writes_the_hosts_own_scheme_and_never_the_plain_text(defs, prefix):
    u = User(name="alice", password=PLAIN)
    cur = u.current(state("!", defs))
    changes = u.compare(cur)
    cmds = u.fix(changes, cur)
    [pw] = [c for c in cmds if "chpasswd -e" in c]
    assert prefix in pw and not any(PLAIN in c for c in cmds)
    assert all(PLAIN not in f"{c.field} {c.before} {c.after}" for c in changes)


def test_a_new_account_gets_a_hashed_password():
    u = User(name="alice", password=PLAIN)
    cur = {"exists": False}
    changes = u.compare(cur)
    cmds = u.fix(changes, cur)
    assert any("chpasswd -e" in c and "$6$" in c for c in cmds) and not any(PLAIN in c for c in cmds)
    assert all(PLAIN not in str(c) for c in changes)


def test_a_missing_account_still_reads_the_scheme():
    u = User(name="alice", password=PLAIN)
    results = state("x", "ENCRYPT_METHOD YESCRYPT")
    results["passwd"] = ok("")
    cur = u.current(results)
    assert cur["scheme"] == "yescrypt"
    assert any("$y$" in c for c in u.fix(u.compare(cur), cur))
