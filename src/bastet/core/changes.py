import difflib
import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Change:
    path: Path
    before: str | None
    after: str


def render_diff(change: Change, root: Path) -> str:
    rel = change.path.relative_to(root).as_posix()
    before = (change.before or "").splitlines(keepends=True)
    after = change.after.splitlines(keepends=True)
    old = "/dev/null" if change.before is None else f"a/{rel}"
    return "".join(difflib.unified_diff(before, after, fromfile=old, tofile=f"b/{rel}"))


def write_changes(changes: Iterable[Change]) -> None:
    for change in changes:
        change.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=change.path.parent, prefix=".bastet-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(change.after)
            os.replace(tmp, change.path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
