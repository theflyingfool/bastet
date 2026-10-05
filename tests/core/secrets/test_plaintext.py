import subprocess
from pathlib import Path

import pyrage
import pytest

from bastet.core.gitrepo import GitRepo
from bastet.core.secrets import crypto, plaintext
from bastet.core.secrets.crypto import SecretError, open_sealed
from bastet.core.secrets.notes import SecretNote, SecretPath
from bastet.core.secrets.redact import Redactor


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


class FakeSecrets:
    """A stand-in for SecretsContext: real recipients/identities, no cli dependency."""

    def __init__(self, recipients: list[str], ids: list) -> None:
        self.recipients = recipients
        self.redactor = Redactor()
        self._ids = ids

    def identities(self) -> list:
        return self._ids


@pytest.fixture
def repo(tmp_path) -> Path:
    root = tmp_path / "inv"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Tester")
    git(root, "config", "user.email", "tester@example.com")
    return root


@pytest.fixture
def keys():
    identity = pyrage.x25519.Identity.generate()
    return identity, str(identity.to_public())


@pytest.fixture
def sctx(keys) -> FakeSecrets:
    identity, pub = keys
    return FakeSecrets([pub], [identity])


def _seed(root: Path, sp: SecretPath, value: str, sctx: FakeSecrets, *, source="chosen", created="2026-10-03T10:00"):
    note = SecretNote.new(sp, source=source, created=created, applies_to=sp.host)
    note.body = crypto.seal(sp.text, value, sctx.recipients)
    note.write(root)
    return note


def _commit_all(root: Path, message: str = "seed") -> None:
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", message)


# --- unlock / lock round trip ---


def test_unlock_then_lock_unchanged_is_byte_identical_and_commits_nothing(repo, sctx):
    sp = SecretPath.parse("git1/gitea/admin_password")
    _seed(repo, sp, "s3cret", sctx)
    _commit_all(repo)
    path = repo / sp.rel
    before = path.read_bytes()
    before_head = git(repo, "rev-parse", "HEAD").strip()

    unlocked = plaintext.unlock(repo, sctx, None)
    assert len(unlocked) == 1
    note = SecretNote.load(repo, sp)
    assert note.data["locked"] is False
    assert note.body.strip() == "s3cret"
    assert path.read_bytes() != before

    result = plaintext.lock(repo, sctx)

    assert path.read_bytes() == before
    assert result.locked == 1
    assert result.changed == 0
    assert git(repo, "rev-parse", "HEAD").strip() == before_head
    assert not (repo / ".bastet" / "unlock").exists()


def test_editing_one_value_reencrypts_only_that_one(repo, sctx):
    sp1 = SecretPath.parse("git1/gitea/admin_password")
    sp2 = SecretPath.parse("git1/gitea/db_password")
    _seed(repo, sp1, "s3cret", sctx)
    _seed(repo, sp2, "other", sctx)
    _commit_all(repo)

    plaintext.unlock(repo, sctx, None)
    note1 = SecretNote.load(repo, sp1)
    note1.body = "new-value"
    note1.write(repo)

    result = plaintext.lock(repo, sctx)
    assert result.changed == 1

    changed_files = git(repo, "diff", "--name-only", "HEAD~1", "HEAD").strip().splitlines()
    assert changed_files == [sp1.rel]

    locked1 = SecretNote.load(repo, sp1)
    assert locked1.data["locked"] is True
    assert locked1.data["source"] == "chosen"
    assert open_sealed(locked1.body.strip(), sp1.text, sctx.identities()).value == "new-value"

    locked2 = SecretNote.load(repo, sp2)
    assert open_sealed(locked2.body.strip(), sp2.text, sctx.identities()).value == "other"


def test_lock_a_note_made_unlocked_from_scratch_sets_created(repo, sctx):
    sp = SecretPath.parse("git1/gitea/api_key")
    note = SecretNote.new(sp, source="chosen", created="2026-01-01T00:00", applies_to="git1")
    note.data["locked"] = False
    note.body = ""
    note.write(repo)
    _commit_all(repo)

    note = SecretNote.load(repo, sp)
    note.body = "fresh-value"
    note.write(repo)

    result = plaintext.lock(repo, sctx)
    assert result.changed == 1
    locked = SecretNote.load(repo, sp)
    assert locked.data["locked"] is True
    assert locked.data["created"] != "2026-01-01T00:00"
    assert open_sealed(locked.body.strip(), sp.text, sctx.identities()).value == "fresh-value"


