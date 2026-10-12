import pytest
import yaml

from bastet.core.errors import BastetError
from bastet.core.frontmatter import new_document, parse_document
from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from bastet.engine.run import ConflictError
from bastet.roles.contract import check_values, load_roles, parse_role
from bastet.roles.resolve import resolve

TYPES = load_host_types()
BASE = {"bastet": "role-definition", "name": "demo", "version": "1.2.3", "api": 0, "description": "A demo role"}
OPTIONS = {
    "flag": {"type": "bool"},
    "mode": {"type": "string", "default": "std"},
    "items": {"type": "list", "items": {"type": "string"}},
    "users": {"type": "map", "items": {"type": "object", "fields": {"shell": {"type": "string"}, "uid": {"type": "int"}}}},
    "conf": {"type": "object", "fields": {"a": {"type": "string"}, "b": {"type": "string"}}},
    "extra": {"type": "bool", "requires": {"flag": True}},
    "alone": {"type": "bool", "conflicts": ["flag"]},
}


def demo_role(tmp_path, options=None):
    folder = tmp_path / "roles" / "demo"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "demo role.md"
    path.write_text("---\n" + yaml.safe_dump({**BASE, "options": options or OPTIONS}, sort_keys=False) + "---\nNotes.\n")
    return parse_role(path)


def note(applies_to, body):
    return f'---\nbastet: role\nrole: demo\napplies_to: "[[{applies_to}]]"\n{body}---\n'


def run(tmp_path, notes, options=None):
    files = {
        "Homelab.md": "---\nbastet: lab\n---\n# Homelab\n",
        "groups/g.md": "---\nbastet: group\n---\n# g\n",
        "groups/g2.md": "---\nbastet: group\n---\n# g2\n",
        "hosts/h1.md": '---\nbastet: host\ntype: computer\nconnection: local\ngroups:\n  - "[[g]]"\n  - "[[g2]]"\n---\n# h1\n',
    }
    for target, body in notes.items():
        sub = "lab" if target == "Homelab" else ("hosts/" + target if target == "h1" else "groups/" + target)
        files[f"_roles/{sub}/demo.md"] = note(target, body)
    for rel, text in files.items():
        p = tmp_path / "inv" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    inv = load_inventory(tmp_path / "inv", TYPES)
    return resolve(inv, inv.get("h1"), TYPES, {"demo": demo_role(tmp_path, options)})[0]


def test_a_group_null_clears_a_lab_value(tmp_path):
    out = run(tmp_path, {"Homelab": "flag: true\n", "g": "flag:\n"})
    assert out.values["flag"] is None and "flag" not in out.origins


def test_a_host_false_beats_a_group_null(tmp_path):
    out = run(tmp_path, {"Homelab": "flag: true\n", "g": "flag:\n", "h1": "flag: false\n"})
    assert out.values["flag"] is False and out.origins["flag"] == "host h1"


def test_a_host_null_clears_what_a_group_set(tmp_path):
    out = run(tmp_path, {"g": "mode: fancy\n", "h1": "mode: null\n"})
    assert out.values["mode"] == "std" and "mode" not in out.origins  # back to the default


def test_a_cleared_option_takes_its_default(tmp_path):
    out = run(tmp_path, {"Homelab": "mode: fancy\n", "h1": "mode:\n"})
    assert out.values["mode"] == "std"


def test_a_null_with_nothing_inherited_is_a_no_op(tmp_path):
    out = run(tmp_path, {"h1": "flag:\nmode:\nitems:\n"})
    assert out.values["flag"] is None and out.values["mode"] == "std" and out.values["items"] is None
    assert out.origins == {}


def test_a_value_above_a_null_wins_and_does_not_see_below_it(tmp_path):
    out = run(tmp_path, {"Homelab": "items: [a]\n", "g": "items:\n", "h1": "items: [b]\n"})
    assert out.values["items"] == ["b"]


def test_same_rank_null_and_value_clash(tmp_path):
    with pytest.raises(ConflictError, match="flag differently"):
        run(tmp_path, {"g": "flag:\n", "g2": "flag: true\n"})


