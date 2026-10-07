import os
import stat
from pathlib import Path

import pytest

from bastet.core.shell import ProbeResult
from bastet.core.remote import LocalRunner
from bastet.engine.model import ABSENT
from bastet.engine.run import Batch, run_host
from bastet.engine.users import AuthorizedKey, sudoer

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleExampleExampleExampleExampleExample admin@laptop"


def key_state(path="/home/alice/.ssh/authorized_keys", kind="file", content="", mode="600"):
    import base64
    if kind == "absent":
        body = f"{path}\nabsent"
    else:
        body = f"{path}\nfile\nnick alice {mode} 1000 1000\n{base64.b64encode(content.encode()).decode()}"
    return {"keys": ProbeResult(0, body)}


def test_key_appended_replaced_and_compliant():
    k = AuthorizedKey(user="alice", key=KEY, options='from="10.0.10.0/24"')
    line = f'from="10.0.10.0/24" {KEY}'
    assert k.wanted("") == line + "\n"
    assert k.wanted("ssh-rsa AAAAother x\n") == f"ssh-rsa AAAAother x\n{line}\n"
    assert k.wanted(f"{KEY}\nssh-rsa AAAAother x\n") == f"{line}\nssh-rsa AAAAother x\n"
    cur = k.current(key_state(content=line + "\n"))
    assert k.compare(cur) == []
    assert [c.field for c in k.compare(k.current(key_state(content=line + "\n", mode="644")))] == ["mode"]


def test_key_for_user_not_created_yet():
    k = AuthorizedKey(user="alice", key=KEY)
    cur = k.current({"keys": ProbeResult(0, "nouser")})
    assert cur["content"] == ABSENT and [c.field for c in k.compare(cur)] == ["key"]
    script = "\n".join(k.fix(k.compare(cur), cur))
    assert "n=alice" in script and 'getent passwd "$n"' in script and "chmod 700" in script and "chmod 600" in script
    assert 'chown "$n:$g"' in script


def test_key_identity_and_label():
    k = AuthorizedKey(user="alice", key=KEY)
    assert k.identity == "authkey:alice:AAAAC3NzaC1lZDI1NTE5AAAAIExampleExampleExampleExampleExampleExample"
    assert k.label == "alice key admin@laptop"
    with pytest.raises(ValueError):
        AuthorizedKey(user="alice", key="garbage")


def test_sudoer_rendering():
    f = sudoer("bastet", user="bastet", nopasswd=True)
    assert f.path == "/etc/sudoers.d/bastet" and f.mode == "0440" and f.owner == "root" and f.validate == "visudo -cf %s"
    assert f.content == "# Managed by Bastet\nbastet ALL=(ALL) NOPASSWD: ALL\n"
    g = sudoer("ops", group="wheel", commands=("/usr/bin/systemctl restart *", "/usr/bin/journalctl"), runas="root",
               setenv=True, defaults=("!requiretty",), rules=("Cmnd_Alias PKG = /usr/bin/apt-get",))
    assert g.content == ("# Managed by Bastet\nDefaults:%wheel !requiretty\n"
                         "%wheel ALL=(root) SETENV: /usr/bin/systemctl restart *, /usr/bin/journalctl\n"
                         "Cmnd_Alias PKG = /usr/bin/apt-get\n")
    for bad in ("a.b", "a~", "../x", ""):
        with pytest.raises(ValueError):
            sudoer(bad, user="x")


def test_custom_key_path_keeps_directory():
    k = AuthorizedKey(user="alice", key="ssh-ed25519 AAAAbody admin@laptop", path="/etc/ssh/authorized_keys/alice")
    cur = k.current({"keys": ProbeResult(0, "nouser")})
    script = "\n".join(k.fix(k.compare(cur), cur))
    assert "chmod 700" not in script and "chmod 600" in script


def test_key_can_be_revoked():
    k = AuthorizedKey(user="alice", key="ssh-ed25519 AAAAbody admin@laptop", state="absent")
    assert k.wanted("ssh-ed25519 AAAAbody admin@laptop\nssh-rsa AAAAother x\n") == "ssh-rsa AAAAother x\n"
    assert k.wanted("ssh-rsa AAAAother x\n") == "ssh-rsa AAAAother x\n"


def test_sudoer_rejected_rule_never_lands(tmp_path, monkeypatch):
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "visudo").write_text("#!/bin/sh\ngrep -q 'ALL=' \"$2\" && ! grep -q BROKEN \"$2\"\n")
    os.chmod(fake / "visudo", 0o755)
    monkeypatch.setenv("PATH", f"{fake}:{os.environ['PATH']}")
    target = tmp_path / "sudoers.d" / "bastet"
    target.parent.mkdir()
    target.write_text("bastet ALL=(ALL) ALL\n")
    bad = sudoer("bastet", rules=("BROKEN rule",))
    local = type(bad)(**{**bad.__dict__, "path": str(target), "owner": None, "group": None, "root": False})
    run = run_host(LocalRunner(), "h", [Batch("t", [local])], apply=True)
    assert run.items[0].status == "failed" and target.read_text() == "bastet ALL=(ALL) ALL\n"
    assert sorted(p.name for p in target.parent.iterdir()) == ["bastet"]