def test_empty_value_refuses_to_lock(repo, sctx):
    sp = SecretPath.parse("git1/gitea/x")
    _seed(repo, sp, "value", sctx)
    _commit_all(repo)
    plaintext.unlock(repo, sctx, None)
    note = SecretNote.load(repo, sp)
    note.body = ""
    note.write(repo)
    with pytest.raises(SecretError, match=sp.text):
        plaintext.lock(repo, sctx)


def test_any_plain_treats_an_unreadable_note_as_plain_fail_closed(repo, sctx):
    sp = SecretPath.parse("git1/gitea/x")
    _seed(repo, sp, "value", sctx)
    bad = repo / "_secrets" / "git1" / "broken.md"
    bad.write_text("---\nbastet: secret\n[ this is not valid yaml\n---\nbody\n")
    _commit_all(repo)

    plain = plaintext.any_plain(repo)

    assert sp not in plain  # the genuinely sealed note is unaffected
    assert len(plain) == 1  # the malformed note counts as plain: fail closed, never skipped silently


def test_any_plain_lists_unlocked_and_unsealed_notes(repo, sctx):
    sp1 = SecretPath.parse("git1/gitea/x")
    sp2 = SecretPath.parse("git1/gitea/y")
    _seed(repo, sp1, "value", sctx)
    note = SecretNote.new(sp2, source="chosen", created="2026-01-01T00:00", applies_to="git1")
    note.data["locked"] = False
    note.body = ""
    note.write(repo)
    _commit_all(repo)
    assert [sp.text for sp in plaintext.any_plain(repo)] == ["git1/gitea/y"]


def test_unlock_saves_original_and_gitignores_bastet_dir(repo, sctx):
    sp = SecretPath.parse("git1/gitea/x")
    _seed(repo, sp, "value", sctx)
    _commit_all(repo)

    plaintext.unlock(repo, sctx, None)

    saved = repo / ".bastet" / "unlock" / f"{sp.rel}.age"
    assert saved.is_file()
    assert open_sealed(saved.read_text().strip(), sp.text, sctx.identities()).value == "value"
    # kept out of git locally (.git/info/exclude), without editing the tracked .gitignore
    assert not (repo / ".gitignore").exists() or ".bastet/" not in (repo / ".gitignore").read_text()
    exclude = (repo / ".git" / "info" / "exclude").read_text()
    assert ".bastet/" in exclude.splitlines()
    assert ".bastet" not in git(repo, "status", "--porcelain")


def test_unlock_one_by_name_leaves_others_sealed(repo, sctx):
    sp1 = SecretPath.parse("git1/gitea/x")
    sp2 = SecretPath.parse("git1/gitea/y")
    _seed(repo, sp1, "one", sctx)
    _seed(repo, sp2, "two", sctx)
    _commit_all(repo)

    plaintext.unlock(repo, sctx, [sp1])

    assert SecretNote.load(repo, sp1).data["locked"] is False
    assert SecretNote.load(repo, sp2).is_sealed


# --- I4: a lock that fails partway must never leave edits uncommitted forever ---


def test_partial_lock_failure_is_committed_in_full_on_the_next_successful_lock(repo, sctx):
    a, b = SecretPath.parse("lab/a"), SecretPath.parse("lab/b")
    _seed(repo, a, "value-a-old", sctx)
    _seed(repo, b, "value-b-old", sctx)
    _commit_all(repo)
    plaintext.unlock(repo, sctx)
    na = SecretNote.load(repo, a)
    na.body = "value-a-NEW\n"
    na.write(repo)
    nb = SecretNote.load(repo, b)
    nb.body = "\n"  # empty once the trailing newline is stripped: invalid
    nb.write(repo)

    with pytest.raises(SecretError):
        plaintext.lock(repo, sctx)
    # nothing was written by THIS call: a's new value must not have been re-sealed yet
    assert SecretNote.load(repo, a).body.strip() == "value-a-NEW"
    assert not SecretNote.load(repo, a).is_sealed

    nb = SecretNote.load(repo, b)
    nb.body = "value-b-old\n"
    nb.write(repo)
    result = plaintext.lock(repo, sctx)

    assert result.changed == 1
    status = git(repo, "status", "--porcelain", "--", "_secrets").strip()
    assert status == ""  # everything under _secrets/ got committed, including the stray prior write
    locked_a = SecretNote.load(repo, a)
    assert locked_a.is_sealed
    assert open_sealed(locked_a.body.strip(), a.text, sctx.identities()).value == "value-a-NEW"


# --- I5: lock must recover the exact value, not `body.strip()` ---


