import pyrage
import pytest

from bastet.core.secrets.crypto import SecretError
from bastet.core.secrets.notes import SecretNote, SecretPath
from bastet.core.secrets.store import AgeStore, for_note


@pytest.fixture
def age_key():
    identity = pyrage.x25519.Identity.generate()
    return identity, str(identity.to_public())


def test_age_store_round_trip(tmp_path, age_key):
    identity, pub = age_key
    store = AgeStore(recipients=[pub], identities=[identity])
    sp = SecretPath.parse("git1/gitea/admin_password")
    note = SecretNote.new(sp, source="chosen", created="2026-10-03T10:00", applies_to="git1")

    store.set(note, "v")
    note.write(tmp_path)

    loaded = SecretNote.load(tmp_path, sp)
    assert loaded.is_sealed
    assert loaded.extra_text == ""
    assert store.exists(loaded)
    assert store.get(loaded) == "v"


def test_for_note_unknown_store_raises(age_key):
    identity, pub = age_key
    store = AgeStore(recipients=[pub], identities=[identity])
    sp = SecretPath.parse("git1/gitea/admin_password")
    note = SecretNote.new(sp, source="chosen", created="2026-10-03T10:00", applies_to="git1")
    note.data["store"] = "vaultwarden"
    with pytest.raises(SecretError, match="store 'vaultwarden' isn't available yet"):
        for_note(note, {"age": store})


def test_for_note_dispatches_to_age(age_key):
    identity, pub = age_key
    store = AgeStore(recipients=[pub], identities=[identity])
    sp = SecretPath.parse("git1/gitea/admin_password")
    note = SecretNote.new(sp, source="chosen", created="2026-10-03T10:00", applies_to="git1")
    assert for_note(note, {"age": store}) is store
