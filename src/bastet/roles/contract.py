"""The role contract: role.yml option menus, validation and defaults."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import yaml

from bastet.core.errors import BastetError, did_you_mean
from bastet.core.frontmatter import parse_document
from bastet.core.osdefaults import check_accounts
from bastet.roles import entries as role_entries
from bastet.roles import expr

TYPES = ("string", "int", "number", "bool", "list", "map", "object", "any")  # any: checked by the role's builder
SECRET_PREFIX = "secret:"  # a reference, resolved and re-checked against the option's type later
RESERVED = {"bastet", "role", "applies_to", "priority", "cssclasses", "tags", "aliases", "rotate_every", "overrides"}
OPTION_KEYS = {"type", "description", "default", "choices", "items", "fields", "shorthand", "secret", "required",
               "generate", "source", "rotate_every", "key", "section", "as", "min", "max", "single_line",
               "format", "path", "marker", "before", "after", "merge_default", "requires", "conflicts", "choices_from"}
API_VERSIONS = (0,)
OPTION_AS = ("flag", "value", "list", "lines", "text", "entries")
ENTRY_FORMATS = ("deb822", "ini_section")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
ROLE_NOTE_RESERVED = {"uses", "needs", "contributes", "collects", "requires", "tags", "cssclasses", "types",
                      "not_types", "os_min", "data", "vars", "presets", "templates", "units", "hooks",
                      "source", "source_hash"}
ROLE_NOTE_KEYS = {"bastet", "name", "version", "api", "description", "os", "provides", "options", "examples", "files", "commands", "packages",
                  "systemd", "users", "accounts", "starter", "checks", "sections", "overrides"}
FILE_EDITS = ("ini",)
FILE_RENDERS = ("apt",)
FILE_FORMS = ("edit", "render", "content", "template", "directory", "link", "line", "block")
EDIT_RENDER_KEYS = {"path", "edit", "render", "mode", "owner", "group", "validate", "before", "after", "backup", "when", "restart", "reload", "daemon_reload", "on_change"}
FILE_KEYS = EDIT_RENDER_KEYS | {"content", "template", "directory", "link", "line", "match", "unique", "block", "marker", "comment", "each"}
FORM_KEYS = {
    "content": {"mode", "owner", "group", "validate", "restart", "reload", "daemon_reload", "on_change", "backup"},
    "template": {"mode", "owner", "group", "validate", "restart", "reload", "daemon_reload", "on_change", "backup"},
    "directory": {"mode", "owner", "group"},
    "link": set(),
    "line": {"match", "unique", "validate", "restart", "reload", "daemon_reload", "on_change"},
    "block": {"marker", "comment", "validate", "restart", "reload", "daemon_reload", "on_change"},
}
COMMAND_KEYS = {"name", "run", "unless", "when", "before", "after", "each"}
SECTION_BLOCKS = ("packages", "users", "files", "systemd", "commands")
SECTION_KEYS = {"name", "when", *SECTION_BLOCKS}
GENERATE_KINDS = ("password", "token")
SECRET_SOURCES = ("generated", "chosen", "issued")


@dataclass
class Option:
    type: str
    description: str = ""
    default: object = None
    choices: tuple | None = None
    choices_file: str | None = None  # the file in the role's folder the choices were read from (choices_from)
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
    format: str | None = None  # as: entries only: deb822 | ini_section, the file format of each entry
    path: str | None = None  # as: entries only: where entries are written; may contain {name}
    marker: str | None = None  # as: entries, ini_section only: the block marker; may contain {name}
    before: str | None = None  # as: entries only: the slot the entries are written before
    after: str | None = None  # as: entries only: the slot the entries are written after
    merge_default: bool = False  # map only: the default entries stay, the given entries merge over them
    requires: dict[str, tuple | None] = field(default_factory=dict)  # sibling -> allowed values (None: just set)
    conflicts: tuple[str, ...] = ()  # siblings that must not be set together with this one


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
    accounts: tuple[str, ...] = ()
    starter: dict = field(default_factory=dict)  # values `bastet add role` writes into a new note
    entries: list[dict] = field(default_factory=list)
    commands: list[dict] = field(default_factory=list)
    packages: list[dict] = field(default_factory=list)
    systemd: list[dict] = field(default_factory=list)
    users: list[dict] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    overrides: list[dict] = field(default_factory=list)  # role-level: {when, note, values}, checked when the role is read
    markdown: bool = False
    raw: dict = field(default_factory=dict)

    def new_note_values(self) -> dict:
        """What a new note for this role starts with: the starter, plus a `secret:<name>` reference for every
        required top-level secret option the starter leaves out (nested secret options need an explicit starter)."""
        values = copy.deepcopy(self.starter)
        for name, opt in self.options.items():
            if opt.secret and opt.required and name not in values:
                values[name] = f"{SECRET_PREFIX}{name}"
        return values


def _read_starter(role: RoleDef, value: object, path: Path) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise BastetError(f"role {role.name}: starter must be a map of option values", file=path, key="starter")
    role.starter = check_values(role, value, f"role {role.name} starter", file=path)


def _relations(where: str, raw: dict, path: Path) -> tuple[dict[str, tuple | None], tuple[str, ...]]:
    """Read `requires` (a list of names, or a map of name to the value or list of values it must have) and `conflicts`."""
    requires: dict[str, tuple | None] = {}
    given = raw.get("requires")
    if given is not None:
        if isinstance(given, list) and all(isinstance(n, str) for n in given):
            requires = dict.fromkeys(given)
        elif isinstance(given, dict) and all(isinstance(n, str) for n in given):
            for name, want in given.items():
                if want is None or isinstance(want, dict):
                    raise BastetError(f"{where}: requires {name} needs true, a value or a list of values", file=path)
                if isinstance(want, list) and not want:
                    raise BastetError(f"{where}: requires {name} needs at least one value", file=path, key="requires")
                requires[name] = tuple(want) if isinstance(want, list) else (want,)
        else:
            raise BastetError(f"{where}: requires must be a list of names or a map of name to value", file=path)
    conflicts = raw.get("conflicts")
    if conflicts is not None and not (isinstance(conflicts, list) and all(isinstance(n, str) for n in conflicts)):
        raise BastetError(f"{where}: conflicts must be a list of names", file=path)
    return requires, tuple(conflicts or ())


def _check_relation_names(where: str, siblings: dict[str, Option], path: Path) -> None:
    """Every name a requires or conflicts rule uses must be a sibling (and not the option itself)."""
    for name, opt in siblings.items():
        for kind, named in (("requires", opt.requires), ("conflicts", opt.conflicts)):
            for other in named:
                if other == name:
                    raise BastetError(f"{where}.{name}: {kind} names itself", file=path)
                if other not in siblings:
                    raise BastetError(f"{where}.{name}: {kind} names {other!r}, which isn't an option here "
                                      f"(options: {', '.join(siblings)})", file=path)
                if kind == "requires" and named[other] is not None:  # the wanted values, as the option itself reads them
                    try:
                        opt.requires[other] = tuple(check_value(siblings[other], want, f"{where}.{name}: requires {other}")
                                                    for want in named[other])
                    except BastetError as exc:
                        raise BastetError(exc.message, file=path, key=name) from None


def _read_choices_file(where: str, name: object, path: Path) -> tuple[str, ...]:
    """The values of a `choices_from` file: one per line, blank lines and `#` lines ignored, whitespace stripped."""
    if not isinstance(name, str) or not name.strip():
        raise BastetError(f"{where}: choices_from must be a file name in the role's folder", file=path, key="choices_from")
    folder = path.parent.resolve()
    target = (folder / name).resolve()
    if Path(name).is_absolute() or not target.is_relative_to(folder) or target == folder:
        raise BastetError(f"{where}: choices_from {name!r} must be a file inside the role's folder", file=path,
                          key="choices_from")
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise BastetError(f"{where}: can't read choices_from file {name!r}: {getattr(exc, 'strerror', None) or exc}",
                          file=path, key="choices_from") from None
    values = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
    if not values:
        raise BastetError(f"{where}: choices_from file {name!r} has no values", file=path, key="choices_from")
    seen: set[str] = set()
    repeated: set[str] = set()
    for value in values:
        if value in seen:
            repeated.add(value)
        seen.add(value)
    if repeated:  # name the first listed value that occurs more than once
        value = next(v for v in values if v in repeated)
        raise BastetError(f"{where}: choices_from file {name!r} lists {value!r} twice", file=path, key="choices_from")
    return tuple(values)


def _option(where: str, raw: object, path: Path, as_items: bool = False) -> Option:
    if not isinstance(raw, dict) or raw.get("type") not in TYPES:
        raise BastetError(f"{where}: an option needs a type ({', '.join(TYPES)})", file=path)
    if as_items:
        for rule in ("requires", "conflicts"):
            if rule in raw:
                raise BastetError(f"{where}: {rule} can't be used on the items of a list or map (it would be ignored); "
                                  "put it on the list or map option itself", file=path, key=rule)
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
    if raw.get("merge_default") and raw["type"] != "map":
        raise BastetError(f"{where}: merge_default only applies to map options", file=path)
    entries = raw.get("as") == "entries"
    for knob in ("format", "path", "marker", "before", "after"):
        if knob in raw and not entries:
            raise BastetError(f"{where}: {knob} only applies to as: entries", file=path)
    if entries:
        item_type = raw["items"].get("type") if isinstance(raw.get("items"), dict) else None
        if raw["type"] != "list" or item_type != "object":
            raise BastetError(f"{where}: as: entries needs a list of objects", file=path)
        if raw.get("format") not in ENTRY_FORMATS:
            raise BastetError(f"{where}: as: entries needs format ({', '.join(ENTRY_FORMATS)})", file=path)
        if not isinstance(raw.get("path"), str) or not raw["path"]:
            raise BastetError(f"{where}: as: entries needs a path", file=path)
        if "marker" in raw and raw["format"] != "ini_section":
            raise BastetError(f"{where}: marker only applies to ini_section", file=path)
        if "before" in raw and "after" in raw:
            raise BastetError(f"{where}: use before or after, not both", file=path)
    requires, conflicts = _relations(where, raw, path)
    from_file = raw.get("choices_from")
    if "choices_from" in raw:
        if "choices" in raw:
            raise BastetError(f"{where}: use choices or choices_from, not both", file=path, key="choices_from")
        item_type = raw["items"].get("type") if isinstance(raw.get("items"), dict) else None
        if raw["type"] != "string" and not (raw["type"] in ("list", "map") and item_type == "string"):
            raise BastetError(f"{where}: choices_from only applies to string options and lists or maps of strings",
                              file=path, key="choices_from")
        from_file_values = _read_choices_file(where, from_file, path)
    opt = Option(type=raw["type"], description=str(raw.get("description", "")), default=raw.get("default"),
                 choices=from_file_values if "choices_from" in raw else (tuple(raw["choices"]) if "choices" in raw else None),
                 choices_file=from_file if "choices_from" in raw else None, shorthand=raw.get("shorthand"),
                 secret=bool(raw.get("secret", False)), required=bool(raw.get("required", False)),
                 generate=generate, source=source, rotate_every=raw.get("rotate_every"),
                 key=raw.get("key"), section=raw.get("section"), as_=raw.get("as"), min=raw.get("min"),
                 max=raw.get("max"), single_line=bool(raw.get("single_line", False)),
                 format=raw.get("format"), path=raw.get("path"), marker=raw.get("marker"), before=raw.get("before"),
                 after=raw.get("after"), merge_default=bool(raw.get("merge_default", False)),
                 requires=requires, conflicts=conflicts)
    if opt.type in ("list", "map"):
        if "items" not in raw:
            raise BastetError(f"{where}: a {opt.type} option needs items", file=path)
        opt.items = _option(f"{where}[]", raw["items"], path, as_items=True)
        if "choices_from" in raw:  # on the list or map itself: its string items take the values
            opt.items.choices, opt.items.choices_file = opt.choices, opt.choices_file
    if opt.type == "object":
        opt.fields = {k: _option(f"{where}.{k}", v, path) for k, v in (raw.get("fields") or {}).items()}
        _check_relation_names(where, opt.fields, path)
    return opt


def _shipped_dir() -> Path:
    return Path(str(resources.files("bastet") / "data" / "roles"))


def _options_and_examples(name: str, raw: dict, path: Path) -> tuple[dict[str, Option], list[dict]]:
    options_raw = raw.get("options") or {}
    if not isinstance(options_raw, dict):
        raise BastetError(f"role {name}: options must be a map", file=path, key="options")
    options = {k: _option(f"{name}.{k}", v, path) for k, v in options_raw.items()}
    _check_relation_names(name, options, path)
    clash = RESERVED & set(options)
    if clash:
        raise BastetError(f"role {name}: option names reserved for role files: {sorted(clash)}", file=path)
    for taken in ("item", "key"):
        if taken in options:
            raise BastetError(f"role {name}: an option can't be called {taken!r}: inside an `each` entry that name "
                              "stands for the current entry", file=path, key=taken)
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


def _check_template(role_file: Path, name: str, allowed: set[str], where: str) -> None:
    """A role template must exist beside the role file and only name options and facts."""
    try:
        text = (role_file.parent / name).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise BastetError(f"{where}: can't read the template: {exc.strerror or exc}", file=role_file, key="template") from None
    try:
        expr.check_text(text, allowed, where)
    except BastetError as exc:
        raise BastetError(exc.message, file=role_file, key="template") from None


def _file_entry(path: Path, entry: object, options: dict[str, Option], index: int = 0) -> dict:
    if not isinstance(entry, dict):
        raise BastetError("each files entry must be a map", file=path, key="files")
    unknown = sorted(str(k) for k in set(entry) - FILE_KEYS)
    if unknown:
        raise BastetError(f"files entry: unknown key {', '.join(unknown)}", file=path, key=unknown[0])
    if not isinstance(entry.get("path"), str) or not entry["path"]:
        raise BastetError("files entry needs a path", file=path, key="path")
    forms = [f for f in FILE_FORMS if f in entry]
    if len(forms) != 1:
        raise BastetError("files entry needs exactly one of edit, render, content, template, directory, link, line or block",
                          file=path, key="files")
    form = forms[0]
    if "each" in entry and form in ("edit", "render"):
        raise BastetError(f"files entry: each doesn't apply to {form} (it is built from the options as a whole)", file=path, key="each")
    allowed = EDIT_RENDER_KEYS if form in ("edit", "render") else FORM_KEYS[form] | {"path", form, "when", "before", "after", "each"}
    for key in sorted(set(entry) - allowed):
        raise BastetError(f"files entry: {key} doesn't apply to {form}", file=path, key=key)
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
    if form == "directory" and entry["directory"] is not True:
        raise BastetError("files entry: directory must be true", file=path, key="directory")
    if form == "block" and not entry.get("marker"):
        raise BastetError("files entry: block needs a marker", file=path, key="marker")
    if form in ("content", "template", "link", "line", "block") and not isinstance(entry[form], str):
        raise BastetError(f"files entry: {form} must be text", file=path, key=form)
    if form == "template" and (entry["template"] in ("", ".", "..") or Path(entry["template"]).name != entry["template"]):
        raise BastetError("files entry: template must be a file in the role's own folder", file=path, key="template")
    for key in ("restart", "reload"):
        if key in entry and not (isinstance(entry[key], list) and all(isinstance(u, str) for u in entry[key])):
            raise BastetError(f"files entry: {key} must be a list of unit names", file=path, key=key)
    if "daemon_reload" in entry and not isinstance(entry["daemon_reload"], bool):
        raise BastetError("files entry: daemon_reload must be true or false", file=path, key="daemon_reload")
    if "on_change" in entry:
        items = entry["on_change"]
        if not (isinstance(items, list) and items and all(
                isinstance(c, dict) and set(c) == {"name", "run"}
                and all(isinstance(c[k], str) and c[k].strip() for k in ("name", "run")) for c in items)):
            raise BastetError("files entry: on_change must be a list of maps, each with a name and a run (both text)",
                              file=path, key="on_change")
    where = f"files[{index}]"
    try:
        role_entries.refuse_bastet_path(entry["path"], where)
    except BastetError as exc:
        raise BastetError(exc.message, file=path, key="path") from None
    names = role_entries.entry_names(entry, options, where, path, "each")
    if form == "template":
        _check_template(path, entry["template"], names, f"{where}.template ({entry['template']})")
    # edit/render keep their long-standing before/after (any name); only the new forms need a block slot
    checked = {k: v for k, v in entry.items() if k not in ("before", "after")} if form in ("edit", "render") else entry
    role_entries.check_common(checked, names, f"files[{index}]", path, "files")
    return dict(entry)


def _command_entry(path: Path, entry: object, options: dict[str, Option]) -> dict:
    if not isinstance(entry, dict):
        raise BastetError("each commands entry must be a map", file=path, key="commands")
    unknown = sorted(str(k) for k in set(entry) - COMMAND_KEYS)
    if unknown:
        raise BastetError(f"commands entry: unknown key {', '.join(unknown)}", file=path, key=unknown[0])
    for key in ("name", "run", "unless"):
        if not isinstance(entry.get(key), str) or not entry[key].strip():
            raise BastetError(f"commands entry needs a {key}", file=path, key="commands")
    for key in ("when", "before", "after", "each"):
        if key in entry and not isinstance(entry[key], str):
            raise BastetError(f"commands entry: {key} must be text", file=path, key="commands")
    if "before" in entry and "after" in entry:
        raise BastetError("commands entry: use before or after, not both", file=path, key="commands")
    names = role_entries.entry_names(entry, options, "commands entry", path, "commands")
    try:
        if "when" in entry:
            expr.check_when(entry["when"], names, "commands entry")
        if "each" in entry:  # text in a looped command is filled in per item
            for key in ("name", "run", "unless"):
                expr.check_text(entry[key], names, f"commands entry: {key}")
    except BastetError as exc:
        raise BastetError(exc.message, file=path, key="commands") from None
    return entry


def _section_lists(path: Path, section: object, options: dict[str, Option], here: str) -> dict[str, list[dict]]:
    """One section's entries, parsed like the role's own lists, each with the section's `when` ANDed into its own."""

    def fail(text: str) -> BastetError:
        return BastetError(f"{here}: {text}", file=path, key="sections")

    if not isinstance(section, dict):
        raise fail("each section is a map")
    if "sections" in section:
        raise fail("sections can't be nested")
    if unknown := sorted(str(k) for k in set(section) - SECTION_KEYS):
        raise fail(f"unknown key {', '.join(unknown)} (known: {', '.join(sorted(SECTION_KEYS))})")
    when = section.get("when")
    if "when" in section:
        if not isinstance(when, str) or not when.strip():
            raise fail("when must be text")
        try:
            expr.check_when(when, set(options), here)
        except BastetError as exc:
            raise BastetError(exc.message, file=path, key="sections") from None
    if "name" in section and not isinstance(section["name"], str):
        raise fail("name must be text")
    parsers = {
        "packages": lambda items: role_entries.parse_packages(path, items, options),
        "users": lambda items: role_entries.parse_users(path, items, options),
        "systemd": lambda items: role_entries.parse_systemd(path, items, options),
        "files": lambda items: [_file_entry(path, e, options, i) for i, e in enumerate(items)],
        "commands": lambda items: [_command_entry(path, e, options) for e in items],
    }
    out: dict[str, list[dict]] = {}
    for block in SECTION_BLOCKS:
        items = section.get(block) or []
        if not isinstance(items, list):
            raise fail(f"{block} must be a list")
        try:
            parsed = parsers[block](items)
        except BastetError as exc:
            raise BastetError(f"{here}: {exc.message}", file=path, key="sections") from None
        out[block] = [{**e, "when": f"({when}) and ({e['when']})" if "when" in e else f"({when})"} if when else e
                      for e in parsed]
    if not any(out.values()):
        raise fail("a section needs at least one entry (packages, users, files, systemd or commands)")
    return out


