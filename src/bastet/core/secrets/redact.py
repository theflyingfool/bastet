"""Masks known secret values out of any text before it's shown, logged or committed (spec 15.8)."""

MASK = "‹secret›"  # ‹secret›
MIN_LENGTH = 4


class Redactor:
    """Collects decrypted values as they're read, then hides them in any later text."""

    def __init__(self) -> None:
        self._values: set[str] = set()

    def add(self, value: str) -> None:
        if value and len(value) >= MIN_LENGTH:
            self._values.add(value)

    def mask(self, text: str) -> str:
        if not text or not self._values:
            return text
        for value in sorted(self._values, key=len, reverse=True):
            text = text.replace(value, MASK)
        return text