def test_same_rank_nulls_agree(tmp_path):
    out = run(tmp_path, {"Homelab": "flag: true\n", "g": "flag:\n", "g2": "flag:\n"})
    assert out.values["flag"] is None


def test_a_null_field_inside_an_object_clears_after_the_merge(tmp_path):
    out = run(tmp_path, {"Homelab": "conf:\n  a: x\n  b: y\n", "g": "conf:\n  a:\n", "h1": "conf:\n  b: z\n"})
    assert out.values["conf"] == {"b": "z"}
    out = run(tmp_path / "again", {"Homelab": "conf:\n  a: x\n", "g": "conf:\n  a:\n", "h1": "conf:\n  a: w\n"})
    assert out.values["conf"] == {"a": "w"}


def test_a_null_field_inside_a_map_entry_clears(tmp_path):
    out = run(tmp_path, {"Homelab": "users:\n  al:\n    shell: sh\n    uid: 5\n", "g": "users:\n  al:\n    shell:\n"})
    assert out.values["users"] == {"al": {"uid": 5}}


def test_a_null_map_entry_drops_the_entry(tmp_path):
    out = run(tmp_path, {"Homelab": "users:\n  al: {uid: 5}\n  bo: {uid: 6}\n", "g": "users:\n  al:\n"})
    assert out.values["users"] == {"bo": {"uid": 6}}


def test_a_null_object_field_at_the_same_rank_clashes(tmp_path):
    with pytest.raises(ConflictError, match=r"conf\.a differently"):
        run(tmp_path, {"g": "conf:\n  a:\n", "g2": "conf:\n  a: x\n"})


def test_the_order_of_notes_never_matters(tmp_path):
    a = run(tmp_path / "1", {"Homelab": "flag: true\n", "g": "flag:\n", "h1": "mode: m\n"})
    b = run(tmp_path / "2", {"h1": "mode: m\n", "g": "flag:\n", "Homelab": "flag: true\n"})
    assert a.values == b.values and a.origins == b.origins


def test_a_cleared_option_does_not_trigger_a_rule(tmp_path):
    out = run(tmp_path, {"Homelab": "extra: true\n", "g": "extra:\n"})
    assert out.values["extra"] is None


def test_a_cleared_option_does_not_satisfy_a_rule(tmp_path):
    with pytest.raises(BastetError, match="extra needs flag to be true"):
        run(tmp_path, {"Homelab": "flag: true\n", "g": "flag:\n", "h1": "extra: true\n"})


def test_a_cleared_option_no_longer_conflicts(tmp_path):
    out = run(tmp_path, {"Homelab": "flag: true\n", "g": "flag:\n", "h1": "alone: true\n"})
    assert out.values["alone"] is True and out.values["flag"] is None


def test_an_unknown_option_is_refused_even_with_a_null(tmp_path):
    with pytest.raises(BastetError, match="no option 'nope'"):
        run(tmp_path, {"h1": "nope:\n"})


def test_check_values_keeps_a_null_for_a_known_option(tmp_path):
    role = demo_role(tmp_path)
    assert check_values(role, {"flag": None, "conf": {"a": None}}, "x") == {"flag": None, "conf": {"a": None}}


def _no_none(value, where):
    if isinstance(value, dict):
        for k, v in value.items():
            _no_none(v, f"{where}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _no_none(v, f"{where}[{i}]")
    else:
        assert value is not None, f"{where} is a bare key (null)"


def test_no_shipped_role_starter_or_example_writes_a_bare_key(tmp_path):
    for name, role in load_roles().items():
        _no_none(role.starter, f"{name} starter")
        values = role.new_note_values()
        _no_none(values, f"{name} new note")
        text = new_document({"bastet": "role", "role": name, "applies_to": "[[Homelab]]", **values}, "Body\n")
        path = tmp_path / f"{name}.md"
        path.write_text(text)
        _no_none(parse_document(text, path).data, f"{name} written note")
        for ex in role.examples:
            _no_none(yaml.safe_load(ex["yaml"]), f"{name} example {ex['title']}")