def _sections(path: Path, items: object, options: dict[str, Option]) -> dict[str, list[dict]]:
    """The entries of every section, per block, in listing order."""
    if not isinstance(items, list):
        raise BastetError("sections must be a list", file=path, key="sections")
    out: dict[str, list[dict]] = {block: [] for block in SECTION_BLOCKS}
    for i, section in enumerate(items):
        name = section.get("name") if isinstance(section, dict) else None
        here = f"sections[{i}]" + (f" ({name})" if isinstance(name, str) and name else "")
        for block, parsed in _section_lists(path, section, options, here).items():
            out[block] += parsed
    return out


def _role_overrides(role_name: str, items: object, options: dict[str, Option], path: Path) -> list[dict]:
    """The role's own `overrides:` as {"when", "note", "values"} entries (values checked like a note's, nulls kept)."""

    def fail(text: str) -> BastetError:
        return BastetError(f"role {role_name}: {text}", file=path, key="overrides")

    if items is None:
        return []
    if not isinstance(items, list):
        raise fail("overrides must be a list of entries like {when: ..., option: value}")
    names = set(options)
    out: list[dict] = []
    for i, entry in enumerate(items):
        here = f"overrides[{i}]"
        if not isinstance(entry, dict):
            raise fail(f"{here} must be a map like {{when: ..., option: value}}")
        when = entry.get("when")
        if not isinstance(when, str) or not when.strip():
            raise fail(f"{here} needs a when (text, an expression over the options, host and lab facts)")
        note = entry.get("note")
        try:
            expr.check_option_when(when, names, here)
            if "note" in entry:
                if not isinstance(note, str) or not note.strip():
                    raise BastetError(f"{here}: note must be text")
                expr.check_option_text(note, names, f"{here}: note")
        except BastetError as exc:
            raise fail(exc.message) from None
        values: dict = {}
        for key, value in entry.items():
            if key in ("when", "note"):
                continue
            if key not in options:
                suggestion = did_you_mean(str(key), list(options))
                raise fail(f"{here} names no option {key!r}" + (f"; {suggestion}" if suggestion else f" (options: {', '.join(options)})"))
            try:
                values[key] = None if value is None else check_value(options[key], value, f"{here}.{key} ({role_name}.{key})", keep_nulls=True)
            except BastetError as exc:
                raise fail(exc.message) from None
        out.append({"when": when, "note": note, "values": values})
    return out


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
        accounts = check_accounts(data.get("accounts"), f"role {name}", path)
        files = data.get("files") or []
        if not isinstance(files, list):
            raise BastetError("files must be a list", file=path, key="files")
        entries = [_file_entry(path, e, options, i) for i, e in enumerate(files)]
        commands = data.get("commands") or []
        if not isinstance(commands, list):
            raise BastetError("commands must be a list", file=path, key="commands")
        commands = [_command_entry(path, e, options) for e in commands]
        packages = role_entries.parse_packages(path, data.get("packages") or [], options)
        systemd = role_entries.parse_systemd(path, data.get("systemd") or [], options)
        users = role_entries.parse_users(path, data.get("users") or [], options)
        checks = role_entries.parse_checks(path, data.get("checks") or [], options)
        grouped = _sections(path, data.get("sections") or [], options)
        overrides = _role_overrides(name, data.get("overrides"), options, path)
        entries += grouped["files"]
        commands += grouped["commands"]
        packages += grouped["packages"]
        systemd += grouped["systemd"]
        users += grouped["users"]
    except BastetError as exc:
        if exc.line is None and exc.key in doc.key_lines:
            raise BastetError(exc.message, file=path, line=doc.key_lines[exc.key], key=exc.key) from None
        raise
    role = RoleDef(name, description, options, path, examples, api=data["api"], version=version, os=os_,
                   provides=provides, accounts=accounts, entries=entries, commands=commands, packages=packages,
                   systemd=systemd, users=users, checks=checks, overrides=overrides, markdown=True,
                   raw={k: data[k] for k in ROLE_NOTE_RESERVED if k in data})
    try:
        _read_starter(role, data.get("starter"), path)
    except BastetError as exc:
        raise BastetError(exc.message, file=path, line=doc.key_lines.get("starter"), key=exc.key) from None
    return role


