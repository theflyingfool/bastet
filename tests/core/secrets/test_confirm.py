import subprocess
from pathlib import Path

import pytest

from bastet.core.gitrepo import GitRepo
from bastet.core.secrets import confirm


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path) -> Path:
    root = tmp_path / "inv"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Tester")
    git(root, "config", "user.email", "tester@example.com")
    return root


def _commit(root: Path, path: str, text: str, message: str) -> None:
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", message)


def test_no_repo_never_alerts(tmp_path):
    repo = GitRepo(tmp_path / "nope")
    assert confirm.changed_since_confirmed(repo, tmp_path / "nope") == []


def test_ensure_baseline_then_no_alert_until_something_changes(repo):
    gr = GitRepo(repo)
    _commit(repo, "a.md", "x", "seed")
    confirm.ensure_baseline(gr, repo)
    assert confirm.changed_since_confirmed(gr, repo) == []


def test_change_under_secrets_after_baseline_is_detected(repo):
    gr = GitRepo(repo)
    _commit(repo, "a.md", "x", "seed")
    confirm.ensure_baseline(gr, repo)
    _commit(repo, "_secrets/lab/x.md", "sealed", "secret: set lab/x")
    assert confirm.changed_since_confirmed(gr, repo) == ["_secrets/lab/x.md"]


def test_confirm_advances_the_baseline(repo):
    gr = GitRepo(repo)
    _commit(repo, "a.md", "x", "seed")
    confirm.ensure_baseline(gr, repo)
    _commit(repo, "_secrets/lab/x.md", "sealed", "secret: set lab/x")
    confirm.confirm(gr, repo)
    assert confirm.changed_since_confirmed(gr, repo) == []


def test_confirm_own_commit_does_not_swallow_a_pending_change(repo):
    gr = GitRepo(repo)
    _commit(repo, "a.md", "x", "seed")
    confirm.ensure_baseline(gr, repo)
    _commit(repo, "_secrets/lab/upstream.md", "sealed", "upstream change, not ours")
    was_pending = confirm.pending(gr, repo)
    assert was_pending is True
    _commit(repo, "_secrets/lab/ours.md", "sealed", "secret: set lab/ours")
    confirm.confirm_own_commit(gr, repo, was_pending)
    # the upstream change must still show up: our own commit didn't quietly confirm it too
    assert "_secrets/lab/upstream.md" in confirm.changed_since_confirmed(gr, repo)


def test_confirm_own_commit_advances_when_nothing_was_pending(repo):
    gr = GitRepo(repo)
    _commit(repo, "a.md", "x", "seed")
    confirm.ensure_baseline(gr, repo)
    was_pending = confirm.pending(gr, repo)
    assert was_pending is False
    _commit(repo, "_secrets/lab/ours.md", "sealed", "secret: set lab/ours")
    confirm.confirm_own_commit(gr, repo, was_pending)
    assert confirm.changed_since_confirmed(gr, repo) == []
