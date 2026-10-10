"""Where the last `refresh` (or a command that folds one in, via `finish`) said it couldn't run:
written so `doctor` can list it until a refresh actually succeeds, even across commands.

`.bastet/refresh-skipped`, next to the other `.bastet/` bookkeeping files (`secrets-confirmed`,
`unlock`) -- gitignored the same way, via `.git/info/exclude`, never the tracked `.gitignore`.
"""

from pathlib import Path

REFRESH_SKIPPED_PATH = ".bastet/refresh-skipped"


def write(root: Path, reason: str) -> None:
    try:
        from bastet.core.secrets.plaintext import _ensure_gitignored  # keeps .bastet/ out of git

        _ensure_gitignored(root)
        path = root / REFRESH_SKIPPED_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(reason + "\n", encoding="utf-8")
    except OSError:
        pass  # bookkeeping must never break the command that's already skipping


def clear(root: Path) -> None:
    try:
        (root / REFRESH_SKIPPED_PATH).unlink(missing_ok=True)
    except OSError:
        pass


def last_reason(root: Path) -> str | None:
    path = root / REFRESH_SKIPPED_PATH
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None