def _parse_yml_role(path: Path) -> RoleDef:
    name = path.parent.name
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise BastetError(f"invalid role definition: {exc}".splitlines()[0], file=path) from None
    if "checks" in raw:
        raise BastetError("checks are for Markdown roles; a role.yml role can't have them", file=path, key="checks")
    options, examples = _options_and_examples(name, raw, path)
    accounts = check_accounts(raw.get("accounts"), f"role {name}", path)
    role = RoleDef(name, str(raw.get("description", "")), options, path, examples, accounts=accounts)
    _read_starter(role, raw.get("starter"), path)
    return role


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


def check_value(opt: Option, value: object, where: str, keep_nulls: bool = False) -> object:
    """Validate one value; returns it normalised (shorthand expanded, empty fields dropped).

    A null field or entry of an object or map is dropped, unless `keep_nulls` is set: note values keep it so that
    resolve() can clear it after the levels are merged. Items of a list are never merged one by one, so their nulls
    are always dropped."""
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
        return {str(k): v if v is None else check_value(opt.items, v, f"{where}.{k}", keep_nulls)
                for k, v in value.items() if keep_nulls or v is not None}
    elif opt.type == "object":
        if not isinstance(value, dict):
            raise BastetError(f"{where}: expected a map of fields, got {value!r}")
        unknown = sorted(str(k) for k in set(value) - set(opt.fields))
        if unknown:
            raise BastetError(f"{where}: unknown field {', '.join(unknown)} (known: {', '.join(opt.fields)})")
        missing = [k for k, f in opt.fields.items() if f.required and value.get(k) is None]
        if missing:
            raise BastetError(f"{where}: needs {', '.join(missing)}")
        return {k: v if v is None else check_value(opt.fields[k], v, f"{where}.{k}", keep_nulls)
                for k, v in value.items() if keep_nulls or v is not None}
    if opt.type in ("int", "number"):
        if opt.min is not None and value < opt.min:
            raise BastetError(f"{where}: must be {opt.min} or more")
        if opt.max is not None and value > opt.max:
            raise BastetError(f"{where}: must be {opt.max} or less")
    if opt.single_line and (not value.strip() or "\n" in value):
        raise BastetError(f"{where}: needs a single non-empty line")
    if opt.choices is not None and value not in opt.choices:
        if opt.choices_file:  # a long list: name the file, show at most the closest value
            hint = did_you_mean(str(value), [str(c) for c in opt.choices])
            raise BastetError(f"{where}: {value!r} isn't one of the values in {opt.choices_file}"
                              + (f"; {hint}" if hint else ""))
        raise BastetError(f"{where}: {value!r} isn't one of {', '.join(map(str, opt.choices))}")
    return value


