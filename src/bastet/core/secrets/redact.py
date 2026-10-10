"""Masks known secret values out of any text before it's shown, logged or committed."""

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
        # Snapshots: another thread may register a value while this one is masking.
        values, protected_strings = tuple(self._values), tuple(self._protected)
        # Find every occurrence of every registered value, and of every protected string, in the
        # ORIGINAL text as a (start, end, is_protected) interval. A value interval is dropped only
        # when it sits wholly inside a protected one -- e.g. a registered value that happens to equal
        # one word of a protected `bastet secret set host role option` hint -- never merely for
        # overlapping or touching one: a value that *contains* a protected substring (a secret's path
        # embedded inside a longer secret value) still gets masked in full, since leaving a real
        # secret completely unmasked would be the worse failure. What's left is merged into
        # non-overlapping ranges (so two overlapping value matches both get fully covered, not one
        # dropped and the other's tail left showing) and the text is rebuilt in one pass.
        protected_ranges = [
            (m.start(), m.end()) for protected in protected_strings for m in re.finditer(re.escape(protected), text)
        ]
        value_spans = sorted(
            (m.start(), m.end()) for value in values for m in re.finditer(re.escape(value), text)
        )
        if not value_spans:
            return text

        def _wholly_inside_protected(s: int, e: int) -> bool:
            return any(ps <= s and e <= pe for ps, pe in protected_ranges)

        merged: list[list[int]] = []
        for start, end in value_spans:
            if _wholly_inside_protected(start, end):
                continue
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        if not merged:
            return text
        out = []
        pos = 0
        for start, end in merged:
            out.append(text[pos:start])
            out.append(MASK)
            pos = end
        out.append(text[pos:])
        return "".join(out)


# Every value decrypted in this process: the last line of defence for output that has no context at hand
# (the top-level error handler).
ACTIVE = Redactor()
