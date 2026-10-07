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
    args = ssh_args(SshTarget("h", "alice", None, Path("/t/kh")), interactive=True)
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


from bastet.core.remote import close_master, control_path  # noqa: E402


def test_ssh_args_keepalive_count_and_no_multiplexing_by_default():
    joined = " ".join(ssh_args(T))
    assert "ServerAliveCountMax=3" in joined and "ControlMaster" not in joined


def test_ssh_args_multiplexed():
    t = SshTarget("203.0.113.10", "bastet", Path("/k/id"), Path("/t/kh"), control_path=Path("/run/user/1000/bastet/%C"))
    args = ssh_args(t)
    joined = " ".join(args)
    assert "ControlMaster=auto" in joined and "ControlPath=/run/user/1000/bastet/%C" in joined
    assert "ControlPersist=60s" in joined and args[-1] == "bastet@203.0.113.10"


def test_control_path_dir_is_private(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    p = control_path()
    assert p == tmp_path / "bastet" / "%C" and (tmp_path / "bastet").stat().st_mode & 0o777 == 0o700


def test_control_path_falls_back_to_cache_dir_without_xdg_runtime_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    p = control_path()
    expected = tmp_path / ".cache" / "bastet" / "ssh"
    assert p == expected / "%C" and expected.stat().st_mode & 0o777 == 0o700


def test_control_path_falls_back_when_xdg_runtime_dir_is_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", "")
    monkeypatch.setenv("HOME", str(tmp_path))
    p = control_path()
    assert p == tmp_path / ".cache" / "bastet" / "ssh" / "%C"


def test_close_master_sends_exit(monkeypatch):
    calls = []
    monkeypatch.setattr("bastet.core.remote.subprocess.run", lambda args, **kw: calls.append(args))
    t = SshTarget("203.0.113.10", "bastet", None, None, control_path=Path("/c/%C"))
    close_master(t)
    assert calls and calls[0][-3:] == ["-O", "exit", "bastet@203.0.113.10"]
    calls.clear()
    close_master(SshTarget("h", "bastet", None, None))
    assert calls == []