def test_lock_round_trips_a_value_with_a_trailing_newline(repo, sctx):
    sp = SecretPath.parse("lab/key")
    original = "-----BEGIN KEY-----\nabc\n-----END KEY-----\n"
    _seed(repo, sp, original, sctx)
    _commit_all(repo)

    plaintext.unlock(repo, sctx)
    result = plaintext.lock(repo, sctx)

    assert result.changed == 0  # no edit: must restore the exact original ciphertext
    note = SecretNote.load(repo, sp)
    assert open_sealed(note.body.strip(), sp.text, sctx.identities()).value == original


def test_lock_round_trips_leading_and_trailing_spaces(repo, sctx):
    sp = SecretPath.parse("lab/pw")
    original = "  s3cret with spaces  "
    _seed(repo, sp, original, sctx)
    _commit_all(repo)

    plaintext.unlock(repo, sctx)
    result = plaintext.lock(repo, sctx)

    assert result.changed == 0
    note = SecretNote.load(repo, sp)
    assert open_sealed(note.body.strip(), sp.text, sctx.identities()).value == original


# --- I6: `locked: false` on a note whose body is still sealed armor, not a value ---


def test_lock_of_locked_false_with_sealed_body_just_fixes_the_flag(repo, sctx):
    sp = SecretPath.parse("lab/c")
    _seed(repo, sp, "value-c", sctx)
    _commit_all(repo)
    note = SecretNote.load(repo, sp)
    note.data["locked"] = False  # nobody ran `unlock`; the body is still the real sealed armor
    note.write(repo)

    plaintext.lock(repo, sctx)

    note = SecretNote.load(repo, sp)
    assert note.data["locked"] is True
    assert note.is_sealed
    assert open_sealed(note.body.strip(), sp.text, sctx.identities()).value == "value-c"


# --- the pre-commit hook ---


def test_hook_blocks_unlocked_commit_and_allows_after_lock(repo, sctx):
    sp = SecretPath.parse("git1/gitea/x")
    _seed(repo, sp, "value", sctx)
    _commit_all(repo)

    gr = GitRepo(repo)
    gr.ensure_hook()

    plaintext.unlock(repo, sctx, None)
    result = subprocess.run(
        ["git", "-C", str(repo), "commit", "-am", "oops"], capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "pre-commit" in (result.stdout + result.stderr).lower() or result.returncode != 0

    plaintext.lock(repo, sctx)
    # lock() already committed the secret note through GitRepo, cleanly, via a hook-passing commit.
    status = git(repo, "status", "--porcelain", "--", sp.rel)
    assert status.strip() == ""


def test_existing_hook_is_chained(repo):
    hooks_dir = Path(git(repo, "rev-parse", "--git-path", "hooks").strip())
    if not hooks_dir.is_absolute():
        hooks_dir = repo / hooks_dir
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / "pre-commit"
    hook_path.write_text("#!/bin/sh\necho ran-local >&2\nexit 0\n")
    hook_path.chmod(0o755)

    gr = GitRepo(repo)
    gr.ensure_hook()

    local_path = hooks_dir / "pre-commit.local"
    assert local_path.is_file()
    assert "ran-local" in local_path.read_text()
    assert "bastet" in hook_path.read_text().lower()

    gr.ensure_hook()  # idempotent: no further chaining
    assert local_path.read_text().count("ran-local") == 1


def test_hook_is_idempotent_when_already_installed(repo):
    gr = GitRepo(repo)
    gr.ensure_hook()
    hooks_dir = Path(git(repo, "rev-parse", "--git-path", "hooks").strip())
    if not hooks_dir.is_absolute():
        hooks_dir = repo / hooks_dir
    first = (hooks_dir / "pre-commit").read_text()
    gr.ensure_hook()
    assert (hooks_dir / "pre-commit").read_text() == first
    assert not (hooks_dir / "pre-commit.local").exists()


def test_hook_rewrites_an_older_bastet_version_in_place(repo):
    from bastet.core.gitrepo import HOOK_MARKER

    hooks_dir = Path(git(repo, "rev-parse", "--git-path", "hooks").strip())
    if not hooks_dir.is_absolute():
        hooks_dir = repo / hooks_dir
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / "pre-commit"
    hook_path.write_text(f"#!/bin/sh\n{HOOK_MARKER}\necho old-buggy-version\nexit 0\n")
    hook_path.chmod(0o755)

    GitRepo(repo).ensure_hook()

    text = hook_path.read_text()
    assert "old-buggy-version" not in text
    assert "core.quotePath=false" in text
    assert not (hooks_dir / "pre-commit.local").exists()


def _hooks_dir(repo: Path) -> Path:
    hooks_dir = Path(git(repo, "rev-parse", "--git-path", "hooks").strip())
    return hooks_dir if hooks_dir.is_absolute() else repo / hooks_dir


def _git_rc(repo: Path, *args: str) -> int:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True).returncode


