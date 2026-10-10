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
    assert repo.pull() == []
    assert repo.push() is True


def test_pending_push_false_with_no_remote(repo):
    a = repo.root / "a.md"
    a.write_text("a\n")
    repo.commit([a], "add a")
    assert repo.pending_push() is False


def test_pending_push_false_with_nothing_committed(tmp_path, repo):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    repo.add_remote(str(bare))
    assert repo.pending_push() is False


def test_pending_push_true_before_the_first_push(tmp_path, repo):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    repo.add_remote(str(bare))
    a = repo.root / "a.md"
    a.write_text("a\n")
    repo.commit([a], "add a")
    assert repo.pending_push() is True


def test_pending_push_false_once_pushed(tmp_path, repo):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    repo.add_remote(str(bare))
    a = repo.root / "a.md"
    a.write_text("a\n")
    repo.commit([a], "add a")
    assert repo.push() is True
    assert repo.pending_push() is False


def test_pending_push_true_after_a_local_commit_the_remote_never_saw(tmp_path, repo):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    repo.add_remote(str(bare))
    a = repo.root / "a.md"
    a.write_text("a\n")
    repo.commit([a], "add a")
    repo.push()
    b = repo.root / "b.md"
    b.write_text("b\n")
    repo.commit([b], "add b")
    assert repo.pending_push() is True


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
    (other / "_secrets").mkdir()
    (other / "_secrets" / "lab").mkdir()
    (other / "_secrets" / "lab" / "x.md").write_text("secret note\n")
    git(other, "add", "b.md", "_secrets")
    git(other, "commit", "-q", "-m", "b")
    git(other, "push", "-q")
    changed = repo.pull()
    assert (repo.root / "b.md").exists()
    assert sorted(changed) == ["_secrets/lab/x.md", "b.md"]


def test_last_author(repo):
    a = repo.root / "a.md"
    a.write_text("a\n")
    repo.commit([a], "add a")
    name, email, date = repo.last_author(a)
    assert name == "Bastet" and "@" in email and len(date) == 10


def test_last_author_no_history_is_none(repo):
    a = repo.root / "a.md"
    a.write_text("a\n")
    assert repo.last_author(a) is None


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


def test_head_is_the_current_commit(repo):
    a = repo.root / "a.md"
    a.write_text("a\n")
    repo.commit([a], "add a")
    assert repo.head() == git(repo.root, "rev-parse", "HEAD").strip()


def test_squash_since_combines_unpushed_commits(repo):
    a = repo.root / "a.md"
    a.write_text("a\n")
    repo.commit([a], "seed")
    base = repo.head()
    b = repo.root / "b.md"
    b.write_text("b\n")
    repo.commit([b], "add b")
    c = repo.root / "c.md"
    c.write_text("c\n")
    repo.commit([c], "add c")
    assert repo.squash_since(base, "squashed") is True
    log = git(repo.root, "log", "--format=%H")
    assert len(log.strip().splitlines()) == 2  # seed + the squash
    assert git(repo.root, "log", "-1", "--format=%s").strip() == "squashed"
    assert (repo.root / "b.md").exists() and (repo.root / "c.md").exists()


def test_squash_since_leaves_other_staged_files_alone(repo):
    a = repo.root / "a.md"
    a.write_text("a\n")
    repo.commit([a], "seed")
    base = repo.head()
    b = repo.root / "b.md"
    b.write_text("b\n")
    repo.commit([b], "add b")
    unrelated = repo.root / "unrelated.md"
    unrelated.write_text("unrelated\n")
    git(repo.root, "add", "unrelated.md")
    assert repo.squash_since(base, "squashed") is True
    assert "unrelated.md" not in git(repo.root, "show", "--name-only", "--format=", "HEAD")
    assert "A  unrelated.md" in git(repo.root, "status", "--porcelain")


def test_file_versions_reads_each_sha_in_one_batch(repo):
    a = repo.root / "a.md"
    a.write_text("v1\n")
    repo.commit([a], "c1")
    sha1 = repo.head()
    a.write_text("v2 ü\n")
    repo.commit([a], "c2")
    sha2 = repo.head()
    assert repo.file_versions(a, [sha1, sha2]) == {sha1: "v1\n", sha2: "v2 ü\n"}


def test_file_versions_path_absent_at_sha_is_none(repo):
    first = repo.root / "first.md"
    first.write_text("x\n")
    repo.commit([first], "c0")
    sha0 = repo.head()
    a = repo.root / "a.md"
    a.write_text("v1\n")
    repo.commit([a], "c1")
    sha1 = repo.head()
    assert repo.file_versions(a, [sha0, sha1]) == {sha0: None, sha1: "v1\n"}


def test_file_versions_empty_shas_is_empty_dict(repo):
    a = repo.root / "a.md"
    a.write_text("v1\n")
    repo.commit([a], "c1")
    assert repo.file_versions(a, []) == {}


def test_squash_since_refuses_when_some_commits_are_already_pushed(tmp_path, repo):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    repo.add_remote(str(bare))
    a = repo.root / "a.md"
    a.write_text("a\n")
    repo.commit([a], "seed")
    base = repo.head()
    b = repo.root / "b.md"
    b.write_text("b\n")
    repo.commit([b], "add b")
    assert repo.push() is True  # "add b" is now pushed
    c = repo.root / "c.md"
    c.write_text("c\n")
    repo.commit([c], "add c")
    assert repo.squash_since(base, "squashed") is False
    assert git(repo.root, "log", "--format=%s").strip().splitlines() == ["add c", "add b", "seed"]


def test_committing_as_you_without_a_git_identity_says_how_to_fix_it(tmp_path, monkeypatch):
    for var in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "EMAIL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")  # never guess an identity from the machine's hostname
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "user.useConfigOnly")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
    r = GitRepo(tmp_path / "inv")
    r.root.mkdir()
    r.init()
    note = r.root / "a.md"
    note.write_text("x\n")
    with pytest.raises(BastetError, match="git doesn't know who you are") as exc:
        r.commit([note], "mine", as_bastet=False)
    assert "git config --global user.name" in str(exc.value) and "Author identity unknown" not in str(exc.value)
    assert r.commit([note], "Bastet's own") is True  # Bastet's identity never needs yours


def test_an_identity_given_only_through_env_vars_passes_the_check(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "user.useConfigOnly")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Example")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "you@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Example")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "you@example.com")
    r = GitRepo(tmp_path / "inv")
    r.root.mkdir()
    r.init()
    note = r.root / "a.md"
    note.write_text("x\n")
    assert r.commit([note], "mine", as_bastet=False) is True


def test_an_identity_missing_only_for_the_author_is_reported(tmp_path, monkeypatch):
    for var in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "EMAIL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "user.useConfigOnly")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Example")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "you@example.com")
    r = GitRepo(tmp_path / "inv")
    r.root.mkdir()
    r.init()
    with pytest.raises(BastetError, match="git doesn't know who you are"):
        r._require_identity()
