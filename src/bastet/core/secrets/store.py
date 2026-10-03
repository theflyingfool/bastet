"""The get/set/exists seam secret notes go through, so another store (15.9) can sit behind it."""

from dataclasses import dataclass
from typing import Protocol

from bastet.core.secrets.crypto import SecretError, open_sealed, seal
from bastet.core.secrets.notes import SecretNote


class Store(Protocol):
    def get(self, note: SecretNote) -> str: ...
    def set(self, note: SecretNote, value: str) -> SecretNote: ...
    def exists(self, note: SecretNote) -> bool: ...


@dataclass
class AgeStore:
    """The only store today: a note's body is a sealed age payload."""

    recipients: list[str]
    identities: list

    def get(self, note: SecretNote) -> str:
        return open_sealed(note.body.strip(), note.path.text, self.identities).value

    def set(self, note: SecretNote, value: str) -> SecretNote:
        note.body = seal(note.path.text, value, self.recipients)
        return note

    def exists(self, note: SecretNote) -> bool:
        return note.is_sealed


def for_note(note: SecretNote, ctx_stores: dict[str, Store]) -> Store:
    """Dispatch on `note.data["store"]`."""
    kind = note.data.get("store")
    store = ctx_stores.get(kind)
    if store is None:
        raise SecretError(f"store {kind!r} isn't available yet")
    return store
