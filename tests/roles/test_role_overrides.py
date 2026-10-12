import pytest
import yaml

from bastet.core.errors import BastetError
from bastet.core.factsnote import render_facts
from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from bastet.roles.contract import load_roles, parse_role
from bastet.roles.resolve import resolve

TYPES = load_host_types()
BASE = {"bastet": "role-definition", "name": "demo", "version": "1.2.3", "api": 0, "description": "A demo role"}
OPTIONS = {
    "ntp": {"type": "bool"},
    "zone": {"type": "string"},
    "key": {"type": "string", "secret": True},
}


def demo_role(tmp_path):
    folder = tmp_path / "roles" / "demo"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "demo role.md"
    path.write_text("---\n" + yaml.safe_dump({**BASE, "options": OPTIONS}, sort_keys=False) + "---\nNotes.\n")
    return parse_role(path)


def run(tmp_path, notes, os_text="Debian GNU/Linux 13 (trixie)"):
    files = {
        "Homelab.md": "---\nbastet: lab\nsite: home\n---\n# Homelab\n",
        "groups/g.md": "---\nbastet: group\n---\n# g\n",
        "hosts/h1.md": '---\nbastet: host\ntype: computer\nconnection: local\ngroups:\n  - "[[g]]"\n---\n# h1\n',
        "_bastet/facts/h1 facts.md": render_facts("h1", {"os": os_text}, "2026-10-06T10:00:00Z"),
    }
    for target, body in notes.items():
        sub = "lab" if target == "Homelab" else ("hosts/" + target if target == "h1" else "groups/" + target)
        files[f"_roles/{sub}/demo.md"] = f'---\nbastet: role\nrole: demo\napplies_to: "[[{target}]]"\n{body}---\n'
    for rel, text in files.items():
        p = tmp_path / "inv" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    inv = load_inventory(tmp_path / "inv", TYPES)
    applied = resolve(inv, inv.get("h1"), TYPES, {**load_roles(), "demo": demo_role(tmp_path)})
    return next(a for a in applied if a.role.name == "demo")


LAB = "ntp: true\noverrides:\n  - when: not host.arch_like\n    ntp: false\n"


def test_a_matching_entry_replaces_the_notes_own_value(tmp_path):
    assert run(tmp_path, {"Homelab": LAB}).values["ntp"] is False


def test_a_non_matching_entry_does_nothing(tmp_path):
    out = run(tmp_path, {"Homelab": LAB}, os_text="Arch Linux")
    assert out.values["ntp"] is True and out.origins["ntp"] == "lab"


def test_the_last_matching_entry_wins(tmp_path):
    body = "zone: a\noverrides:\n  - {when: host.container == false, zone: b}\n  - {when: host.physical, zone: c}\n"
    assert run(tmp_path, {"Homelab": body}).values["zone"] == "c"


def test_a_higher_ranked_note_beats_a_lab_override(tmp_path):
    out = run(tmp_path, {"Homelab": LAB, "g": "ntp: true\n"})
    assert out.values["ntp"] is True and out.origins["ntp"] == "group g"


def test_a_null_override_clears_after_the_merge(tmp_path):
    out = run(tmp_path, {"Homelab": "ntp: true\noverrides:\n  - {when: not host.arch_like, ntp: null}\n"})
    assert out.values["ntp"] is None and "ntp" not in out.origins


def test_a_null_override_loses_to_a_higher_ranked_value(tmp_path):
    body = "ntp: true\noverrides:\n  - {when: not host.arch_like, ntp: null}\n"
    assert run(tmp_path, {"Homelab": body, "h1": "ntp: true\n"}).values["ntp"] is True


def test_the_origin_says_override(tmp_path):
    assert run(tmp_path, {"Homelab": LAB}).origins["ntp"] == "lab (override)"


def test_an_override_applies_with_no_base_value(tmp_path):
    out = run(tmp_path, {"g": "overrides:\n  - {when: host.debian_like, zone: Berlin}\n"})
    assert out.values["zone"] == "Berlin" and out.origins["zone"] == "group g (override)"


def test_when_sees_lab_facts(tmp_path):
    body = "overrides:\n  - {when: \"lab.site == 'home'\", zone: Home}\n"
    assert run(tmp_path, {"Homelab": body}).values["zone"] == "Home"


def test_secret_references_pass_through(tmp_path):
    out = run(tmp_path, {"Homelab": "overrides:\n  - {when: host.debian_like, key: 'secret:demo-key'}\n"})
    assert out.values["key"] == "secret:demo-key"


@pytest.mark.parametrize("body, text", [
    ("overrides:\n  - {when: ntp, zone: x}\n", "ntp"),
    ("overrides:\n  - {when: host.nope, zone: x}\n", "nope"),
    ("overrides:\n  - {when: nothing.arch_like, zone: x}\n", "nothing"),
    ("overrides:\n  - {when: 'host.arch_like and', zone: x}\n", "when"),
    ("overrides:\n  - {when: host.arch_like, zonee: x}\n", "no option 'zonee'"),
    ("overrides:\n  - {when: host.arch_like, ntp: maybe}\n", "expected true or false"),
    ("overrides:\n  - {zone: x}\n", "needs a when"),
    ("overrides:\n  - {when: 3, zone: x}\n", "needs a when"),
    ("overrides: nope\n", "must be a list"),
    ("overrides:\n  - nope\n", "must be a map"),
])
def test_a_bad_overrides_entry_is_refused_naming_file_and_key(tmp_path, body, text):
    with pytest.raises(BastetError) as err:
        run(tmp_path, {"Homelab": body})
    assert text in err.value.message and err.value.key == "overrides"
    assert err.value.file is not None and err.value.file.name == "demo.md"
    assert err.value.message.startswith("lab note: overrides")
