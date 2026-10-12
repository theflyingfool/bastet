"""The generic builder: turns a Markdown role's merged values into engine resources, from the role's file entries."""

from __future__ import annotations

import re
import shlex
from dataclasses import replace

from bastet.core.errors import BastetError
from bastet.core.osinfo import ARCH_LIKE
from bastet.engine.command import Command
from bastet.engine.files import Block, File, Settings
from bastet.engine.model import Resource
from bastet.engine.run import Batch
from bastet.roles import entries, expr
from bastet.roles.contract import Option, RoleDef


def _matches(name: str, host) -> bool:
    if name == "arch":
        return host.os_id in ARCH_LIKE
    if name == "debian":
        return host.debian_like
    return host.os_id == name


def _check_os(role: RoleDef, host) -> None:
    if role.os and not any(_matches(name, host) for name in role.os):
        family = role.os[0]
        raise BastetError(f"{role.name} role: {host.name} isn't {family.capitalize()}-based "
                          f"({host.data.get('os') or 'OS unknown'}); aim it at [[{family}]]")


def _keyed(role: RoleDef, values: dict):
    """The options that name a key in the file and have a value, in contract order."""
    for name, option in role.options.items():
        if option.key and values.get(name) is not None:
            value = values[name]
            for text in value if isinstance(value, (list, tuple)) else [value]:
                if isinstance(text, str) and ("\n" in text or "\r" in text):
                    raise BastetError(f"{role.name}.{name}: a value can't contain a line break")
            yield option, value


def _kind(option: Option) -> str:
    return option.as_ or {"bool": "flag", "list": "list"}.get(option.type, "value")


def _ini_line(option: Option, value: object) -> str | None:
    """The line to write, or None when the option is switched off (a false flag, an empty list)."""
    key, kind = option.key, _kind(option)
    if kind == "flag":
        return key if value else None
    if kind == "list":
        return f"{key} = {' '.join(str(v) for v in value)}" if value else None
    return f"{key} = {value}"


def _ini(role: RoleDef, values: dict, entry: dict) -> list[Resource]:
    sections: dict[str, tuple[list[str], list[str]]] = {}
    for name, option in role.options.items():
        if option.key and not option.section:
            if values.get(name) is not None:
                raise BastetError(f"{role.name}.{name}: edit: ini needs a section")
    for option in role.options.values():
        if option.key and option.section:
            sections.setdefault(option.section, ([], []))
    for option, value in _keyed(role, values):
        keys, lines = sections[option.section]
        keys.append(option.key)
        if (text := _ini_line(option, value)) is not None:
            lines.append(text)
    return [Settings(path=entry["path"], section=section, keys=tuple(keys), lines=tuple(lines), validate=entry.get("validate"))
            for section, (keys, lines) in sections.items() if keys]


def _sq(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def _quote(value: object) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _apt_line(option: Option, value: object) -> str:
    key = option.key
    if isinstance(value, bool):
        return f'{key} "{"true" if value else "false"}";'
    if isinstance(value, (list, tuple)):
        return f"{key} {{ {' '.join(_quote(v) + ';' for v in value)} }};" if value else f"{key} {{ }};"
    return f"{key} {_quote(value)};"


def _apt(role: RoleDef, values: dict, entry: dict) -> list[Resource]:
    lines = ["# Managed by Bastet (apt role). Edit the role file, not this file."]
    lines += [_apt_line(option, value) for option, value in _keyed(role, values)]
    return [File(path=entry["path"], content="\n".join(lines) + "\n", mode=entry.get("mode"), owner=entry.get("owner"),
                 group=entry.get("group"), validate=entry.get("validate"))]


NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


def _entry_values(role: RoleDef, option_name: str, option: Option, item: dict) -> dict:
    """One list item with its defaults applied, checked for a usable name and for line breaks."""
    values = {name: item.get(name) if item.get(name) is not None else field.default
              for name, field in option.items.fields.items()}
    name = values.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise BastetError(f"{role.name}.{option_name}: {name!r} isn't a usable name")
    for field_name, field in option.items.fields.items():
        if field.as_ == "text":
            continue
        value = values[field_name]
        for text in value if isinstance(value, (list, tuple)) else [value]:
            if isinstance(text, str) and ("\n" in text or "\r" in text):
                raise BastetError(f"{role.name}.{option_name}.{field_name}: a value can't contain a line break")
    return values


def _keyed_fields(option: Option, values: dict):
    for name, field in option.items.fields.items():
        if field.key and values.get(name) is not None:
            yield field, values[name]


def _deb822_value(field: Option, value: object) -> str | None:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple)):
        return " ".join(str(v) for v in value) or None
    text = str(value)
    if field.as_ == "text" and ("\n" in text.strip("\n")):
        return "".join("\n " + (line if line.strip() else ".") for line in text.strip("\n").splitlines())
    return text.strip("\n") or None


