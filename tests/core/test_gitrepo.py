import subprocess
from pathlib import Path

import pytest

from bastet.core.errors import BastetError
from bastet.core.gitrepo import GitRepo


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path) -> GitRepo:
    r = GitRepo(tmp_path / "inv")
    r.root.mkdir()
    r.init()
    git(r.root, "config", "user.name", "Tester")
    git(r.root, "config", "user.email", "tester@example.com")
    return r


def test_init_and_is_repo(tmp_path, repo):
    assert repo.is_repo()
    assert not GitRepo(tmp_path).is_repo() or (tmp_path / ".git").exists()


def test_commit_as_bastet_only_given_paths(repo):
    a = repo.root / "a.md"
    b = repo.root / "b.md"
    a.write_text("a\n")
    b.write_text("b\n")
    assert repo.commit([a], "add a")
    assert git(repo.root, "log", "-1", "--format=%an").strip() == "Bastet"
    assert repo.dirty() == [b]


def test_commit_as_user(repo):
    a = repo.root / "a.md"
    a.write_text("a\n")
    repo.commit([a], "mine", as_bastet=False)
    assert git(repo.root, "log", "-1", "--format=%an").strip() == "Tester"


def test_commit_nothing_returns_false(repo):
    a = repo.root / "a.md"
    a.write_text("a\n")
    repo.commit([a], "add a")
    assert repo.commit([a], "again") is False


def test_dirty_lists_untracked_and_modified(repo):
    a = repo.root / "a.md"
    a.write_text("a\n")
    repo.commit([a], "add a")
    a.write_text("changed\n")
    (repo.root / "sub").mkdir()
    (repo.root / "sub" / "new.md").write_text("n\n")
    assert sorted(repo.dirty()) == [a, repo.root / "sub" / "new.md"]


def test_no_remote_pull_push_are_noops(repo):
    assert not repo.has_remote()
    repo.pull()
    assert repo.push() is True


def test_pull_and_push_with_remote(tmp_path, repo):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    repo.add_remote(str(bare))
    a = repo.root / "a.md"
    a.write_text("a\n")
    repo.commit([a], "add a")
    assert repo.push() is True
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(bare), str(other)], check=True)
    git(other, "config", "user.name", "Tester")
    git(other, "config", "user.email", "tester@example.com")
    (other / "b.md").write_text("b\n")
    git(other, "add", "b.md")
    git(other, "commit", "-q", "-m", "b")
    git(other, "push", "-q")
    repo.pull()
    assert (repo.root / "b.md").exists()


def test_pull_failure_is_bastet_error(tmp_path, repo):
    repo.add_remote(str(tmp_path / "does-not-exist.git"))
    git(repo.root, "config", "branch.main.remote", "origin")
    git(repo.root, "config", "branch.main.merge", "refs/heads/main")
    with pytest.raises(BastetError):
        repo.pull()


def test_git_runs_non_interactive(monkeypatch):
    from bastet.core.gitrepo import git_env

    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
    env = git_env()
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert "BatchMode=yes" in env["GIT_SSH_COMMAND"] and "ConnectTimeout" in env["GIT_SSH_COMMAND"]
    monkeypatch.setenv("GIT_SSH_COMMAND", "ssh -i mykey")
    assert git_env()["GIT_SSH_COMMAND"] == "ssh -i mykey"


def test_push_timeout_is_false_not_crash(tmp_path, repo, monkeypatch):
    import bastet.core.gitrepo as g

    repo.add_remote(str(tmp_path / "x.git"))
    real = g.subprocess.run

    def slow(cmd, *a, **k):
        if "push" in cmd:
            raise g.subprocess.TimeoutExpired(cmd, 1)
        return real(cmd, *a, **k)

    monkeypatch.setattr(g.subprocess, "run", slow)
    assert repo.push() is False
