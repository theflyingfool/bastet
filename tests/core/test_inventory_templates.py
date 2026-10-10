"""Templates for hosts, hardware, and other inventory items."""

import json
from pathlib import Path

import pytest

from bastet.core.frontmatter import parse_document
from bastet.core.inventory import load_inventory
from bastet.core.templates import templates_for_inventory
from bastet.core.hosttypes import load_host_types


def test_templates_include_every_host_type():
    """Every host type gets a template."""
    types = load_host_types()
    templates = templates_for_inventory(types)
    type_names = set(templates.keys())
    for type_name in types:
        assert f"Host - {type_name}.md" in type_names


def test_templates_include_every_hardware_category():
    """Every hardware category gets a template."""
    from bastet.core.hardware import HARDWARE_CATEGORIES
    types = load_host_types()
    templates = templates_for_inventory(types)
    template_names = set(templates.keys())
    for category in HARDWARE_CATEGORIES:
        assert f"Hardware - {category}.md" in template_names


def test_templates_include_other_kinds():
    """Templates for Role file, Group, and Location."""
    types = load_host_types()
    templates = templates_for_inventory(types)
    template_names = set(templates.keys())
    assert "Role file.md" in template_names
    assert "Group.md" in template_names
    assert "Location.md" in template_names


def test_templates_have_readme():
    """The README explains that templates are Bastet-owned."""
    types = load_host_types()
    templates = templates_for_inventory(types)
    assert "README.md" in templates
    readme = templates["README.md"]
    assert "Bastet" in readme or "bastet" in readme
    assert "generated" in readme.lower() or "own" in readme.lower()


def test_host_templates_parse_as_hosts(tmp_path):
    """Host templates can be loaded as host documents without error."""
    types = load_host_types()
    templates = templates_for_inventory(types)
    for name, content in templates.items():
        if not name.startswith("Host - "):
            continue
        path = tmp_path / "hosts" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    # Load and check they parse
    inv = load_inventory(tmp_path, types)
    for doc in inv.of_kind("host"):
        assert doc.data.get("type") in types


def test_hardware_templates_parse_as_hardware(tmp_path):
    """Hardware templates can be loaded as hardware documents without error."""
    from bastet.core.hardware import HARDWARE_CATEGORIES
    types = load_host_types()
    templates = templates_for_inventory(types)
    for name, content in templates.items():
        if not name.startswith("Hardware - "):
            continue
        path = tmp_path / "hardware" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    # Load and check they parse
    inv = load_inventory(tmp_path, types)
    for doc in inv.of_kind("hardware"):
        assert doc.data.get("category") in HARDWARE_CATEGORIES


def test_hardware_templates_have_all_user_fields():
    """Every hardware template includes all HARDWARE_YOURS fields."""
    from bastet.core.hardware import HARDWARE_YOURS
    types = load_host_types()
    templates = templates_for_inventory(types)
    for name, content in templates.items():
        if not name.startswith("Hardware - "):
            continue
        doc = parse_document(content, Path(name))
        assert doc is not None
        for field in HARDWARE_YOURS:
            assert field in doc.data, f"{name} missing {field}"


def test_templates_dont_load_as_inventory_docs(tmp_path):
    """Templates in _templates/ don't load as real documents in the inventory."""
    types = load_host_types()
    templates = templates_for_inventory(types)

    # Write all templates to _templates/
    templates_dir = tmp_path / "_templates"
    templates_dir.mkdir()
    for name, content in templates.items():
        (templates_dir / name).write_text(content, encoding="utf-8")

    # Load inventory and verify nothing from _templates loaded
    inv = load_inventory(tmp_path, types)
    for doc in inv.of_kind("host"):
        assert "_templates" not in str(doc.path)
    for doc in inv.of_kind("hardware"):
        assert "_templates" not in str(doc.path)


def test_host_template_content(tmp_path):
    """A host template has expected structure: bastet, cssclasses, type, gather, and yours fields."""
    types = load_host_types()
    templates = templates_for_inventory(types)

    server_template = templates["Host - server.md"]
    doc = parse_document(server_template, Path("Host - server.md"))
    assert doc is not None
    assert doc.data.get("bastet") == "host"
    assert "bastet-host" in doc.data.get("cssclasses", [])
    assert doc.data.get("type") == "server"
    assert "gather" in doc.data
    # Yours fields should be present
    for field in types["server"].fields:
        if types["server"].fields[field] == "yours":
            assert field in doc.data


def test_hardware_template_content():
    """A hardware template has expected structure."""
    types = load_host_types()
    templates = templates_for_inventory(types)

    drive_template = templates["Hardware - drive.md"]
    doc = parse_document(drive_template, Path("Hardware - drive.md"))
    assert doc is not None
    assert doc.data.get("bastet") == "hardware"
    assert doc.data.get("category") == "drive"
    # Should have hardware user fields
    from bastet.core.hardware import HARDWARE_YOURS
    for field in HARDWARE_YOURS:
        assert field in doc.data


def test_templates_dont_have_generated_marker():
    """Templates themselves should not have `generated: true` (user docs will get that)."""
    types = load_host_types()
    templates = templates_for_inventory(types)
    for name, content in templates.items():
        if name == "README.md":
            continue
        doc = parse_document(content, Path(name))
        assert doc is not None
        # Templates should NOT have generated marker; only README should
        assert doc.data.get("generated") is None or doc.data.get("generated") is False


def test_template_body_mentions_fields():
    """Template body explains the fields in the frontmatter."""
    types = load_host_types()
    templates = templates_for_inventory(types)

    server_template = templates["Host - server.md"]
    doc = parse_document(server_template, Path("Host - server.md"))
    assert doc is not None
    # Body should be non-empty and explain something
    assert doc.body.strip()
    # Should mention some key concepts
    body_lower = doc.body.lower()
    assert any(word in body_lower for word in ["field", "property", "gather", "bastet"])
