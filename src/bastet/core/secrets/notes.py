"""The secret note model: path layout, frontmatter and the one-armor-block body."""

import re
from dataclasses import dataclass, field
from pathlib import Path

from bastet.core.frontmatter import new_document, parse_document
from bastet.core.links import make_link
from bastet.core.secrets.crypto import SecretError

ARMOR_BLOCK = re.compile(r"-----BEGIN AGE ENCRYPTED FILE-----\n[A-Za-z0-9+/=\n]+-----END AGE ENCRYPTED FILE-----")
ARMOR_WHOLE = re.compile(r"^-----BEGIN AGE ENCRYPTED FILE-----\n[A-Za-z0-9+/=\n]+-----END AGE ENCRYPTED FILE-----$")

# Frontmatter fields in spec order (15.1); every field is always written.
FIELD_ORDER = (
    "bastet",
    "store",
    "applies_to",
    "role",
    "option",
    "source",
    "created",
    "rotated",
    "rotates",
    "rotation",
    "rotate_every",
    "expires",
    "standalone",
    "locked",
)


def _applies_to_link(applies_to: str) -> str:
    if applies_to.lower() == "lab":
        return make_link("Homelab")
    return make_link(applies_to)


@dataclass(frozen=True)
class SecretPath:
    host: str
    role: str | None
    name: str

    @property
    def rel(self) -> str:
        parts = ["_secrets", self.host]
        if self.role:
            parts.append(self.role)
        parts.append(f"{self.name}.md")
        return "/".join(parts)

    @property
    def text(self) -> str:
        parts = [self.host]
        if self.role:
            parts.append(self.role)
        parts.append(self.name)
        return "/".join(parts)

    @classmethod
    def parse(cls, text: str) -> "SecretPath":
        parts = text.split("/")
        if len(parts) == 2:
            return cls(parts[0], None, parts[1])
        if len(parts) == 3:
            return cls(parts[0], parts[1], parts[2])
        raise SecretError(f"{text!r} isn't a secret path (host/name or host/role/name)")

    @classmethod
    def from_cli(cls, words: list[str]) -> "SecretPath":
        return cls.parse("/".join(words))


@dataclass
class SecretNote:
    path: SecretPath
    data: dict = field(default_factory=dict)
    body: str = ""

    @classmethod
    def new(
        cls,
        sp: SecretPath,
        *,
        source: str,
        created: str,
        applies_to: str,
        rotate_every: str | None = None,
        expires: str | None = None,
        standalone: bool = False,
        rotates: bool = True,
    ) -> "SecretNote":
        data = {
            "bastet": "secret",
            "store": "age",
            "applies_to": _applies_to_link(applies_to),
            "role": sp.role,
            "option": sp.name,
            "source": source,
            "created": created,
            "rotated": None,
            "rotates": rotates,
            "rotation": None,
            "rotate_every": rotate_every,
            "expires": expires,
            "standalone": standalone,
            "locked": True,
        }
        return cls(path=sp, data=data, body="")

    @classmethod
    def load(cls, root: Path, sp: SecretPath) -> "SecretNote":
        path = root / sp.rel
        doc = parse_document(path.read_text(encoding="utf-8"), path)
        if doc is None:
            raise SecretError(f"{path}: not a Bastet note (no frontmatter)")
        return cls(path=sp, data=doc.data, body=doc.body)

    def write(self, root: Path) -> None:
        path = root / self.path.rel
        path.parent.mkdir(parents=True, exist_ok=True)
        ordered = {key: self.data.get(key, "") for key in FIELD_ORDER}
        for key, value in self.data.items():
            if key not in ordered:
                ordered[key] = value
        body = self.body if self.body.endswith("\n") else self.body + "\n"
        path.write_text(new_document(ordered, body), encoding="utf-8")

    @property
    def is_sealed(self) -> bool:
        return bool(ARMOR_WHOLE.fullmatch(self.body.strip()))

    @property
    def extra_text(self) -> str:
        match = ARMOR_BLOCK.search(self.body)
        if match is None:
            return self.body.strip()
        return (self.body[: match.start()] + self.body[match.end() :]).strip()


def _path_from_parts(parts: tuple[str, ...]) -> SecretPath:
    if len(parts) == 2:
        return SecretPath(parts[0], None, parts[1])
    if len(parts) == 3:
        return SecretPath(parts[0], parts[1], parts[2])
    raise SecretError(f"{'/'.join(parts)!r} isn't a secret path (host/name or host/role/name)")


def all_notes(root: Path) -> list[SecretNote]:
    base = root / "_secrets"
    if not base.exists():
        return []
    notes = []
    for path in sorted(base.rglob("*.md")):
        rel = path.relative_to(base)
        sp = _path_from_parts(rel.with_suffix("").parts)
        notes.append(SecretNote.load(root, sp))
    return notes
