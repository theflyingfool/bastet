import os
import socket
import subprocess
from collections.abc import Iterable
from pathlib import Path

from bastet.core.errors import BastetError

BASTET_NAME = "Bastet"

HOOK_MARKER = "# bastet-secrets-pre-commit"
HOOK_VERSION_MARKER = "# bastet-secrets-pre-commit-v2"
PRE_COMMIT_HOOK = f"""#!/bin/sh
{HOOK_MARKER}
{HOOK_VERSION_MARKER}
# Installed by `bastet` (GitRepo.ensure_hook): refuses to commit a plain-text secret note.
here=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
if [ -x "$here/pre-commit.local" ]; then
    "$here/pre-commit.local" "$@" || exit $?
fi
bad=""
old_ifs=$IFS
IFS='
'
set -f
for f in $(git -c core.quotePath=false diff --cached --name-only --no-renames --diff-filter=ACMR); do
    case "$f" in
        _secrets/*.md)
            content=$(git show ":$f" 2>/dev/null)
            status=$?
            if [ "$status" -ne 0 ]; then
                # can't read what's actually staged: fail closed rather than let it through
                bad="$bad $f"
            elif printf '%s' "$content" | grep -q 'locked: false'; then
                bad="$bad $f"
            elif ! printf '%s' "$content" | grep -q 'BEGIN AGE ENCRYPTED FILE'; then
                bad="$bad $f"
            fi
            ;;
        \\"_secrets/*.md*)
            # core.quotePath only hides the backslash-escaping for ASCII; a name with a quote,
            # backslash, tab or newline is still C-quoted and lands here -- refuse it too, fail closed.
            bad="$bad $f"
            ;;
    esac
done
IFS=$old_ifs
set +f
if [ -n "$bad" ]; then
    echo "bastet: refusing to commit plain-text secret note(s):$bad" >&2
    echo "bastet: run \\`bastet secret lock\\` first" >&2
    exit 1
fi
exit 0
"""

TIMEOUT = 120


def git_env() -> dict[str, str]:
    """Never wait for a password prompt or an unreachable host."""
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes -o ConnectTimeout=15")
    return env


def bastet_email() -> str:
    return f"bastet@{socket.gethostname()}"