def test_hook_blocks_a_plain_note_with_a_space_in_its_name(repo):
    GitRepo(repo).ensure_hook()
    target = repo / "_secrets" / "nas" / "BMC password.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("---\nbastet: secret\nlocked: false\n---\nHunter2-PLAIN\n")
    git(repo, "add", str(target))
    assert _git_rc(repo, "commit", "-qm", "space") != 0


def test_hook_blocks_a_plain_note_with_a_non_ascii_name(repo):
    GitRepo(repo).ensure_hook()
    target = repo / "_secrets" / "nas" / "mot_de_passé.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("---\nbastet: secret\nlocked: false\n---\nHunter2-PLAIN\n")
    git(repo, "add", str(target))
    assert _git_rc(repo, "commit", "-qm", "nonascii") != 0


def test_hook_blocks_a_rename_that_turned_a_secret_plain(repo, sctx):
    sp = SecretPath.parse("nas/bmc")
    _seed(repo, sp, "value", sctx)
    _commit_all(repo)
    GitRepo(repo).ensure_hook()

    git(repo, "mv", str(repo / sp.rel), str(repo / "_secrets" / "nas" / "bmc2.md"))
    renamed = repo / "_secrets" / "nas" / "bmc2.md"
    # A small, high-similarity edit (git still classifies this as a rename, not a delete+add):
    # just flip `locked: false` without actually replacing the body with plain text. The old
    # `--diff-filter=ACM` dropped renames entirely, so this slipped straight through.
    text = renamed.read_text().replace("locked: true", "locked: false")
    renamed.write_text(text)
    git(repo, "add", "-A")
    assert git(repo, "diff", "--cached", "--name-status").startswith("R")  # confirm it's seen as a rename
    assert _git_rc(repo, "commit", "-qm", "rename") != 0


# --- Obsidian Sync / Git pre-flight detection ---


def test_sync_enabled_list_form_blocks_unless_secrets_excluded(repo):
    (repo / ".obsidian").mkdir()
    (repo / ".obsidian" / "core-plugins.json").write_text('["sync", "file-explorer"]')
    assert plaintext.preflight_block(repo) is not None

    (repo / ".obsidian" / "sync.json").write_text('{"excludedFolders": ["_secrets"]}')
    assert plaintext.preflight_block(repo) is None


def test_sync_enabled_dict_form_blocks(repo):
    (repo / ".obsidian").mkdir()
    (repo / ".obsidian" / "core-plugins.json").write_text('{"sync": true}')
    assert plaintext.preflight_block(repo) is not None


def test_obsidian_git_autosave_blocks(repo):
    plugin_dir = repo / ".obsidian" / "plugins" / "obsidian-git"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "data.json").write_text('{"autoSaveInterval": 5}')
    assert plaintext.preflight_block(repo) is not None


def test_obsidian_git_autocommit_on_change_blocks(repo):
    plugin_dir = repo / ".obsidian" / "plugins" / "obsidian-git"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "data.json").write_text('{"autoCommitOnFileChange": true}')
    assert plaintext.preflight_block(repo) is not None


def test_no_obsidian_config_does_not_block(repo):
    assert plaintext.preflight_block(repo) is None


# --- run_countdown, driven by fake keys and a fake clock ---


def test_run_countdown_locks_on_timeout():
    clock = {"t": 0.0}
    rendered = []

    def now():
        return clock["t"]

    def read_key(_timeout):
        clock["t"] += 1.0
        return None

    def render(remaining):
        rendered.append(remaining)
        if remaining <= 0:
            clock["t"] = 10_000  # stop the loop once we've observed the zero render

    plaintext.run_countdown(read_key, now, render, total=3, extend=900, warn_at=60)
    assert rendered[-1] == 0


def test_run_countdown_q_locks_immediately():
    clock = {"t": 0.0}

    def now():
        return clock["t"]

    keys = iter(["q"])

    def read_key(_timeout):
        clock["t"] += 1.0
        return next(keys, None)

    calls = []
    plaintext.run_countdown(read_key, now, lambda r: calls.append(r), total=900, extend=900, warn_at=60)
    assert len(calls) == 1  # locked right after the first key


def test_run_countdown_enter_extends_deadline():
    clock = {"t": 0.0}

    def now():
        return clock["t"]

    keys = iter(["ENTER", "q"])

    def read_key(_timeout):
        clock["t"] += 1.0
        return next(keys, None)

    remainings = []
    plaintext.run_countdown(read_key, now, lambda r: remainings.append(r), total=5, extend=100, warn_at=60)
    # after Enter at t=1 the deadline moves from 5 to 105, so the second render is well above 5
    assert remainings[1] > 5