def check_values(role: RoleDef, values: dict, where: str, file: Path | None = None) -> dict:
    """Validate a note's values. A null (`key:`) is kept: it opts out of an inherited value and is cleared by resolve()
    once the levels are merged. Unknown option names are refused even with a null."""
    out: dict = {}
    for key, value in values.items():
        if key in RESERVED:
            continue
        if key not in role.options:
            suggestion = did_you_mean(key, list(role.options.keys()))
            if suggestion:
                msg = f"{where}: {role.name} has no option {key!r}; {suggestion}"
            else:
                msg = f"{where}: {role.name} has no option {key!r} (options: {', '.join(role.options)})"
            raise BastetError(msg, file=file, key=key)
        if value is None:
            out[key] = None
            continue
        try:
            out[key] = check_value(role.options[key], value, f"{role.name}.{key}", keep_nulls=True)
        except BastetError as exc:
            raise BastetError(exc.message, file=file, key=key) from None
    return out


def check_overrides(role: RoleDef, overrides: object, where: str, file: Path | None = None) -> list[tuple[str, dict]]:
    """Validate a note's `overrides:` and return its entries as (when, checked values) pairs, in listing order."""

    def fail(text: str) -> BastetError:
        return BastetError(f"{where} note: {text}", file=file, key="overrides")

    if overrides is None:
        return []
    if not isinstance(overrides, list):
        raise fail("overrides must be a list of entries like {when: ..., option: value}")
    out: list[tuple[str, dict]] = []
    for i, entry in enumerate(overrides):
        here = f"overrides[{i}]"
        if not isinstance(entry, dict):
            raise fail(f"{here} must be a map like {{when: ..., option: value}}")
        when = entry.get("when")
        if not isinstance(when, str) or not when.strip():
            raise fail(f"{here} needs a when (text, an expression over host and lab facts)")
        try:
            expr.check_fact_when(when, set(role.options), here)
        except BastetError as exc:
            raise fail(exc.message) from None
        values: dict = {}
        for key, value in entry.items():
            if key == "when":
                continue
            if key not in role.options:
                suggestion = did_you_mean(str(key), list(role.options))
                raise fail(f"{here} names no option {key!r}" + (f"; {suggestion}" if suggestion else f" (options: {', '.join(role.options)})"))
            if value is None:
                values[key] = None
                continue
            try:
                values[key] = check_value(role.options[key], value, f"{here}.{key} ({role.name}.{key})", keep_nulls=True)
            except BastetError as exc:
                raise fail(exc.message) from None
        out.append((when, values))
    return out


