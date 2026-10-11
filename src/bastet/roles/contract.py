"""The role contract: role.yml option menus, validation and defaults."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import yaml

from bastet.core.errors import BastetError, did_you_mean
from bastet.core.frontmatter import parse_document

TYPES = ("string", "int", "number", "bool", "list", "map", "object", "any")  # any: checked by the role's builder
SECRET_PREFIX = "secret:"  # a reference, resolved and re-checked against the option's type later
RESERVED = {"bastet", "role", "applies_to", "priority", "cssclasses", "tags", "aliases", "rotate_every"}
OPTION_KEYS = {"type", "description", "default", "choices", "items", "fields", "shorthand", "secret", "required",
               "generate", "source", "rotate_every", "key", "section", "as", "min", "max", "single_line"}
API_VERSIONS = (0,)
OPTION_AS = ("flag", "value", "list")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
ROLE_NOTE_RESERVED = {"uses", "needs", "contributes", "collects", "requires", "tags", "cssclasses", "types",
                      "not_types", "os_min", "data", "vars", "presets", "packages", "templates", "units", "hooks",
                      "source", "source_hash"}
ROLE_NOTE_KEYS = {"bastet", "name", "version", "api", "description", "os", "provides", "options", "examples", "files"}
FILE_EDITS = ("ini",)
FILE_RENDERS = ("apt",)
FILE_KEYS = {"path", "edit", "render", "mode", "owner", "group", "validate", "before", "after", "backup"}
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
    key: str | None = None  # the key a Markdown role writes this option under in a file
    section: str | None = None  # the section that key belongs to
    as_: str | None = None  # flag | value | list: how the option is written
    min: int | float | None = None  # int/number only
    max: int | float | None = None  # int/number only
    single_line: bool = False  # string only: one non-empty line


@dataclass
class RoleDef:
    name: str
    description: str
    options: dict[str, Option]
    path: Path
    examples: list[dict] = field(default_factory=list)
    api: int | None = None
    version: str = "0.0.0"
    os: tuple[str, ...] = ()
    provides: tuple[str, ...] = ()
    entries: list[dict] = field(default_factory=list)
    markdown: bool = False
    raw: dict = field(default_factory=dict)


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
    if raw.get("as") is not None and raw["as"] not in OPTION_AS:
        raise BastetError(f"{where}: as must be one of {', '.join(OPTION_AS)}", file=path)
    for bound in ("min", "max"):
        if bound in raw:
            if raw["type"] not in ("int", "number"):
                raise BastetError(f"{where}: {bound} only applies to int and number options", file=path)
            if not isinstance(raw[bound], (int, float)) or isinstance(raw[bound], bool):
                raise BastetError(f"{where}: {bound} must be a number", file=path)
    if raw.get("single_line") is not None and raw["type"] != "string":
        raise BastetError(f"{where}: single_line only applies to string options", file=path)
    opt = Option(type=raw["type"], description=str(raw.get("description", "")), default=raw.get("default"),
                 choices=tuple(raw["choices"]) if "choices" in raw else None, shorthand=raw.get("shorthand"),
                 secret=bool(raw.get("secret", False)), required=bool(raw.get("required", False)),
                 generate=generate, source=source, rotate_every=raw.get("rotate_every"),
                 key=raw.get("key"), section=raw.get("section"), as_=raw.get("as"), min=raw.get("min"),
                 max=raw.get("max"), single_line=bool(raw.get("single_line", False)))
    if opt.type in ("list", "map"):
        if "items" not in raw:
            raise BastetError(f"{where}: a {opt.type} option needs items", file=path)
        opt.items = _option(f"{where}[]", raw["items"], path)
    if opt.type == "object":
        opt.fields = {k: _option(f"{where}.{k}", v, path) for k, v in (raw.get("fields") or {}).items()}
    return opt


def _shipped_dir() -> Path:
    return Path(str(resources.files("bastet") / "data" / "roles"))


def _options_and_examples(name: str, raw: dict, path: Path) -> tuple[dict[str, Option], list[dict]]:
    options_raw = raw.get("options") or {}
    if not isinstance(options_raw, dict):
        raise BastetError(f"role {name}: options must be a map", file=path, key="options")
    options = {k: _option(f"{name}.{k}", v, path) for k, v in options_raw.items()}
    clash = RESERVED & set(options)
    if clash:
        raise BastetError(f"role {name}: option names reserved for role files: {sorted(clash)}", file=path)
    examples = raw.get("examples") or []
    if not isinstance(examples, list) or not all(
            isinstance(e, dict) and isinstance(e.get("title"), str) and isinstance(e.get("yaml"), str)
            for e in examples):
        raise BastetError(f"role {name}: each example needs a title and yaml text", file=path)
    return options, examples


def _text_list(path: Path, key: str, value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise BastetError(f"{key} must be a flat list of text", file=path, key=key)
    return tuple(value)


def _file_entry(path: Path, entry: object) -> dict:
    if not isinstance(entry, dict):
        raise BastetError("each files entry must be a map", file=path, key="files")
    unknown = sorted(str(k) for k in set(entry) - FILE_KEYS)
    if unknown:
        raise BastetError(f"files entry: unknown key {', '.join(unknown)}", file=path, key=unknown[0])
    if not isinstance(entry.get("path"), str) or not entry["path"]:
        raise BastetError("files entry needs a path", file=path, key="path")
    if ("edit" in entry) == ("render" in entry):
        raise BastetError("files entry needs exactly one of edit or render", file=path, key="files")
    for kind, allowed in (("edit", FILE_EDITS), ("render", FILE_RENDERS)):
        if kind in entry and entry[kind] not in allowed:
            raise BastetError(f"files entry: {kind} must be one of {', '.join(allowed)}", file=path, key=kind)
    if "backup" in entry and not isinstance(entry["backup"], bool):
        raise BastetError("files entry: backup must be true or false", file=path, key="backup")
    if "edit" in entry and {"mode", "owner", "group"} & set(entry):
        raise BastetError("files entry: mode, owner and group don't apply to edit (the file keeps its own); use render for a whole file",
                          file=path, key="files")
    if "before" in entry and "after" in entry:
        raise BastetError("files entry: use before or after, not both", file=path, key="files")
    return dict(entry)


def parse_role(path: Path) -> RoleDef:
    """Read one Markdown role note ("<name> role.md"): the frontmatter is the contract."""
    doc = parse_document(path.read_text(encoding="utf-8"), path)
    if doc is None:
        raise BastetError("a role note needs frontmatter", file=path, line=1)
    data = doc.data

    def fail(msg: str, key: str) -> BastetError:
        return BastetError(msg, file=path, line=doc.key_lines.get(key), key=key)

    if data.get("bastet") != "role-definition":
        raise fail("needs bastet: role-definition", "bastet")
    name = path.parent.name
    if data.get("name") != name:
        raise fail(f"name must be {name!r}, the folder name", "name")
    version = data.get("version")
    if not isinstance(version, str) or not VERSION_RE.match(version):
        raise fail("version must look like 1.2.3", "version")
    if data.get("api") not in API_VERSIONS or isinstance(data.get("api"), bool):
        raise fail(f"api must be one of {', '.join(map(str, API_VERSIONS))}", "api")
    description = data.get("description")
    if not isinstance(description, str) or not description.strip():
        raise fail("needs a description", "description")
    unknown = sorted(str(k) for k in set(data) - ROLE_NOTE_KEYS - ROLE_NOTE_RESERVED)
    if unknown:
        raise fail(f"unknown key {', '.join(unknown)}", unknown[0])
    try:
        options, examples = _options_and_examples(name, data, path)
        os_ = _text_list(path, "os", data.get("os"))
        provides = _text_list(path, "provides", data.get("provides"))
        files = data.get("files") or []
        if not isinstance(files, list):
            raise BastetError("files must be a list", file=path, key="files")
        entries = [_file_entry(path, e) for e in files]
    except BastetError as exc:
        if exc.line is None and exc.key in doc.key_lines:
            raise BastetError(exc.message, file=path, line=doc.key_lines[exc.key], key=exc.key) from None
        raise
    return RoleDef(name, description, options, path, examples, api=data["api"], version=version, os=os_,
                   provides=provides, entries=entries, markdown=True,
                   raw={k: data[k] for k in ROLE_NOTE_RESERVED if k in data})


def _parse_yml_role(path: Path) -> RoleDef:
    name = path.parent.name
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise BastetError(f"invalid role definition: {exc}".splitlines()[0], file=path) from None
    options, examples = _options_and_examples(name, raw, path)
    return RoleDef(name, str(raw.get("description", "")), options, path, examples)


def load_roles(directory: Path | None = None) -> dict[str, RoleDef]:
    roles: dict[str, RoleDef] = {}
    root = directory or _shipped_dir()
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        note, legacy = folder / f"{folder.name} role.md", folder / "role.yml"
        if note.exists() and legacy.exists():
            raise BastetError(f"role {folder.name} has both '{note.name}' and role.yml; keep one", file=folder)
        if note.exists():
            roles[folder.name] = parse_role(note)
        elif legacy.exists():
            roles[folder.name] = _parse_yml_role(legacy)
    return roles


def _lenient(typ: str, value: object) -> object:
    """Lenient value parsing: convert string values to the expected type if possible.

    bool accepts "true"/"false"/"yes"/"no" (any case)
    int and number accept numeric text
    Returns the converted value on success, or the original value if not applicable.
    """
    if not isinstance(value, str):
        return value

    s = value.strip().lower()

    if typ == "bool":
        if s in {"true", "yes"}:
            return True
        if s in {"false", "no"}:
            return False
        return value  # invalid; let the normal check_value error

    if typ == "int":
        try:
            return int(value)
        except (ValueError, TypeError):
            return value  # invalid; let the normal check_value error

    if typ == "number":
        try:
            if "." in value or "e" in value.lower():
                return float(value)
            return int(value)
        except (ValueError, TypeError):
            return value  # invalid; let the normal check_value error

    return value


def check_value(opt: Option, value: object, where: str) -> object:
    """Validate one value; returns it normalised (shorthand expanded, empty fields dropped)."""
    if isinstance(value, str) and value.startswith(SECRET_PREFIX):
        return value  # unresolved reference: the real value is checked against this type once it's resolved
    # Lenient parsing: convert string values if applicable
    value = _lenient(opt.type, value)
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
    if opt.type in ("int", "number"):
        if opt.min is not None and value < opt.min:
            raise BastetError(f"{where}: must be {opt.min} or more")
        if opt.max is not None and value > opt.max:
            raise BastetError(f"{where}: must be {opt.max} or less")
    if opt.single_line and (not value.strip() or "\n" in value):
        raise BastetError(f"{where}: needs a single non-empty line")
    if opt.choices is not None and value not in opt.choices:
        raise BastetError(f"{where}: {value!r} isn't one of {', '.join(map(str, opt.choices))}")
    return value


def check_values(role: RoleDef, values: dict, where: str, file: Path | None = None) -> dict:
    out: dict = {}
    for key, value in values.items():
        if key in RESERVED or value is None:
            continue
        if key not in role.options:
            suggestion = did_you_mean(key, list(role.options.keys()))
            if suggestion:
                msg = f"{where}: {role.name} has no option {key!r}; {suggestion}"
            else:
                msg = f"{where}: {role.name} has no option {key!r} (options: {', '.join(role.options)})"
            raise BastetError(msg, file=file, key=key)
        try:
            out[key] = check_value(role.options[key], value, f"{role.name}.{key}")
        except BastetError as exc:
            raise BastetError(exc.message, file=file, key=key) from None
    return out


def with_defaults(role: RoleDef, values: dict) -> dict:
    return {k: values.get(k, opt.default) for k, opt in role.options.items()}
