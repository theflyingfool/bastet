from types import SimpleNamespace

import pytest

from bastet.cli.app import app
from bastet.cli.complete import complete_secret_words
from bastet.core.secrets import crypto
from bastet.core.secrets.notes import SecretNote, SecretPath
from conftest import git

SENTINEL = "SENTINEL-4242"


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


def test_bastet_secret_lists_without_values(runner, secret_keys, inventory):
    sp = SecretPath.parse("lab/dns_token")
    _seed_note(inventory, sp, SENTINEL, secret_keys["pub"])
    result = runner.invoke(app, ["secret"])
    assert result.exit_code == 0, result.output
    assert SENTINEL not in result.output
    assert "lab/dns_token" in result.output


def test_show_refuses_when_piped(runner, secret_keys, inventory):
    sp = SecretPath.parse("lab/dns_token")
    _seed_note(inventory, sp, SENTINEL, secret_keys["pub"])
    result = runner.invoke(app, ["secret", "show", "lab", "dns_token"])
    assert result.exit_code != 0
    assert SENTINEL not in result.output
    assert "terminal" in result.output


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


@pytest.mark.parametrize("words,incomplete,expected", [
    ((), "", ["box", "lab", "pve1"]),
    (("box",), "", ["testsecret"]),
    (("box", "testsecret"), "", ["admin_password", "db_password"]),
    (("box", "testsecret"), "admin", ["admin_password"]),
    (("no-such-host",), "", []),
])
def test_complete_secret_words(inventory, test_role, words, incomplete, expected):
    ctx = SimpleNamespace(params={"words": words})
    results = complete_secret_words(ctx, [], incomplete)
    for exp in expected:
        assert exp in results
    if not expected:
        assert results == []
