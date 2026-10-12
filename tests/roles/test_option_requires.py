from pathlib import Path

import pytest
import yaml

from bastet.core.errors import BastetError
from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from bastet.roles.contract import check_relations, parse_role
from bastet.roles.resolve import resolve

BASE = {"bastet": "role-definition", "name": "demo", "version": "1.2.3", "api": 0, "description": "A demo role"}
OPTIONS = {
    "ntp": {"type": "bool"},
    "mode": {"type": "string"},
    "servers": {"type": "list", "items": {"type": "string"}, "requires": {"ntp": True}},
    "pool": {"type": "string", "requires": ["ntp", "mode"], "conflicts": ["servers"]},
}


def write_role(tmp_path, options=None):
    folder = tmp_path / "roles" / "demo"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "demo role.md"
    path.write_text("---\n" + yaml.safe_dump({**BASE, "options": options or OPTIONS}, sort_keys=False) + "---\nNotes.\n")
    return path


def role(tmp_path, options=None):
    return parse_role(write_role(tmp_path, options))


def refused(tmp_path, options, *words):
    with pytest.raises(BastetError) as e:
        parse_role(write_role(tmp_path, options))
    text = str(e.value)
    assert "demo role.md" in text and "demo" in text
    for word in words:
        assert word in text


def test_a_rule_naming_a_missing_option_is_refused_at_read(tmp_path):
    refused(tmp_path, {"a": {"type": "bool", "requires": ["nope"]}}, "a", "nope")
    refused(tmp_path, {"a": {"type": "bool", "conflicts": ["nope"]}}, "a", "nope")
    refused(tmp_path, {"a": {"type": "bool", "requires": {"nope": True}}}, "a", "nope")


def test_a_rule_naming_a_missing_field_names_the_parent(tmp_path):
    opts = {"o": {"type": "object", "fields": {"x": {"type": "int", "requires": ["y"]}}}}
    refused(tmp_path, opts, "o.x", "y")


def test_a_rule_naming_itself_or_in_a_bad_shape_is_refused(tmp_path):
    refused(tmp_path, {"a": {"type": "bool", "requires": ["a"]}}, "requires")
    refused(tmp_path, {"a": {"type": "bool", "conflicts": ["a"]}}, "conflicts")
    refused(tmp_path, {"a": {"type": "bool"}, "b": {"type": "bool", "requires": "a"}}, "requires")
    refused(tmp_path, {"a": {"type": "bool"}, "b": {"type": "bool", "conflicts": {"a": True}}}, "conflicts")
    refused(tmp_path, {"a": {"type": "bool"}, "b": {"type": "bool", "requires": [1]}}, "requires")


def test_a_satisfied_rule_passes(tmp_path):
    r = role(tmp_path)
    check_relations(r, {"ntp": True, "servers": ["a"]}, "lab")
    check_relations(r, {}, "lab")
    check_relations(r, {"ntp": True, "mode": "x", "pool": "p"}, "lab")


def test_requires_a_value(tmp_path):
    with pytest.raises(BastetError, match="demo: servers needs ntp to be true") as e:
        check_relations(role(tmp_path), {"servers": ["a"]}, "lab", file=Path("n.md"))
    assert e.value.file == Path("n.md")
    with pytest.raises(BastetError, match="demo: servers needs ntp to be true"):
        check_relations(role(tmp_path), {"servers": ["a"], "ntp": False}, "lab")


def test_requires_one_of_several_values(tmp_path):
    r = role(tmp_path, {"a": {"type": "string"}, "b": {"type": "string", "requires": {"a": ["x", "y"]}}})
    check_relations(r, {"a": "y", "b": "1"}, "lab")
    with pytest.raises(BastetError, match="demo: b needs a to be one of x, y"):
        check_relations(r, {"a": "z", "b": "1"}, "lab")


def test_requires_names_only_that_it_is_set(tmp_path):
    r = role(tmp_path)
    with pytest.raises(BastetError, match="demo: pool needs ntp to be set"):
        check_relations(r, {"pool": "p", "mode": "m"}, "lab")
    with pytest.raises(BastetError, match="demo: pool needs mode to be set"):
        check_relations(r, {"pool": "p", "ntp": False}, "lab")


