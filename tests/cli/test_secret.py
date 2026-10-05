import subprocess

import pytest

import bastet.cli.secret as secret_mod
from bastet.cli.app import app
from bastet.core.secrets import crypto
from bastet.core.secrets.notes import SecretNote, SecretPath
from bastet.roles.contract import load_roles
from conftest import git

SENTINEL = "SENTINEL-4242"


@pytest.fixture
def interactive(monkeypatch):
    """Pretend stdin/stdout are terminals, so prompts behave as they would for a person."""
    monkeypatch.setattr(secret_mod, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr(secret_mod, "_stdout_is_tty", lambda: True)


@pytest.fixture
def fake_clipboard(monkeypatch):
    calls = {"copied": None, "cleared": False}

    def fake_tool():
        return "wl-copy"

    def fake_copy(tool, value):
        calls["copied"] = (tool, value)

    monkeypatch.setattr(secret_mod, "_clipboard_tool", fake_tool)
    monkeypatch.setattr(secret_mod, "_copy_to_clipboard", fake_copy)
    return calls


@pytest.fixture
def test_role(inventory, tmp_path, monkeypatch):
    """A test-only role with two secret options (one generatable, one not), used by a host's role file."""
    roles_dir = tmp_path / "roles"
    (roles_dir / "testsecret").mkdir(parents=True)
    (roles_dir / "testsecret" / "role.yml").write_text(
        "description: a role for secrets tests\n"
        "options:\n"
        "  admin_password:\n"
        "    type: string\n"
        "    secret: true\n"
        "    generate:\n"
        "      kind: password\n"
        "      length: 20\n"
        "  db_password:\n"
        "    type: string\n"
        "    secret: true\n"
        "    generate:\n"
        "      kind: password\n"
        "      length: 16\n"
    )
    # A second role, deliberately never applied to any host: used only to exercise the
    # "no generate: Enter asks again" prompt directly (`secret set box othersecret plain_token`),
    # without it also showing up as a needed secret via resolve().
    (roles_dir / "othersecret").mkdir(parents=True)
    (roles_dir / "othersecret" / "role.yml").write_text(
        "description: a role for secrets tests\noptions:\n  plain_token:\n    type: string\n    secret: true\n"
    )
    # A third role, applied to a host but with its secret option left unset in the role file: needed
    # implicitly, by the contract alone (no `secret:` reference written anywhere).
    (roles_dir / "impliedsecret").mkdir(parents=True)
    (roles_dir / "impliedsecret" / "role.yml").write_text(
        "description: a role for secrets tests\noptions:\n  api_key:\n    type: string\n    secret: true\n"
    )
    merged = {**load_roles(), **load_roles(roles_dir)}
    monkeypatch.setattr(secret_mod, "load_roles", lambda: merged)

    (inventory / "hosts" / "box.md").write_text("---\nbastet: host\ntype: laptop\n---\n# box\n")
    roles = inventory / "_roles" / "hosts" / "box"
    roles.mkdir(parents=True)
    (roles / "testsecret.md").write_text(
        '---\nbastet: role\nrole: testsecret\napplies_to: "[[box]]"\n'
        'admin_password: "secret:admin_password"\ndb_password: "secret:db_password"\n---\n'
    )
    git(inventory, "add", ".")
    git(inventory, "commit", "-q", "-m", "test role")
    return {"host": "box", "role": "testsecret"}


def _seed_note(inventory, sp: SecretPath, value: str, pub: str) -> None:
    note = SecretNote.new(sp, source="chosen", created="2026-10-03T00:00", applies_to=sp.host)
    note.body = crypto.seal(sp.text, value, [pub])
    note.write(inventory)
    git(inventory, "add", ".")
    git(inventory, "commit", "-q", "-m", "seed secret")


def test_set_and_show_round_trip(runner, secret_keys, inventory, interactive):
    result = runner.invoke(
        app, ["secret", "set", "lab", "dns_token"], input=f"{SENTINEL}\n{SENTINEL}\n"
    )
    assert result.exit_code == 0, result.output
    assert SENTINEL not in result.output

    shown = runner.invoke(app, ["secret", "show", "lab", "dns_token"], input="1\n")
    assert shown.exit_code == 0, shown.output
    assert SENTINEL in shown.output


def test_enter_generates_when_contract_allows(runner, secret_keys, inventory, interactive, test_role):
    result = runner.invoke(app, ["secret", "set", "box", "testsecret", "admin_password"], input="\n")
    assert result.exit_code == 0, result.output
    note = SecretNote.load(inventory, SecretPath.parse("box/testsecret/admin_password"))
    assert note.data["source"] == "generated"
    from bastet.core.secrets.crypto import identity, open_sealed

    value = open_sealed(note.body.strip(), note.path.text, [identity(secret_keys["key_path"])]).value
    assert len(value) == 20


def test_enter_with_no_generate_asks_again(runner, secret_keys, inventory, interactive, test_role):
    result = runner.invoke(
        app, ["secret", "set", "box", "othersecret", "plain_token"], input=f"\n{SENTINEL}\n{SENTINEL}\n"
    )
    assert result.exit_code == 0, result.output
    assert "Enter a value, or e to fill it in yourself." in result.output


def test_typed_twice_mismatch_is_reasked(runner, secret_keys, inventory, interactive):
    result = runner.invoke(
        app, ["secret", "set", "lab", "dns_token"], input=f"one\ntwo\n{SENTINEL}\n{SENTINEL}\n"
    )
    assert result.exit_code == 0, result.output
    assert "didn't match" in result.output


def test_replace_asks_first(runner, secret_keys, inventory, interactive):
    sp = SecretPath.parse("lab/dns_token")
    _seed_note(inventory, sp, "old-value", secret_keys["pub"])
    declined = runner.invoke(app, ["secret", "set", "lab", "dns_token"], input="n\n")
    assert declined.exit_code == 0, declined.output
    assert "Replace" in declined.output and "Not replaced" in declined.output

    accepted = runner.invoke(
        app, ["secret", "set", "lab", "dns_token"], input=f"y\n{SENTINEL}\n{SENTINEL}\n"
    )
    assert accepted.exit_code == 0, accepted.output
    assert SENTINEL not in accepted.output


def test_piped_stdin_sets_a_single_secret(runner, secret_keys, inventory):
    result = runner.invoke(app, ["secret", "set", "lab", "dns_token"], input=f"{SENTINEL}\n")
    assert result.exit_code == 0, result.output
    assert SENTINEL not in result.output
    note = SecretNote.load(inventory, SecretPath.parse("lab/dns_token"))
    assert note.is_sealed


def test_e_makes_an_unlocked_empty_note_with_no_commit(runner, secret_keys, inventory, interactive):
    before = git(inventory, "rev-parse", "HEAD").strip()
    result = runner.invoke(app, ["secret", "set", "lab", "dns_token"], input="e\n")
    assert result.exit_code == 0, result.output
    note = SecretNote.load(inventory, SecretPath.parse("lab/dns_token"))
    assert note.data["locked"] is False
    assert note.body.strip() == ""
    after = git(inventory, "rev-parse", "HEAD").strip()
    assert before == after


def test_zero_over_two_needed_secrets_makes_one_commit(runner, secret_keys, inventory, interactive, test_role):
    before = git(inventory, "log", "--format=%H").strip().splitlines()
    result = runner.invoke(app, ["secret", "set"], input="0\n\n\n")
    assert result.exit_code == 0, result.output
    after = git(inventory, "log", "--format=%H").strip().splitlines()
    assert len(after) == len(before) + 1
    assert "secret: set 2 secrets" in git(inventory, "log", "-1", "--format=%s")


def test_q_after_first_secret_leaves_one_commit(runner, secret_keys, inventory, interactive, test_role):
    before = git(inventory, "log", "--format=%H").strip().splitlines()
    result = runner.invoke(app, ["secret", "set"], input="1\n\nq\n")
    assert result.exit_code == 0, result.output
    after = git(inventory, "log", "--format=%H").strip().splitlines()
    assert len(after) == len(before) + 1
    assert "secret: set box/testsecret/admin_password" in git(inventory, "log", "-1", "--format=%s")


def test_show_refuses_when_piped(runner, secret_keys, inventory):
    sp = SecretPath.parse("lab/dns_token")
    _seed_note(inventory, sp, SENTINEL, secret_keys["pub"])
    result = runner.invoke(app, ["secret", "show", "lab", "dns_token"])
    assert result.exit_code != 0
    assert SENTINEL not in result.output
    assert "terminal" in result.output


def test_show_clipboard_never_touches_the_real_clipboard(runner, secret_keys, inventory, interactive, fake_clipboard):
    sp = SecretPath.parse("lab/dns_token")
    _seed_note(inventory, sp, SENTINEL, secret_keys["pub"])
    result = runner.invoke(app, ["secret", "show", "lab", "dns_token"], input="2\n")
    assert result.exit_code == 0, result.output
    assert SENTINEL not in result.output
    assert fake_clipboard["copied"] == ("wl-copy", SENTINEL)


def test_bastet_secret_lists_without_values(runner, secret_keys, inventory):
    sp = SecretPath.parse("lab/dns_token")
    _seed_note(inventory, sp, SENTINEL, secret_keys["pub"])
    result = runner.invoke(app, ["secret"])
    assert result.exit_code == 0, result.output
    assert SENTINEL not in result.output
    assert "lab/dns_token" in result.output


def test_unset_secret_option_is_implied_needed(runner, secret_keys, inventory, interactive, test_role):
    """A role file that leaves a `secret: true` option unset still needs that secret (spec 15.3)."""
    from bastet.cli.common import load_context

    roles = inventory / "_roles" / "hosts" / "box"
    (roles / "impliedsecret.md").write_text('---\nbastet: role\nrole: impliedsecret\napplies_to: "[[box]]"\n---\n')
    git(inventory, "add", ".")
    git(inventory, "commit", "-q", "-m", "implied secret role")

    ctx = load_context()
    needed = {n.sp.text for n in secret_mod.needed_secrets(ctx)}
    assert "box/impliedsecret/api_key" in needed

    listed = runner.invoke(app, ["secret"])
    assert listed.exit_code == 0, listed.output
    assert "box/impliedsecret/api_key" in listed.output and "missing" in listed.output


def test_squash_does_not_sweep_in_an_unrelated_staged_file(runner, secret_keys, inventory, interactive, test_role):
    (inventory / "unrelated.md").write_text("---\nbastet: host\ntype: laptop\n---\n# unrelated\n")
    git(inventory, "add", "unrelated.md")

    result = runner.invoke(app, ["secret", "set"], input="0\n\n\n")
    assert result.exit_code == 0, result.output

    assert "secret: set 2 secrets" in git(inventory, "log", "-1", "--format=%s")
    show = git(inventory, "show", "--name-only", "--format=", "HEAD")
    assert "unrelated.md" not in show
    status = git(inventory, "status", "--porcelain")
    assert "A  unrelated.md" in status  # still staged, untouched by the squash


def test_single_named_set_pushes(runner, secret_keys, inventory, interactive, tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    git(inventory, "remote", "add", "origin", str(bare))
    git(inventory, "push", "-q", "-u", "origin", "main")

    result = runner.invoke(app, ["secret", "set", "lab", "dns_token"], input=f"{SENTINEL}\n{SENTINEL}\n")
    assert result.exit_code == 0, result.output

    remote_log = subprocess.run(
        ["git", "--git-dir", str(bare), "log", "--format=%s"], capture_output=True, text=True
    ).stdout
    assert "secret: set lab/dns_token" in remote_log


def test_piped_replace_refuses(runner, secret_keys, inventory):
    sp = SecretPath.parse("lab/dns_token")
    _seed_note(inventory, sp, "old-value", secret_keys["pub"])
    result = runner.invoke(app, ["secret", "set", "lab", "dns_token"], input=f"{SENTINEL}\n")
    assert result.exit_code != 0
    assert SENTINEL not in result.output
    note = SecretNote.load(inventory, sp)
    assert crypto.open_sealed(note.body.strip(), sp.text, [crypto.identity(secret_keys["key_path"])]).value == "old-value"


def test_piped_set_with_no_words_refuses(runner, secret_keys, inventory):
    result = runner.invoke(app, ["secret", "set"], input="0\n")
    assert result.exit_code != 0
    assert "pipe" in result.output or "terminal" in result.output


# --- unlock / lock (spec 15.4) ---


def test_unlock_on_a_non_terminal_leaves_notes_unlocked_and_lock_locks_them(runner, secret_keys, inventory):
    sp = SecretPath.parse("lab/dns_token")
    _seed_note(inventory, sp, SENTINEL, secret_keys["pub"])

    result = runner.invoke(app, ["secret", "unlock"])
    assert result.exit_code == 0, result.output
    assert "Unlocked" in result.output and "bastet secret lock" in result.output
    note = SecretNote.load(inventory, sp)
    assert note.data["locked"] is False
    assert note.body.strip() == SENTINEL

    locked = runner.invoke(app, ["secret", "lock"])
    assert locked.exit_code == 0, locked.output
    assert SENTINEL not in locked.output
    relocked = SecretNote.load(inventory, sp)
    assert relocked.data["locked"] is True
    assert relocked.is_sealed


def test_load_context_refuses_other_commands_while_plain_text_exists(runner, secret_keys, inventory):
    sp = SecretPath.parse("lab/dns_token")
    _seed_note(inventory, sp, SENTINEL, secret_keys["pub"])
    unlock_result = runner.invoke(app, ["secret", "unlock"])
    assert unlock_result.exit_code == 0, unlock_result.output

    blocked = runner.invoke(app, ["show"])
    assert blocked.exit_code != 0
    assert "plain text" in blocked.output and "bastet secret lock" in blocked.output

    # the excepted commands still work while a secret is unlocked
    still_works = runner.invoke(app, ["secret", "set", "lab", "another_token"], input=f"{SENTINEL}\n{SENTINEL}\n")
    assert still_works.exit_code == 0, still_works.output


def test_unlock_refuses_when_obsidian_sync_is_on(runner, secret_keys, inventory):
    sp = SecretPath.parse("lab/dns_token")
    _seed_note(inventory, sp, SENTINEL, secret_keys["pub"])
    (inventory / ".obsidian").mkdir()
    (inventory / ".obsidian" / "core-plugins.json").write_text('["sync"]')

    result = runner.invoke(app, ["secret", "unlock"])
    assert result.exit_code != 0
    assert "Sync" in result.output
    assert SecretNote.load(inventory, sp).is_sealed


def test_unlock_refuses_when_obsidian_git_autosaves(runner, secret_keys, inventory):
    sp = SecretPath.parse("lab/dns_token")
    _seed_note(inventory, sp, SENTINEL, secret_keys["pub"])
    plugin_dir = inventory / ".obsidian" / "plugins" / "obsidian-git"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "data.json").write_text('{"autoSaveInterval": 1}')

    result = runner.invoke(app, ["secret", "unlock"])
    assert result.exit_code != 0
    assert "obsidian-git" in result.output.lower() or "auto-commit" in result.output.lower()
    assert SecretNote.load(inventory, sp).is_sealed


def test_inventory_lists_while_a_secret_is_unlocked(runner, secret_keys, inventory, interactive):
    runner.invoke(app, ["secret", "set", "lab", "dns_token"], input="e\n")
    result = runner.invoke(app, ["secret"])
    assert result.exit_code == 0, result.output
    assert "lab/dns_token" in result.output and "unlocked" in result.output
