from dataclasses import dataclass
from pathlib import Path

from bastet.core.errors import BastetError
from bastet.core.frontmatter import parse_document
from bastet.core.gitrepo import GitRepo

_MISSING = object()


def _value(text: str | None, path: Path, key: str) -> object:
    if text is None:
        return _MISSING
    try:
        doc = parse_document(text, path)
    except BastetError:
        return _MISSING
    if doc is None:
        return _MISSING
    return doc.data.get(key, _MISSING)


@dataclass
class Setter:
    author: str
    date: str | None
    sha: str | None

    def describe(self) -> str:
        if self.sha is None:
            return "an uncommitted edit"
        return f"set by {self.author} on {self.date} ({self.sha[:7]})"


def last_setter(repo: GitRepo, path: Path, key: str) -> Setter | None:
    """Who introduced the field's current value: value history, not line blame."""
    current = _value(path.read_text(encoding="utf-8"), path, key)
    if current is _MISSING:
        return None
    if _value(repo.file_at("HEAD", path), path, key) != current:
        return Setter("you", None, None)
    setter = None
    for sha, author, date in repo.file_log(path):
        if _value(repo.file_at(sha, path), path, key) == current:
            setter = Setter(author, date, sha)
        else:
            break
    return setter
