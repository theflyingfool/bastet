"""Masks known secret values out of any text before it's shown, logged or committed (spec 15.8)."""

import json
import re
import shlex

MASK = "‹secret›"  # ‹secret›
# Below this, a value is left unmasked: masking 1-3 character strings (a single digit in a port
# number, an "x" in a flag) garbles ordinary output for no privacy benefit, and such short strings
# are too common to usefully identify as "the secret" anyway.
MIN_LENGTH = 4


class Redactor:
    """Collects decrypted values as they're read, then hides them in any later text."""

    def __init__(self) -> None:
        self._values: set[str] = set()
        self._protected: set[str] = set()

    def add(self, value: str) -> None:
        """Register `value`, every line of it (a multi-line secret used inside a larger file still gets
        masked line by line, since a diff can split it across lines), and the `shlex.quote`d and
        `json.dumps`d forms a value commonly appears in (a shell command, a rendered JSON body)."""
        if not value:
            return
        self._register(value)
        if "\n" in value:
            for line in value.splitlines():
                self._register(line)

    def _register(self, value: str) -> None:
        if len(value) < MIN_LENGTH:
            return
        self._values.add(value)
        quoted = shlex.quote(value)
        if quoted != value:
            self._values.add(quoted)
        dumped = json.dumps(value)
        inner = dumped[1:-1]  # json.dumps always wraps a string in double quotes; keep only the escaped body
        if inner and inner != value:
            self._values.add(inner)

    def protect(self, text: str) -> None:
        """A string that must never be masked even if it happens to collide with a registered secret
        value -- a secret's own path (`host/role/option`), or the words a hint like
        `bastet secret set host role option` is built from. Protecting it here, once, at the point a
        `SecretPath` or a hint is created, means every later `mask()` call -- wherever the text ends up --
        leaves it alone, without each call site having to know which parts of its message are safe.
        """
        if text and len(text) >= MIN_LENGTH:
            self._protected.add(text)

    def clear(self) -> None:
        """Forget every registered value and protected string (tests: a fresh Redactor per test)."""
        self._values.clear()
        self._protected.clear()

    def mask(self, text: str) -> str:
        if not text or not self._values:
            return text
        # Find every occurrence of every registered value (and protected string) in the ORIGINAL
        # text as a (start, end, is_protected) interval, longest-first so a longer match wins over
        # one of its own substrings at the same position. Then drop any value-interval that sits
        # wholly inside a protected one (so masking a value never eats into a protected string around
        # it), merge what's left, and rebuild the text in one pass. Doing it this way -- rather than
        # repeated str.replace, or splitting on protected spans first -- means a value that merely
        # *contains* a protected substring still gets masked in full, and position shifts from one
        # replacement never affect where the next one is found.
        spans: list[tuple[int, int, bool]] = []
        for protected in self._protected:
            spans.extend((m.start(), m.end(), True) for m in re.finditer(re.escape(protected), text))
        for value in self._values:
            spans.extend((m.start(), m.end(), False) for m in re.finditer(re.escape(value), text))
        if not spans:
            return text
        spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
        protected_ranges = [(s, e) for s, e, is_p in spans if is_p]

        def _overlaps_protected(s: int, e: int) -> bool:
            # Any overlap, not just full containment: a value that merely touches a protected span
            # (e.g. its path) is left alone entirely, rather than risk masking part of it.
            return any(s < pe and ps < e for ps, pe in protected_ranges)

        kept: list[tuple[int, int]] = []
        last_end = -1
        for start, end, is_protected in spans:
            if is_protected:
                continue
            if start < last_end:
                continue  # overlaps a longer/earlier match already kept
            if _overlaps_protected(start, end):
                continue
            kept.append((start, end))
            last_end = end
        if not kept:
            return text
        out = []
        pos = 0
        for start, end in sorted(kept):
            out.append(text[pos:start])
            out.append(MASK)
            pos = end
        out.append(text[pos:])
        return "".join(out)


# Every value decrypted in this process: the last line of defence for output that has no context at hand
# (the top-level error handler).
ACTIVE = Redactor()