def _has(value: object, allowed: tuple) -> bool:
    return any(value == a and isinstance(value, bool) == isinstance(a, bool) for a in allowed)


def _wanted(allowed: tuple) -> str:
    if len(allowed) == 1:
        one = allowed[0]
        return str(one).lower() if isinstance(one, bool) else str(one)
    return "one of " + ", ".join(str(a) for a in allowed)


def _check_siblings(siblings: dict[str, Option], given: dict, prefix: str, role: str, file: Path | None) -> None:
    """The requires/conflicts rules of the options (or fields) set in `given`, then those of nested objects."""
    for name, opt in siblings.items():
        value = given.get(name)
        if value is None:  # unset; false, 0, "" and [] count as set
            continue

        def fail(text: str, name: str = name) -> BastetError:
            return BastetError(f"{role}: {prefix}{name} {text}", file=file, key=(prefix or name).split(".")[0].split("[")[0])

        for other, allowed in opt.requires.items():
            have = given.get(other)
            if have is None or (allowed is not None and not _has(have, allowed)):
                need = "set" if allowed is None else _wanted(allowed)
                raise fail(f"needs {prefix}{other} to be {need}")
        for other in opt.conflicts:
            if given.get(other) is not None:
                raise fail(f"can't be set together with {prefix}{other}")
        _check_nested(opt, value, f"{prefix}{name}", role, file)


