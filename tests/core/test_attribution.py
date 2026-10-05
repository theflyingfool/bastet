import subprocess
from pathlib import Path

import pytest

from bastet.core.attribution import last_setter
from bastet.core.gitrepo import GitRepo


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path) -> GitRepo:
    r = GitRepo(tmp_path)
    r.init()
    git(tmp_path, "config", "user.name", "Tester")
    git(tmp_path, "config", "user.email", "t@example.com")
    return r


def write(repo: GitRepo, ram: str, *, as_bastet: bool) -> Path:
    p = repo.root / "h.md"
    p.write_text(f"---\nbastet: host\nram: {ram}\nos: x\n---\n")
    repo.commit([p], f"ram {ram}", as_bastet=as_bastet)
    return p


def test_bastet_set_value(repo):
    p = write(repo, "16 GB", as_bastet=True)
    s = last_setter(repo, p, "ram")
    assert s.author == "Bastet" and s.sha is not None


def test_user_changed_value_after_bastet(repo):
    write(repo, "16 GB", as_bastet=True)
    p = write(repo, "32 GB", as_bastet=False)
    assert last_setter(repo, p, "ram").author == "Tester"


def test_unrelated_later_commits_dont_steal_credit(repo):
    p = write(repo, "16 GB", as_bastet=False)
    p.write_text("---\nbastet: host\nram: 16 GB\nos: y\n---\n")
    repo.commit([p], "os edit", as_bastet=True)
    assert last_setter(repo, p, "ram").author == "Tester"


def test_uncommitted_value_is_yours(repo):
    p = write(repo, "16 GB", as_bastet=True)
    p.write_text("---\nbastet: host\nram: 64 GB\nos: x\n---\n")
    s = last_setter(repo, p, "ram")
    assert s.sha is None and "uncommitted" in s.describe()


def test_missing_key_is_none(repo):
    p = write(repo, "16 GB", as_bastet=True)
    assert last_setter(repo, p, "cpu") is None


def test_subprocess_count_is_constant_regardless_of_history_length(tmp_path, monkeypatch):
    import bastet.core.gitrepo as g

    def make_repo(n: int) -> tuple[GitRepo, Path]:
        root = tmp_path / f"r{n}"
        root.mkdir()
        r = GitRepo(root)
        r.init()
        git(root, "config", "user.name", "Tester")
        git(root, "config", "user.email", "t@example.com")
        p = None
        for i in range(n):
            # ram stays constant so the walk-back never breaks early: it has to visit every commit
            p = r.root / "h.md"
            p.write_text(f"---\nbastet: host\nram: 16 GB\nos: x{i}\n---\n")
            r.commit([p], f"os {i}", as_bastet=True)
        return r, p

    def count_calls(repo: GitRepo, p: Path) -> int:
        calls = []
        real_run = g.subprocess.run

        def counting_run(*a, **k):
            calls.append(a)
            return real_run(*a, **k)

        monkeypatch.setattr(g.subprocess, "run", counting_run)
        try:
            last_setter(repo, p, "ram")
        finally:
            monkeypatch.setattr(g.subprocess, "run", real_run)
        return len(calls)

    r5, p5 = make_repo(5)
    r50, p50 = make_repo(50)
    assert count_calls(r5, p5) == count_calls(r50, p50)
