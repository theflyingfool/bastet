from pathlib import Path
from difflib import get_close_matches


def did_you_mean(word: str, candidates: list[str]) -> str:
    """Return a suggestion string for a typo, or empty string if no close matches.

    Uses difflib to find up to 3 close matches and formats them as:
    'did you mean `option1`?' or 'did you mean `option1`, `option2` or `option3`?'
    """
    matches = get_close_matches(word, candidates, n=3, cutoff=0.6)
    if not matches:
        return ""
    if len(matches) == 1:
        return f"did you mean `{matches[0]}`?"
    if len(matches) == 2:
        return f"did you mean `{matches[0]}` or `{matches[1]}`?"
    return f"did you mean `{matches[0]}`, `{matches[1]}` or `{matches[2]}`?"


class BastetError(Exception):
    """An error a user can act on: says what's wrong and where."""

    def __init__(
        self,
        message: str,
        *,
        file: Path | None = None,
        line: int | None = None,
        key: str | None = None,
    ) -> None:
        self.message = message
        self.file = file
        self.line = line
        self.key = key
        super().__init__(str(self))

    def __str__(self) -> str:
        parts = []
        if self.file is not None:
            parts.append(f"{self.file}:{self.line}" if self.line is not None else str(self.file))
        if self.key:
            parts.append(self.key)
        parts.append(self.message)
        return ": ".join(parts)


class Unreachable(BastetError):
    """The host could not be reached (network, DNS, SSH not answering)."""


class AuthFailed(BastetError):
    """The host answered but refused the login."""
