import socket
import subprocess
from collections.abc import Iterable
from pathlib import Path

from bastet.core.errors import BastetError

BASTET_NAME = "Bastet"


def bastet_email() -> str:
    return f"bastet@{socket.gethostname()}"


class GitRepo:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(
            ["git", "-C", str(self.root), *args], capture_output=True, text=True
        )
        if check and result.returncode != 0:
            raise BastetError(f"git {args[0]} failed: {result.stderr.strip()}", file=self.root)
        return result

    def is_repo(self) -> bool:
        if not self.root.is_dir():
            return False
        result = self._git("rev-parse", "--show-toplevel", check=False)
        return result.returncode == 0 and Path(result.stdout.strip()).resolve() == self.root.resolve()

    def init(self) -> None:
        self._git("init", "-q", "-b", "main")

    def has_remote(self) -> bool:
        return bool(self._git("remote").stdout.strip())

    def add_remote(self, url: str) -> None:
        self._git("remote", "add", "origin", url)

    def _has_upstream(self) -> bool:
        branch = self._git("symbolic-ref", "--short", "-q", "HEAD", check=False).stdout.strip()
        if not branch:
            return False
        return self._git("config", "--get", f"branch.{branch}.merge", check=False).returncode == 0

    def pull(self) -> None:
        if not self.has_remote() or not self._has_upstream():
            return
        self._git("pull", "--ff-only", "-q")

    def push(self) -> bool:
        if not self.has_remote():
            return True
        args = ["push", "-q"] if self._has_upstream() else ["push", "-q", "-u", "origin", "HEAD"]
        return self._git(*args, check=False).returncode == 0

    def dirty(self) -> list[Path]:
        out = self._git("status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
        entries = out.split("\0")
        paths: list[Path] = []
        i = 0
        while i < len(entries):
            entry = entries[i]
            if entry:
                status, rel = entry[:2], entry[3:]
                paths.append(self.root / rel)
                if status[0] in "RC":
                    i += 1
            i += 1
        return paths

    def commit(self, paths: Iterable[Path], message: str, *, as_bastet: bool = True) -> bool:
        rel = [str(Path(p).resolve().relative_to(self.root.resolve())) for p in paths]
        if not rel:
            return False
        self._git("add", "--", *rel)
        if self._git("diff", "--cached", "--quiet", "--", *rel, check=False).returncode == 0:
            return False
        identity = ["-c", f"user.name={BASTET_NAME}", "-c", f"user.email={bastet_email()}"] if as_bastet else []
        self._git(*identity, "commit", "-q", "-m", message, "--", *rel)
        return True
