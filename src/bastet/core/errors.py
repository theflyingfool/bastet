from pathlib import Path


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