def test_false_zero_empty_text_and_empty_list_count_as_set(tmp_path):
    r = role(tmp_path, {"a": {"type": "any"}, "b": {"type": "any", "requires": ["a"]}})
    for v in (False, 0, "", []):
        check_relations(r, {"a": v, "b": 1}, "lab")
    with pytest.raises(BastetError):
        check_relations(r, {"a": None, "b": 1}, "lab")


def test_conflicts(tmp_path):
    r = role(tmp_path, {"a": {"type": "any"}, "b": {"type": "any", "conflicts": ["a"]}})
    check_relations(r, {"a": 1}, "lab")
    check_relations(r, {"b": 1}, "lab")
    with pytest.raises(BastetError, match="demo: b can't be set together with a"):
        check_relations(r, {"a": False, "b": 0}, "lab")


def test_fields_inside_an_object_are_siblings(tmp_path):
    fields = {"x": {"type": "bool"}, "y": {"type": "int", "requires": {"x": True}}, "z": {"type": "int", "conflicts": ["y"]}}
    r = role(tmp_path, {"o": {"type": "object", "fields": fields}, "x": {"type": "bool"}})
    check_relations(r, {"o": {"x": True, "y": 1}}, "lab")
    with pytest.raises(BastetError, match=r"demo: o\.y needs o\.x to be true"):
        check_relations(r, {"o": {"y": 1}, "x": True}, "lab")
    with pytest.raises(BastetError, match=r"demo: o\.z can't be set together with o\.y"):
        check_relations(r, {"o": {"x": True, "y": 1, "z": 2}}, "lab")


def test_fields_inside_list_items_are_checked_per_item(tmp_path):
    item = {"type": "object", "fields": {"x": {"type": "bool"}, "y": {"type": "int", "requires": ["x"]}}}
    r = role(tmp_path, {"l": {"type": "list", "items": item}})
    check_relations(r, {"l": [{"x": True, "y": 1}, {"x": False}]}, "lab")
    with pytest.raises(BastetError, match=r"demo: l\[1\]\.y needs l\[1\]\.x to be set"):
        check_relations(r, {"l": [{"y": 1, "x": 1}, {"y": 2}]}, "lab")


# the check sees the merged values of all notes (before defaults), per host

TYPES = load_host_types()


def inventory(tmp_path, notes):
    files = {
        "Homelab.md": "---\nbastet: lab\n---\n# Homelab\n",
        "hosts/h1.md": "---\nbastet: host\ntype: computer\nconnection: local\n---\n# h1\n",
        **notes,
    }
    for rel, text in files.items():
        p = tmp_path / "inv" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return load_inventory(tmp_path / "inv", TYPES)


LAB_SERVERS = '---\nbastet: role\nrole: demo\napplies_to: "[[Homelab]]"\nservers: [a]\n---\n'
HOST_NTP = '---\nbastet: role\nrole: demo\napplies_to: "[[h1]]"\nntp: true\n---\n'


def test_a_lab_note_and_a_host_note_can_complete_each_other(tmp_path):
    demo = role(tmp_path)
    inv = inventory(tmp_path, {"_roles/lab/demo.md": LAB_SERVERS, "_roles/hosts/h1/demo.md": HOST_NTP})
    out = resolve(inv, inv.get("h1"), TYPES, {"demo": demo})
    assert out[0].values["servers"] == ["a"] and out[0].values["ntp"] is True


def test_the_merged_values_are_checked_and_the_error_names_the_note(tmp_path):
    demo = role(tmp_path)
    inv = inventory(tmp_path, {"_roles/lab/demo.md": LAB_SERVERS})
    with pytest.raises(BastetError, match="demo: servers needs ntp to be true") as e:
        resolve(inv, inv.get("h1"), TYPES, {"demo": demo})
    assert e.value.file is not None and e.value.file.name == "demo.md"


def test_a_default_does_not_satisfy_a_rule(tmp_path):
    demo = role(tmp_path, {**OPTIONS, "ntp": {"type": "bool", "default": True}})
    inv = inventory(tmp_path, {"_roles/lab/demo.md": LAB_SERVERS})
    with pytest.raises(BastetError, match="servers needs ntp"):
        resolve(inv, inv.get("h1"), TYPES, {"demo": demo})
