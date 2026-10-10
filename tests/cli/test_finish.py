"""One commit per command, folding in regenerated notes; a consistent push-failure line; refresh
skip reasons printed as plain lines. See docs/plans/2026-10-07-bastet-simplify-ux.md Task 5."""

import bastet.cli.common as common_mod
from bastet.cli.app import app
from bastet.core.secrets.notes import SecretPath
from conftest import git


def _count(root) -> int:
    return int(git(root, "rev-list", "--count", "HEAD").strip())


# --- one commit per command ---


def test_add_role_makes_one_commit(runner, inventory):
    before = _count(inventory)
    result = runner.invoke(app, ["add", "role", "packages", "pve1", "-y"])
    assert result.exit_code == 0, result.output
    assert _count(inventory) - before == 1
    assert git(inventory, "log", "-1", "--format=%s").strip().startswith("add role packages to pve1")


def test_add_role_and_secrets_section_still_one_commit(runner, secret_keys, inventory, test_role, interactive):
    """`add role` writes the role file and (after setting a needed secret) the secrets-section
    embed in two separate `write_with_confirmation` calls -- both land in the one `add role` commit.
    The secret itself keeps its own commit (secret-related commits stay separate)."""
    before = _count(inventory)
    result = runner.invoke(
        app, ["add", "role", "impliedsecret", "box"], input="y\ny\nSENTINEL-API\nSENTINEL-API\n"
    )
    assert result.exit_code == 0, result.output
    after = _count(inventory)
    assert after - before == 2
    subjects = git(inventory, "log", f"-{after - before}", "--format=%s").splitlines()
    assert any(s.startswith("add role impliedsecret to box") for s in subjects)
    assert any(s.startswith("secret: set") for s in subjects)


# --- nothing to write: no commit ---


def test_second_refresh_up_to_date_makes_no_commit(runner, inventory):
    runner.invoke(app, ["refresh"])
    before = _count(inventory)
    result = runner.invoke(app, ["refresh"])
    assert result.exit_code == 0 and "up to date" in result.output
    assert _count(inventory) == before


# --- refresh skip reasons: a plain line, on stdout ---


def test_skip_reason_merge_in_progress_is_plain_stdout(runner, inventory):
    (inventory / ".git" / "MERGE_HEAD").write_text("0" * 40 + "\n")
    result = runner.invoke(app, ["refresh"])
    assert result.exit_code == 0
    assert "refresh skipped: a git merge or rebase is in progress" in result.stdout
    assert "refresh skipped" not in result.stderr


def test_skip_reason_plaintext_secret_is_plain_stdout(runner, secret_keys, inventory):
    from bastet.core.secrets import crypto
    from bastet.core.secrets.notes import SecretNote

    sp = SecretPath.parse("lab/dns_token")
    note = SecretNote.new(sp, source="chosen", created="2026-10-03T00:00", applies_to=sp.host)
    note.body = crypto.seal(sp.text, "SENTINEL-4242", [secret_keys["pub"]])
    note.write(inventory)
    git(inventory, "add", ".")
    git(inventory, "commit", "-q", "-m", "seed secret")
    runner.invoke(app, ["secret", "unlock"])

    result = runner.invoke(app, ["secret"])
    assert result.exit_code == 0, result.output
    assert "refresh skipped: 1 secret(s) are plain text" in result.stdout
    assert "refresh skipped" not in result.stderr


def test_skip_reason_unexpected_error_is_plain_stdout(runner, inventory, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(common_mod, "generated_changes", boom)
    result = runner.invoke(app, ["refresh"])
    assert result.exit_code == 0
    assert "refresh skipped: RuntimeError: kaboom" in result.stdout
    assert "refresh skipped" not in result.stderr


# --- push failure: one consistent line, exit code unaffected ---


def test_push_failure_prints_one_line_and_does_not_fail(runner, inventory, monkeypatch):
    monkeypatch.setattr(common_mod.GitRepo, "push", lambda self: False)
    result = runner.invoke(
        app, ["add", "host", "edge1", "--type", "vps", "--provider", "linode", "--ip", "203.0.113.10", "-y"]
    )
    assert result.exit_code == 0, result.output
    assert "committed locally; push failed (offline?); it'll be pushed next time" in result.output
