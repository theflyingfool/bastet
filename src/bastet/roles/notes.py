"""Role notes Bastet writes on its own: the one text every new note has, and the default notes of the lab, a group, a host."""

from __future__ import annotations

from pathlib import Path

from bastet.core.changes import Change
from bastet.core.frontmatter import new_document
from bastet.core.links import make_link
from bastet.roles.contract import RoleDef

LAB_ROLES = ("packages",)  # written when the lab is created
GROUP_ROLES: tuple[str, ...] = ()  # written when a group is copied or created
HOST_ROLES: tuple[str, ...] = ()  # written when a host is added


def role_note_text(role_name: str, role: RoleDef, target_name: str) -> str:
    """A new role note for `target_name`: the role's starter values (or none) and a pointer to the docs."""
    values = role.new_note_values()
    line = ("These entries are listed so you can change them; delete any you do not need." if values
            else "No values set; this role uses its defaults.")
    body = f"Docs: [[Using roles]] · Options: ![[{role_name} role#Options]]\n\n{line}\n"
    data = {"bastet": "role", "role": role_name, "applies_to": make_link(target_name), **values}
    return new_document(data, body)


def default_role_notes(kind: str, folder: Path, target_name: str, roles: dict[str, RoleDef]) -> list[Change]:
    """The default notes for a new lab, group or host (`kind`), one per default role whose file doesn't exist yet."""
    names = {"lab": LAB_ROLES, "group": GROUP_ROLES, "host": HOST_ROLES}[kind]
    return [Change(folder / f"{name}.md", None, role_note_text(name, roles[name], target_name))
            for name in names if name in roles and not (folder / f"{name}.md").exists()]