class GitRepo:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        try:
            result = subprocess.run(
                ["git", "-C", str(self.root), *args], capture_output=True, text=True, env=git_env(), timeout=TIMEOUT
            )
        except subprocess.TimeoutExpired:
            raise BastetError(f"git {args[0]} timed out after {TIMEOUT}s", file=self.root) from None
        if check and result.returncode != 0:
            raise BastetError(f"git {args[0]} failed: {result.stderr.strip()}", file=self.root)
        return result

    def is_repo(self) -> bool:
        if not self.root.is_dir():
            return False
        result = self._git("rev-parse", "--show-toplevel", check=False)
        return result.returncode == 0 and Path(result.stdout.strip()).resolve() == self.root.resolve()

    def clone_from(self, url: str) -> bool:
        try:
            result = subprocess.run(
                ["git", "clone", "-q", url, str(self.root)], capture_output=True, text=True, env=git_env(), timeout=TIMEOUT
            )
        except subprocess.TimeoutExpired:
            return False
        return result.returncode == 0

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

    def head(self) -> str:
        return self._git("rev-parse", "HEAD").stdout.strip()

    def head_or_none(self) -> str | None:
        """Like `head()`, but None instead of raising when there isn't a commit yet."""
        r = self._git("rev-parse", "--verify", "-q", "HEAD", check=False)
        return r.stdout.strip() if r.returncode == 0 else None

    def changed_paths(self, a: str, b: str, pathspec: str | None = None) -> list[str]:
        """Paths that differ between two commits (`git diff --name-only`), optionally under `pathspec`.
        Raises if either commit doesn't resolve (e.g. one was pruned after a rewrite)."""
        args = ["diff", "--name-only", a, b]
        if pathspec:
            args += ["--", pathspec]
        return [p for p in self._git(*args).stdout.splitlines() if p]

    def _unpushed(self) -> set[str] | None:
        """Commit hashes not yet pushed, or None when there's no upstream (everything counts as unpushed)."""
        if not self._has_upstream():
            return None
        r = self._git("rev-list", "@{u}..HEAD", check=False)
        if r.returncode != 0:
            return None
        return set(r.stdout.split())

    def squash_since(self, base: str, message: str) -> bool:
        """Squash every commit since `base` into one, only when none of them are pushed.

        Commits only the paths that actually changed between `base` and the old HEAD, so anything
        else a user had already staged stays staged and out of the squash commit.
        """
        head = self.head()
        if head == base:
            return False
        since = set(self._git("rev-list", f"{base}..HEAD").stdout.split())
        unpushed = self._unpushed()
        if unpushed is not None and not since <= unpushed:
            return False
        paths = self._git("diff", "--name-only", base, head).stdout.split("\n")
        paths = [p for p in paths if p]
        self._git("reset", "--soft", base)
        identity = ["-c", f"user.name={BASTET_NAME}", "-c", f"user.email={bastet_email()}"]
        self._git(*identity, "commit", "-q", "-m", message, "--", *paths)
        return True

    def pull(self) -> list[str]:
        """Pull (fast-forward only); returns the paths that changed, relative to the root."""
        if not self.has_remote() or not self._has_upstream():
            return []
        before = self._git("rev-parse", "HEAD", check=False)
        start = before.stdout.strip() if before.returncode == 0 else None
        self._git("pull", "--ff-only", "-q")
        if start is None:
            return []
        end = self.head()
        if start == end:
            return []
        r = self._git("diff", "--name-only", start, end, check=False)
        return [p for p in r.stdout.splitlines() if p]

    def last_author(self, path: Path) -> tuple[str, str, str] | None:
        """(name, email, date YYYY-MM-DD) of the last commit that touched `path`; None if it has no history."""
        r = self._git("log", "-1", "--format=%an%x1f%ae%x1f%as", "--", self._rel(path), check=False)
        line = r.stdout.strip()
        if not line or line.count("\x1f") != 2:
            return None
        name, email, date = line.split("\x1f")
        return name, email, date

    def push(self) -> bool:
        if not self.has_remote():
            return True
        args = ["push", "-q"] if self._has_upstream() else ["push", "-q", "-u", "origin", "HEAD"]
        try:
            return self._git(*args, check=False).returncode == 0
        except BastetError:
            return False

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

    def busy(self) -> bool:
        """A merge, rebase, cherry-pick or revert is in progress."""
        for name in ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
            r = self._git("rev-parse", "--git-path", name, check=False)
            if r.returncode == 0 and (self.root / r.stdout.strip()).exists():
                return True
        return False

    def log_entries(self, limit: int = 50) -> list[tuple[str, str, str]]:
        """(date YYYY-MM-DD, author, subject), newest first; [] when there is no history."""
        r = self._git("log", f"-n{limit}", "--format=%as%x1f%an%x1f%s", check=False)
        if r.returncode != 0:
            return []
        return [tuple(line.split("\x1f", 2)) for line in r.stdout.splitlines() if line.count("\x1f") >= 2]

    def _rel(self, path: Path) -> str:
        return Path(path).resolve().relative_to(self.root.resolve()).as_posix()

    def file_at(self, ref: str, path: Path) -> str | None:
        r = self._git("show", f"{ref}:{self._rel(path)}", check=False)
        return r.stdout if r.returncode == 0 else None

    def file_log(self, path: Path) -> list[tuple[str, str, str]]:
        r = self._git("log", "--format=%H%x1f%an%x1f%as", "--", self._rel(path), check=False)
        if r.returncode != 0:
            return []
        return [tuple(line.split("\x1f")) for line in r.stdout.splitlines() if line.count("\x1f") == 2]

    def file_versions(self, path: Path, shas: Iterable[str]) -> dict[str, str | None]:
        """`path` as it read at each of `shas`, None where it didn't exist yet; one `git cat-file --batch` process."""
        shas = list(shas)
        if not shas:
            return {}
        rel = self._rel(path)
        request = "".join(f"{sha}:{rel}\n" for sha in shas).encode()
        try:
            result = subprocess.run(
                ["git", "-C", str(self.root), "cat-file", "--batch"],
                input=request,
                capture_output=True,
                env=git_env(),
                timeout=TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            raise BastetError(f"git cat-file timed out after {TIMEOUT}s", file=self.root) from None
        out = result.stdout
        versions: dict[str, str | None] = {}
        pos = 0
        for sha in shas:
            nl = out.index(b"\n", pos)
            header = out[pos:nl].split()
            pos = nl + 1
            if header[-1] == b"missing":
                versions[sha] = None
                continue
            size = int(header[2])
            versions[sha] = out[pos : pos + size].decode("utf-8")
            pos += size + 1  # the trailing newline after the object's content
        return versions

    def ensure_hook(self) -> None:
        """Install the plain-text-secret-refusing pre-commit hook; idempotent, chains a pre-existing foreign hook."""
        hooks_dir = Path(self._git("rev-parse", "--git-path", "hooks").stdout.strip())
        if not hooks_dir.is_absolute():
            hooks_dir = self.root / hooks_dir
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hook_path = hooks_dir / "pre-commit"
        local_path = hooks_dir / "pre-commit.local"
        if hook_path.is_file():
            existing = hook_path.read_text(encoding="utf-8")
            if HOOK_MARKER in existing:
                if HOOK_VERSION_MARKER in existing:
                    return  # already ours, and already this version
                # ours, but an older version: rewrite in place rather than chain it to itself
                hook_path.write_text(PRE_COMMIT_HOOK, encoding="utf-8")
                hook_path.chmod(0o755)
                return
            hook_path.rename(local_path)
            local_path.chmod(0o755)
        hook_path.write_text(PRE_COMMIT_HOOK, encoding="utf-8")
        hook_path.chmod(0o755)

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

    def amend(self, paths: Iterable[Path]) -> bool:
        """Fold more files into the last commit, keeping its message and author -- used right after
        `commit`, before anything is pushed, so the dashboard can catch up to a commit it couldn't
        see yet when it was first rendered."""
        rel = [str(Path(p).resolve().relative_to(self.root.resolve())) for p in paths]
        if not rel:
            return False
        self._git("add", "--", *rel)
        if self._git("diff", "--cached", "--quiet", "--", *rel, check=False).returncode == 0:
            return False
        self._git("commit", "-q", "--amend", "--no-edit", "--", *rel)
        return True