def _check_nested(opt: Option, value: object, here: str, role: str, file: Path | None) -> None:
    if opt.type == "object" and isinstance(value, dict):
        _check_siblings(opt.fields, value, f"{here}.", role, file)
    elif opt.type == "list" and isinstance(value, list):
        for i, item in enumerate(value):
            _check_nested(opt.items, item, f"{here}[{i}]", role, file)
    elif opt.type == "map" and isinstance(value, dict):
        for k, item in value.items():
            _check_nested(opt.items, item, f"{here}.{k}", role, file)


def check_relations(role: RoleDef, values: dict, file: Path | None = None) -> None:
    """Check the requires and conflicts rules on values as the notes wrote them (merged, before defaults)."""
    _check_siblings(role.options, values, "", role.name, file)


def _merged(default: object, given: object) -> object:
    if given is None:
        return copy.deepcopy(default)
    if not isinstance(default, dict) or not isinstance(given, dict):
        return given
    out = copy.deepcopy(default)
    for key, value in given.items():
        base = out.get(key)
        out[key] = {**base, **value} if isinstance(base, dict) and isinstance(value, dict) else value
    return out


def with_defaults(role: RoleDef, values: dict) -> dict:
    return {k: _merged(opt.default, values.get(k)) if opt.merge_default else values.get(k, opt.default)
            for k, opt in role.options.items()}
