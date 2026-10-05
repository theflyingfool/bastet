"""The role contract: role.yml option menus, validation and defaults (spec 9.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import yaml

from bastet.core.errors import BastetError

TYPES = ("string", "int", "number", "bool", "list", "map", "object", "any")  # any: checked by the role's builder
SECRET_PREFIX = "secret:"  # a reference, resolved and re-checked against the option's type later (spec 15.1)
RESERVED = {"bastet", "role", "applies_to", "priority", "cssclasses", "tags", "aliases", "rotate_every"}
OPTION_KEYS = {"type", "description", "default", "choices", "items", "fields", "shorthand", "secret", "required",
               "generate", "source", "rotate_every"}
GENERATE_KINDS = ("password", "token")
SECRET_SOURCES = ("generated", "chosen", "issued")


@dataclass
class Option:
    type: str
    description: str = ""
    default: object = None
    choices: tuple | None = None
    items: Option | None = None
    fields: dict[str, Option] = field(default_factory=dict)
    shorthand: str | None = None
    secret: bool = False
    required: bool = False
    generate: dict | None = None  # {kind: password|token, length: int}; offered by `bastet secret set` (15.3)
    source: str | None = None  # generated | chosen | issued: this option's default `source` when set (15.1, 15.3)
    rotate_every: object = None  # a per-source map ({generated: 180d, ...}) or a bare duration; the weakest policy level (15.6)


@dataclass
class RoleDef:
    name: str
    description: str
    options: dict[str, Option]
    path: Path
    examples: list[dict] = field(default_factory=list)


def _option(where: str, raw: object, path: Path) -> Option:
    if not isinstance(raw, dict) or raw.get("type") not in TYPES:
        raise BastetError(f"{where}: an option needs a type ({', '.join(TYPES)})", file=path)
    unknown = set(raw) - OPTION_KEYS
    if unknown:
        raise BastetError(f"{where}: unknown keys {sorted(unknown)}", file=path)
    generate = raw.get("generate")
    if generate is not None and (not isinstance(generate, dict) or generate.get("kind") not in GENERATE_KINDS):
        raise BastetError(f"{where}: generate needs a kind ({', '.join(GENERATE_KINDS)})", file=path)
    source = raw.get("source")
    if source is not None and source not in SECRET_SOURCES:
        raise BastetError(f"{where}: source must be one of {', '.join(SECRET_SOURCES)}", file=path)
    opt = Option(type=raw["type"], description=str(raw.get("description", "")), default=raw.get("default"),
                 choices=tuple(raw["choices"]) if "choices" in raw else None, shorthand=raw.get("shorthand"),
                 secret=bool(raw.get("secret", False)), required=bool(raw.get("required", False)),
                 generate=generate, source=source, rotate_every=raw.get("rotate_every"))
    if opt.type in ("list", "map"):
        if "items" not in raw:
            raise BastetError(f"{where}: a {opt.type} option needs items", file=path)
        opt.items = _option(f"{where}[]", raw["items"], path)
    if opt.type == "object":
        opt.fields = {k: _option(f"{where}.{k}", v, path) for k, v in (raw.get("fields") or {}).items()}
    return opt


def _shipped_dir() -> Path:
    return Path(str(resources.files("bastet") / "data" / "roles"))


def load_roles(directory: Path | None = None) -> dict[str, RoleDef]:
    roles: dict[str, RoleDef] = {}
    for path in sorted((directory or _shipped_dir()).glob("*/role.yml")):
        name = path.parent.name
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise BastetError(f"invalid role definition: {exc}".splitlines()[0], file=path) from None
        options = {k: _option(f"{name}.{k}", v, path) for k, v in (raw.get("options") or {}).items()}
        clash = RESERVED & set(options)
        if clash:
            raise BastetError(f"role {name}: option names reserved for role files: {sorted(clash)}", file=path)
        examples = raw.get("examples") or []
        if not all(isinstance(e, dict) and isinstance(e.get("title"), str) and isinstance(e.get("yaml"), str)
                   for e in examples):
            raise BastetError(f"role {name}: each example needs a title and yaml text", file=path)
        roles[name] = RoleDef(name, str(raw.get("description", "")), options, path, examples)
    return roles


def check_value(opt: Option, value: object, where: str) -> object:
    """Validate one value; returns it normalised (shorthand expanded, empty fields dropped)."""
    if isinstance(value, str) and value.startswith(SECRET_PREFIX):
        return value  # unresolved reference: the real value is checked against this type once it's resolved
    if opt.type == "object" and opt.shorthand and isinstance(value, str):
        value = {opt.shorthand: value}
    if opt.type == "any":
        return value
    if opt.type == "string":
        if not isinstance(value, str):
            hint = ' (quote it, e.g. "0644")' if isinstance(value, int) and not isinstance(value, bool) else ""
            raise BastetError(f"{where}: expected text, got {value!r}{hint}")
    elif opt.type == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            raise BastetError(f"{where}: expected a whole number, got {value!r}")
    elif opt.type == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise BastetError(f"{where}: expected a number, got {value!r}")
    elif opt.type == "bool":
        if not isinstance(value, bool):
            raise BastetError(f"{where}: expected true or false, got {value!r}")
    elif opt.type == "list":
        if not isinstance(value, list):
            raise BastetError(f"{where}: expected a list, got {value!r}")
        return [check_value(opt.items, v, f"{where}[{i}]") for i, v in enumerate(value)]
    elif opt.type == "map":
        if not isinstance(value, dict):
            raise BastetError(f"{where}: expected a map, got {value!r}")
        return {str(k): check_value(opt.items, v, f"{where}.{k}") for k, v in value.items()}
    elif opt.type == "object":
        if not isinstance(value, dict):
            raise BastetError(f"{where}: expected a map of fields, got {value!r}")
        unknown = sorted(str(k) for k in set(value) - set(opt.fields))
        if unknown:
            raise BastetError(f"{where}: unknown field {', '.join(unknown)} (known: {', '.join(opt.fields)})")
        missing = [k for k, f in opt.fields.items() if f.required and value.get(k) is None]
        if missing:
            raise BastetError(f"{where}: needs {', '.join(missing)}")
        return {k: check_value(opt.fields[k], v, f"{where}.{k}") for k, v in value.items() if v is not None}
    if opt.choices is not None and value not in opt.choices:
        raise BastetError(f"{where}: {value!r} isn't one of {', '.join(map(str, opt.choices))}")
    return value


def check_values(role: RoleDef, values: dict, where: str, file: Path | None = None) -> dict:
    out: dict = {}
    for key, value in values.items():
        if key in RESERVED or value is None:
            continue
        if key not in role.options:
            raise BastetError(f"{where}: {role.name} has no option {key!r} (options: {', '.join(role.options)})",
                              file=file, key=key)
        try:
            out[key] = check_value(role.options[key], value, f"{role.name}.{key}")
        except BastetError as exc:
            raise BastetError(exc.message, file=file, key=key) from None
    return out


def with_defaults(role: RoleDef, values: dict) -> dict:
    return {k: values.get(k, opt.default) for k, opt in role.options.items()}
