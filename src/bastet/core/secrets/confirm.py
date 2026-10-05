"""The last commit at which `_secrets/` changes were confirmed safe to use (spec 15.8).

The alert-and-gate only ever used to see a secret change that arrived through `load_context`'s own
pull, because it was driven by *that pull's* reported diff. Anything else that moves HEAD forward --
`bastet refresh`'s own pull, `secret set`'s quiet pull, a plain `git pull` run by hand, or the
Obsidian Git plugin committing or pulling on its own -- slipped past unnoticed.

Instead, this stores the commit confirmed last (`.bastet/secrets-confirmed`, gitignored, next to
`.bastet/unlock`) and diffs `_secrets/` between it and the current HEAD, however HEAD got there. The
baseline only moves forward when the person explicitly accepts a pending change (`apply`'s "y"), or
when Bastet made the secret commit itself (`set`, `generate`, `lock`) -- so the file plays the same
role as the old `.bastet/unconfirmed-secrets.json`, without needing a separate "pull observed this"
signal at all.
"""

from pathlib import Path

from bastet.core.errors import BastetError
from bastet.core.gitrepo import GitRepo

CONFIRMED_PATH = ".bastet/secrets-confirmed"


def _read(root: Path) -> str | None:
    path = root / CONFIRMED_PATH
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def _write(root: Path, commit: str) -> None:
    from bastet.core.secrets.plaintext import _ensure_gitignored  # keeps .bastet/ out of git

    _ensure_gitignored(root)
    path = root / CONFIRMED_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(commit + "\n", encoding="utf-8")


def ensure_baseline(repo: GitRepo, root: Path) -> None:
    """The very first time this runs against a repo (no file yet): record the current HEAD -- not
    HEAD after whatever pull is about to happen -- as confirmed, so nothing already in history is
    retroactively alerted on, but anything arriving from here on still is."""
    if not repo.is_repo() or _read(root) is not None:
        return
    head = repo.head_or_none()
    if head is not None:
        _write(root, head)


def confirm(repo: GitRepo, root: Path) -> None:
    """The person accepted pending secret changes, or Bastet just made its own secret commit: stop
    alerting about everything up to (and including) the current HEAD."""
    if not repo.is_repo():
        return
    head = repo.head_or_none()
    if head is not None:
        _write(root, head)


def pending(repo: GitRepo, root: Path) -> bool:
    """Whether there's an upstream secret change not yet confirmed, right now (before some other
    commit potentially moves HEAD further and would otherwise hide it from the caller)."""
    return bool(changed_since_confirmed(repo, root))


def confirm_own_commit(repo: GitRepo, root: Path, was_pending: bool) -> None:
    """After Bastet made its own secret commit (`set`, `generate`, `lock`): advance the confirmed
    baseline to the new HEAD, so Bastet never alerts on changes it just made itself -- but only when
    nothing was already unconfirmed before that commit (`was_pending`, from `pending()` called just
    before it). Otherwise the advance would quietly fold a real, not-yet-reviewed upstream change
    (pulled in by this same command, e.g. `secret set`'s quiet pull) into "confirmed" along with
    Bastet's own commit, swallowing the alert for it."""
    if not was_pending:
        confirm(repo, root)


def changed_since_confirmed(repo: GitRepo, root: Path) -> list[str]:
    """`_secrets/*.md` paths that changed since the last confirmed commit, however they got here."""
    if not repo.is_repo():
        return []
    baseline = _read(root)
    head = repo.head_or_none()
    if baseline is None or head is None or baseline == head:
        return []
    try:
        changed = repo.changed_paths(baseline, head, "_secrets/")
    except BastetError:
        # the confirmed commit no longer resolves (history rewritten, gc'd): fail closed rather than
        # silently resetting the baseline and missing whatever changed.
        return [f"_secrets/ (can't compare with the last confirmed commit {baseline[:12]})"]
    return sorted({p for p in changed if p.endswith(".md")})
