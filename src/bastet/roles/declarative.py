"""The generic builder: turns a Markdown role's merged values into engine resources, from the role's file entries."""

from __future__ import annotations

from dataclasses import replace

from bastet.core.errors import BastetError
from bastet.core.osinfo import ARCH_LIKE
from bastet.engine.command import Command
from bastet.engine.files import File, Settings
from bastet.engine.model import Resource
from bastet.engine.run import Batch
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


RENDERERS = {"apt": _apt}
EDITORS = {"ini": _ini}


def build(role: RoleDef, values: dict, host) -> list[Batch]:
    _check_os(role, host)
    resources: list[Resource] = []
    for entry in role.entries:
        if entry.get("backup"):
            path = entry["path"]
            resources.append(Command(
                name=f"back up {path}", run=f"cp -p {path} {path}.bastet-orig", run_before="repositories",
                unless=f"test -e '{path}.bastet-orig' || ! test -f '{path}' || grep -q -e 'Bastet Managed' -e 'Managed by Bastet' '{path}'"))
        if "edit" in entry:
            made = EDITORS[entry["edit"]](role, values, entry)
        else:
            made = RENDERERS[entry["render"]](role, values, entry)
        resources += [_placed(r, role, entry) for r in made]
    return [Batch(role.name, resources)]


def _placed(resource: Resource, role: RoleDef, entry: dict) -> Resource:
    return replace(resource, run_before=entry.get("before"), run_after=entry.get("after"), provides=tuple(role.provides))