def _deb822(option: Option, name: str, values: dict) -> list[Resource]:
    lines = []
    for field, value in _keyed_fields(option, values):
        if (text := _deb822_value(field, value)) is not None:
            lines.append(f"{field.key}:{'' if text.startswith(chr(10)) else ' '}{text}")
    return [File(path=option.path.format(name=name), content="\n".join(lines) + "\n", mode="0644")]


def _ini_section(option: Option, name: str, values: dict) -> list[Resource]:
    lines = [f"[{name}]"]
    for field, value in _keyed_fields(option, values):
        if field.as_ == "lines":
            lines += [f"{field.key} = {v}" for v in value]
        elif isinstance(value, (list, tuple)):
            if value:
                lines.append(f"{field.key} = {' '.join(str(v) for v in value)}")
        else:
            lines.append(f"{field.key} = {value}")
    if values.get("enabled") is False:
        lines = [f"#{line}" for line in lines]
    return [Block(path=option.path, block="\n".join(lines), marker=(option.marker or "{name}").format(name=name))]


ENTRY_FORMATS = {"deb822": _deb822, "ini_section": _ini_section}


def _entries(role: RoleDef, values: dict, secret: bool = False) -> list[Resource]:
    """The files for every option declared `as: entries`: one resource per list item."""
    out: list[Resource] = []
    for option_name, option in role.options.items():
        if option.as_ != "entries":
            continue
        for item in values.get(option_name) or []:
            fields = _entry_values(role, option_name, option, item)
            made = ENTRY_FORMATS[option.format](option, fields["name"], fields)
            out += [_placed(r, role, {"before": option.before, "after": option.after}, secret) for r in made]
    return out


RENDERERS = {"apt": _apt}
EDITORS = {"ini": _ini}


def build(role: RoleDef, values: dict, host, secret_options: frozenset = frozenset(),
          origins: dict[str, str] | None = None) -> list[Batch]:
    # Any secret option may have reached a file this role edits, renders or writes as entries, so those are marked.
    secret = bool(secret_options)
    _check_os(role, host)
    resources: list[Resource] = []
    ctx = expr.context(role.options, values, host, origins)
    notes = entries.run_checks(role, ctx)  # first, so an error check stops the host before anything is planned
    for i, entry in enumerate(role.entries):
        resources += entries.build_each(role, entry, f"files[{i}]", ctx,
                                        lambda c, entry=entry, i=i: _file(role, values, entry, i, c, secret_options))
    resources += _entries(role, values, secret)
    resources += entries.build_entries(role, ctx, host, secret_options, notes)
    resources += _commands(role, ctx)
    return [Batch(role.name, resources, notes)]


def _file(role: RoleDef, values: dict, entry: dict, i: int, ctx: dict, secret_options: frozenset) -> list[Resource]:
    """The resources of one `files` entry (for one item of its `each`)."""
    secret = bool(secret_options)
    r = entries.resolved_files_entry(role, entry, i, ctx)
    out: list[Resource] = []
    if entry.get("backup"):
        path = r["path"]
        out.append(Command(
            name=f"back up {path}", run=f"cp -p {shlex.quote(path)} {shlex.quote(path + '.bastet-orig')}", run_before="repositories",
            unless=f"test -e {_sq(path + '.bastet-orig')} || ! test -f {_sq(path)} || "
                   f"grep -q -e 'Bastet Managed' -e 'Managed by Bastet' {_sq(path)}"))
    if "edit" in entry or "render" in entry:
        made = EDITORS[entry["edit"]](role, values, r) if "edit" in entry else RENDERERS[entry["render"]](role, values, r)
        return out + [replace(_placed(x, role, entry, secret), **entries.triggers(r)) for x in made]
    return out + entries.build_files(role, ctx, entry, i, secret_options, r)


def _commands(role: RoleDef, ctx: dict) -> list[Resource]:
    """The role's commands whose `when` condition (if any) holds, one per item for a looped command."""
    out: list[Resource] = []
    for i, c in enumerate(role.commands):
        def make(item_ctx: dict, c: dict = c) -> list[Resource]:
            text = {k: str(expr.resolve(c[k], item_ctx)) if "each" in c else c[k] for k in ("name", "run", "unless")}
            return [Command(**text, run_before=c.get("before"), run_after=c.get("after"))]

        out += entries.build_each(role, c, f"commands[{i}]", ctx, make)
    return out


def _placed(resource: Resource, role: RoleDef, entry: dict, secret: bool = False) -> Resource:
    placed = entries.placed(resource, role, entry)
    return replace(placed, secret=True) if secret else placed
