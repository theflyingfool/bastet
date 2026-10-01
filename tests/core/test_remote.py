import subprocess
from pathlib import Path

import pytest

import bastet.core.remote as remote
from bastet.core.errors import AuthFailed, BastetError, Unreachable
from bastet.core.remote import LocalRunner, SshRunner, SshTarget, ssh_args

T = SshTarget(address="203.0.113.10", user="bastet", key=Path("/k/id"), known_hosts=Path("/t/kh"))


def test_local_runner_runs_script():
    r = LocalRunner().run("echo hi\nexit 3\n")
    assert r.stdout == "hi\n" and r.returncode == 3


def test_ssh_args_batch_with_key_and_known_hosts():
    args = ssh_args(T)
    assert args[0] == "ssh" and args[-1] == "bastet@203.0.113.10"
    joined = " ".join(args)
    assert "BatchMode=yes" in joined and "IdentitiesOnly=yes" in joined and "-i /k/id" in joined
    assert "UserKnownHostsFile=/t/kh" in joined and "StrictHostKeyChecking=yes" in joined
    assert "-t" not in args


def test_ssh_args_interactive_has_tty_and_no_batch():
    args = ssh_args(SshTarget("h", "nick", None, Path("/t/kh")), interactive=True)
    assert "-t" in args and "BatchMode=yes" not in " ".join(args) and "-i" not in args


def fake_run(returncode, stderr="", stdout=""):
    def run(*a, **k):
        return subprocess.CompletedProcess(a[0], returncode, stdout, stderr)
    return run


@pytest.mark.parametrize(
    "stderr,exc",
    [
        ("bastet@h: Permission denied (publickey).", AuthFailed),
        ("Host key verification failed.", BastetError),
        ("ssh: connect to host h port 22: Connection refused", Unreachable),
    ],
)
def test_ssh_errors_are_classified(monkeypatch, stderr, exc):
    monkeypatch.setattr(remote.subprocess, "run", fake_run(255, stderr))
    with pytest.raises(exc):
        SshRunner(T).run("echo hi")


def test_ssh_timeout_is_unreachable(monkeypatch):
    def slow(*a, **k):
        raise subprocess.TimeoutExpired(a[0], 1)
    monkeypatch.setattr(remote.subprocess, "run", slow)
    with pytest.raises(Unreachable):
        SshRunner(T).run("echo hi")


def test_ssh_success(monkeypatch):
    monkeypatch.setattr(remote.subprocess, "run", fake_run(0, stdout="ok\n"))
    assert SshRunner(T).run("echo ok").stdout == "ok\n"
