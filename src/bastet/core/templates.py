"""Generate Obsidian templates for hosts, hardware, and other inventory items.

Templates are stored in the inventory's _templates/ folder and used with Obsidian's
built-in Templates plugin ("Templates: Insert template" command). Bastet owns these files
and rewrites them on refresh to keep them in sync with current types and categories.
"""

from bastet.core.hosttypes import HostType
from bastet.core.hardware import HARDWARE_CATEGORIES, HARDWARE_YOURS
from bastet.core.yamlstyle import dump_frontmatter


def templates_for_inventory(types: dict[str, HostType]) -> dict[str, str]:
    """Generate all templates for the inventory: one per host type, hardware category, and other kinds.

    Returns a dict mapping template filename to its full Markdown content.
    Templates are plain Markdown with frontmatter but no `generated: true` marker,
    so they can be inserted into user notes without marking those notes as Bastet-generated.
    """
    templates: dict[str, str] = {}

    # Host templates: one per type
    for type_name in sorted(types.keys()):
        type_def = types[type_name]
        templates[f"Host - {type_name}.md"] = _host_template(type_name, type_def)

    # Hardware templates: one per category
    for category in sorted(HARDWARE_CATEGORIES):
        templates[f"Hardware - {category}.md"] = _hardware_template(category)

    # Other kinds
    templates["Role file.md"] = _role_file_template()
    templates["Group.md"] = _group_template()
    templates["Location.md"] = _location_template()

    # README explaining that these are Bastet-owned
    templates["README.md"] = _readme_template()

    return templates


def _host_template(type_name: str, type_def: HostType) -> str:
    """Template for a host of the given type."""
    data = {
        "bastet": "host",
        "cssclasses": ["bastet-host"],
        "type": type_name,
        "gather": type_def.gather,
    }

    # Add fields that are marked as "yours" for this type
    for field_name, nature in sorted(type_def.fields.items()):
        if nature == "yours":
            data[field_name] = ""

    # Add provider field for types that require or can use it
    if "provider" in type_def.minimal:
        data["provider"] = ""

    # Add hostname by default
    if "hostname" not in data:
        data["hostname"] = ""

    frontmatter = dump_frontmatter(data)
    body = _explain_host_fields(type_def)
    return f"---\n{frontmatter}---\n{body}"


def _explain_host_fields(type_def: HostType) -> str:
    """Explain the fields in a host template."""
    lines = [
        f"# {type_def.name} - <hostname>\n",
        f"{type_def.description}\n",
        "Docs: [[Hosts and facts]]\n",
        "## About this template\n",
        "Edit this note's properties (frontmatter) to set up the host. The text below is for reference.\n",
    ]

    yours_fields = {f: type_def.fields.get(f) == "yours" for f in type_def.fields}
    yours_list = [f for f, is_yours in yours_fields.items() if is_yours]

    if yours_list:
        lines.append("\n### Your settings\n")
        for field in sorted(yours_list):
            lines.append(f"- `{field}`: (yours to set)\n")

    lines.append("\n### Gathered facts\n")
    lines.append("Bastet will fill these automatically when it gathers facts from the host:\n")
    fact_fields = [f for f, nature in type_def.fields.items() if nature == "fact"]
    for field in sorted(fact_fields):
        lines.append(f"- `{field}`\n")

    if type_def.minimal:
        lines.append(f"\n### Required fields\n")
        lines.append(f"This host type requires: {', '.join(type_def.minimal)}\n")

    return "".join(lines) + "\n"


def _hardware_template(category: str) -> str:
    """Template for a hardware item of the given category."""
    data = {
        "bastet": "hardware",
        "category": category,
        "status": "",  # placeholder
    }

    # Add all user-editable hardware fields
    for field in HARDWARE_YOURS:
        data[field] = ""

    frontmatter = dump_frontmatter(data)
    body = _explain_hardware_fields(category)
    return f"---\n{frontmatter}---\n{body}"


def _explain_hardware_fields(category: str) -> str:
    """Explain the fields in a hardware template."""
    lines = [
        f"# <hardware name>\n",
        f"Category: {category}\n",
        "Docs: [[Hardware]]\n",
        "\n## About this template\n",
        "Edit this note's properties to document a hardware item. The text below is for reference.\n",
        "\n### Your information\n",
        "- `status`: in-service, spare, failed, retired, or sold\n",
        "- `model`: make and model of the hardware\n",
        "- `serial`: serial number (for identification)\n",
        "- `size`: capacity or specification (e.g., \"4 TB\", \"32 GB\")\n",
        "- `price`: purchase price\n",
        "- `vendor`: where you bought it\n",
        "- `purchased`: purchase date\n",
        "- `location`: physical location in your lab\n",
        "- `warranty_until`: warranty expiration date\n",
        "- `notes`: any additional information\n",
        "\n### Installation\n",
        "- `installed_in`: [[host]] where this hardware is currently installed (optional)\n",
    ]
    return "".join(lines) + "\n"


def _role_file_template() -> str:
    """Template for a role file."""
    data = {
        "bastet": "role",
        "role": "<role name>",
        "applies_to": "[[<host or group>]]",
    }
    frontmatter = dump_frontmatter(data)
    body = """# <role name> for <target>

Docs: [[Roles]]

Values go in this note's properties (the frontmatter at the top), not in the page text below.

## Examples

Place examples here.

## Options

Place role options here.
"""
    return f"---\n{frontmatter}---\n{body}"


def _group_template() -> str:
    """Template for a group (a set of hosts matching a criterion)."""
    data = {
        "bastet": "group",
        "match": {"os": "<os-identifier>"},
    }
    frontmatter = dump_frontmatter(data)
    body = """# <Group Name>

A group of hosts matching a criterion. Edit the `match` property to define which hosts belong here.

You can use `match: {os: ubuntu-24.04}` to match by OS, for example.

Roles can apply to groups: `applies_to: "[[<Group Name>]]"`
"""
    return f"---\n{frontmatter}---\n{body}"


def _location_template() -> str:
    """Template for a location (a physical place)."""
    data = {
        "bastet": "location",
    }
    frontmatter = dump_frontmatter(data)
    body = """# <Location Name>

A physical location in your lab (e.g., "Closet 1", "Office", "Rack 3").

You can link hosts and hardware to locations with `location: "[[<Location Name>]]"` in their properties.
"""
    return f"---\n{frontmatter}---\n{body}"


def _readme_template() -> str:
    """README for the _templates folder."""
    return """# _templates

This folder contains Bastet's templates for creating new notes in Obsidian.

## Using templates

In Obsidian, open a new note and run the command **"Templates: Insert template"** to insert one of these.
The templates are generated by Bastet and updated with each `bastet refresh`, so they stay in sync
with your host types and hardware categories.

## What's here

- **Host - <type>.md**: Templates for each host type (server, vps, laptop, etc.)
- **Hardware - <category>.md**: Templates for each hardware category (drive, memory, nic, etc.)
- **Role file.md**: Template for a new role configuration
- **Group.md**: Template for a group of hosts matching a criterion
- **Location.md**: Template for a physical location in your lab

## Editing notes

These templates themselves are managed by Bastet. To add or change a template, work with the source
in Bastet's codebase, not by editing these files directly.
"""
