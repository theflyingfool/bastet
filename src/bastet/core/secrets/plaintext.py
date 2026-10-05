"""Unlock and lock: plain text in place, a saved original ciphertext, and the plain-text lock-down (spec 15.4)."""

import datetime as dt
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from bastet.core.secrets import crypto
from bastet.core.secrets.crypto import SecretError
from bastet.core.secrets.notes import SecretNote, SecretPath, all_notes

UNLOCK_DIR = ".bastet/unlock"
GITIGNORE_LINE = ".bastet/"


def _now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%dT%H:%M")


def _unlock_copy_path(root: Path, sp: SecretPath) -> Path:
    return root / UNLOCK_DIR / f"{sp.rel}.age"


def _ensure_gitignored(root: Path) -> None:
    gi = root / ".gitignore"
    if gi.is_file():
        lines = gi.read_text(encoding="utf-8").splitlines()
        if any(line.strip() == GITIGNORE_LINE for line in lines):
            return
        lines.append(GITIGNORE_LINE)
        gi.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        gi.write_text(GITIGNORE_LINE + "\n", encoding="utf-8")


def any_plain(root: Path) -> list[SecretPath]:
    """Every secret note that's plain text: unlocked, or a body that isn't a sealed armor block."""
    return [n.path for n in all_notes(root) if n.data.get("locked") is False or not n.is_sealed]


def unlock(root: Path, sctx, which: list[SecretPath] | None = None) -> list[SecretNote]:
    """Replace each sealed note's body with its plain value, saving the original ciphertext to restore on lock."""
    notes = all_notes(root)
    if which is not None:
        wanted = {sp.text for sp in which}
        notes = [n for n in notes if n.path.text in wanted]
    notes = [n for n in notes if n.is_sealed]  # already-plain notes need no unlocking
    if not notes:
        return []
    _ensure_gitignored(root)
    unlocked = []
    for note in notes:
        value = crypto.open_sealed(note.body.strip(), note.path.text, sctx.identities()).value
        sctx.redactor.add(value)
        copy_path = _unlock_copy_path(root, note.path)
        copy_path.parent.mkdir(parents=True, exist_ok=True)
        armor = note.body if note.body.endswith("\n") else note.body + "\n"
        copy_path.write_text(armor, encoding="utf-8")
        note.data["locked"] = False
        note.body = value
        note.write(root)
        unlocked.append(note)
    return unlocked


@dataclass
class LockResult:
    locked: int
    changed: int
    changed_paths: list[str] = field(default_factory=list)


def lock(root: Path, sctx) -> LockResult:
    """Re-encrypt every plain-text note: restore unchanged ciphertext exactly, re-seal changed values, commit."""
    notes = [n for n in all_notes(root) if n.data.get("locked") is False or not n.is_sealed]
    if not notes:
        return LockResult(locked=0, changed=0)
    now = _now()
    changed_paths: list[str] = []
    rel_paths: list[Path] = []
    for note in notes:
        value = note.body.strip()
        if not value:
            raise SecretError(f"{note.path.text}: empty; fill it in, or run `bastet secret set`, before locking")
        copy_path = _unlock_copy_path(root, note.path)
        original_armor = None
        original_value = None
        if copy_path.is_file():
            original_armor = copy_path.read_text(encoding="utf-8")
            try:
                original_value = crypto.open_sealed(original_armor.strip(), note.path.text, sctx.identities()).value
            except SecretError:
                original_value = None
        if original_armor is not None and original_value == value:
            note.body = original_armor
        else:
            note.body = crypto.seal(note.path.text, value, sctx.recipients)
            note.data["source"] = "chosen"
            if original_armor is not None:
                note.data["rotated"] = now
            else:
                note.data["created"] = now
            changed_paths.append(note.path.text)
        note.data["locked"] = True
        note.write(root)
        rel_paths.append(root / note.path.rel)
        sctx.redactor.add(value)
    shutil.rmtree(root / UNLOCK_DIR, ignore_errors=True)
    if changed_paths:
        from bastet.core.gitrepo import GitRepo

        repo = GitRepo(root)
        if repo.is_repo():
            words = ", ".join(changed_paths)
            repo.commit(rel_paths, f"secret: lock ({len(changed_paths)} changed: {words})")
    return LockResult(locked=len(notes), changed=len(changed_paths), changed_paths=changed_paths)


# --- pre-flight checks for `unlock`: Obsidian Sync and the Obsidian Git plugin ---


def _json_or_none(path: Path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _sync_enabled(root: Path) -> bool:
    data = _json_or_none(root / ".obsidian" / "core-plugins.json")
    if isinstance(data, list):
        return "sync" in data
    if isinstance(data, dict):
        return bool(data.get("sync"))
    return False


def _sync_excludes_secrets(root: Path) -> bool:
    path = root / ".obsidian" / "sync.json"
    if not path.is_file():
        return False
    return "_secrets" in path.read_text(encoding="utf-8")


def _obsidian_git_autocommits(root: Path) -> bool:
    data = _json_or_none(root / ".obsidian" / "plugins" / "obsidian-git" / "data.json")
    if not isinstance(data, dict):
        return False
    try:
        interval = int(data.get("autoSaveInterval") or 0)
    except (TypeError, ValueError):
        interval = 0
    return interval > 0 or bool(data.get("autoCommitOnFileChange"))


def preflight_block(root: Path) -> str | None:
    """A reason `unlock` must refuse, or None when it's safe to proceed."""
    if _sync_enabled(root) and not _sync_excludes_secrets(root):
        return "Obsidian Sync is on and doesn't exclude _secrets/; unlock refuses (secrets would sync in plain text)"
    if _obsidian_git_autocommits(root):
        return "the Obsidian Git plugin auto-commits; unlock refuses (it could commit plain text mid-edit)"
    return None


# --- the live countdown, driven by injected key-reading, clock and rendering, so it's testable ---


def run_countdown(read_key, now, render, *, total: float = 15 * 60, extend: float = 15 * 60, warn_at: float = 60) -> None:
    """Loop until it's time to lock: Enter extends, q/Esc/Ctrl-C lock now, zero remaining locks.

    `read_key(timeout)` returns one of "ENTER", "q", "ESC", "CTRL_C" or None (no key within timeout).
    `now()` returns the current time (seconds, monotonic). `render(remaining_seconds)` draws the countdown;
    it's also called once with 0 right before returning on timeout.
    """
    deadline = now() + total
    while True:
        remaining = deadline - now()
        if remaining <= 0:
            render(0)
            return
        render(remaining)
        key = read_key(min(1.0, remaining))
        if key is None:
            continue
        if key == "ENTER":
            deadline += extend
        elif key in ("q", "ESC", "CTRL_C"):
            return
