import pytest
import yaml

from bastet.core.errors import BastetError
from bastet.core.factsnote import render_facts
from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from bastet.engine.run import Note
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import load_roles, parse_role
from bastet.roles.resolve import resolve

TYPES = load_host_types()
BASE = {"bastet": "role-definition", "name": "demo", "version": "1.2.3", "api": 0, "description": "A demo role"}
OPTIONS = {
    "ntp": {"type": "bool"},
    "servers": {"type": "list", "items": {"type": "string"}, "requires": {"ntp": True}},
    "zone": {"type": "string"},
    "level": {"type": "int", "min": 1, "max": 5},
}
NULL_ON_DEBIAN = {"when": "not host.arch_like", "ntp": None, "servers": None}


def demo_role(tmp_path, overrides):
    folder = tmp_path / "roles" / "demo"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "demo role.md"
    data = {**BASE, "options": OPTIONS}
    if overrides is not None:
        data["overrides"] = overrides
    path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\nNotes.\n")
    return parse_role(path)


def run(tmp_path, overrides, notes, os_text="Debian GNU/Linux 13 (trixie)", host_type="computer"):
    files = {
        "Homelab.md": "---\nbastet: lab\nsite: home\n---\n# Homelab\n",
        "hosts/h1.md": f"---\nbastet: host\ntype: {host_type}\nconnection: local\n---\n# h1\n",
        "_bastet/facts/h1 facts.md": render_facts("h1", {"os": os_text}, "2026-10-06T10:00:00Z"),
    }
    for target, body in notes.items():
        sub = "lab" if target == "Homelab" else "hosts/" + target
        files[f"_roles/{sub}/demo.md"] = f'---\nbastet: role\nrole: demo\napplies_to: "[[{target}]]"\n{body}---\n'
    for rel, text in files.items():
        p = tmp_path / "inv" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    inv = load_inventory(tmp_path / "inv", TYPES)
    applied = resolve(inv, inv.get("h1"), TYPES, {**load_roles(), "demo": demo_role(tmp_path, overrides)})
    return next(a for a in applied if a.role.name == "demo")


LAB = "ntp: true\nservers:\n  - 10.1.1.1\nzone: Europe/Berlin\n"


def test_a_matching_entry_nulls_options_and_leaves_the_rest(tmp_path):
    out = run(tmp_path, [NULL_ON_DEBIAN], {"Homelab": LAB})
    assert out.values["ntp"] is None and out.values["servers"] is None and out.values["zone"] == "Europe/Berlin"
    assert "ntp" not in out.origins and "servers" not in out.origins and out.origins["zone"] == "lab"


def test_a_non_matching_entry_does_nothing_and_says_nothing(tmp_path):
    out = run(tmp_path, [NULL_ON_DEBIAN], {"Homelab": LAB}, os_text="Arch Linux")
    assert out.values["ntp"] is True and out.values["servers"] == ["10.1.1.1"] and out.notes == []


def test_clearing_only_ntp_still_fails_the_relation_check(tmp_path):
    with pytest.raises(BastetError, match="servers needs ntp"):
        run(tmp_path, [{"when": "not host.arch_like", "ntp": None}], {"Homelab": LAB})


def test_an_override_runs_after_the_merge_so_it_beats_every_note(tmp_path):
    out = run(tmp_path, [NULL_ON_DEBIAN], {"Homelab": "zone: a\n", "h1": LAB})
    assert out.values["ntp"] is None and out.values["servers"] is None


def test_a_set_value_replaces_the_merged_one_and_the_origin_says_role_override(tmp_path):
    out = run(tmp_path, [{"when": "host.debian_like", "zone": "UTC"}], {"Homelab": "zone: a\n"})
    assert out.values["zone"] == "UTC" and out.origins["zone"] == "role override"


def test_a_set_value_on_an_unset_option_is_applied_without_a_note(tmp_path):
    out = run(tmp_path, [{"when": "host.debian_like", "level": 2}], {"Homelab": "zone: a\n"})
    assert out.values["level"] == 2 and out.origins["level"] == "role override" and out.notes == []


def test_entries_apply_in_listing_order_and_the_last_wins(tmp_path):
    entries = [{"when": "host.debian_like", "level": 2}, {"when": "not host.container", "level": 3}]
    assert run(tmp_path, entries, {"Homelab": "zone: a\n"}).values["level"] == 3


def test_when_may_use_the_role_options_with_their_merged_values(tmp_path):
    entry = {"when": "ntp and zone is none", "level": 4}
    assert run(tmp_path, [entry], {"Homelab": "ntp: true\n"}).values["level"] == 4
    assert run(tmp_path, [entry], {"Homelab": "ntp: true\nzone: a\n"}).values["level"] is None


def test_when_sees_unset_options_as_none_and_lab_facts(tmp_path):
    entry = {"when": "ntp is none and lab.site == 'home'", "level": 5}
    assert run(tmp_path, [entry], {"Homelab": "zone: a\n"}).values["level"] == 5


def test_one_info_note_names_the_options_that_had_a_value(tmp_path):
    out = run(tmp_path, [NULL_ON_DEBIAN], {"Homelab": LAB})
    assert out.notes == [Note("info", "demo", "role demo ignores ntp, servers on this host")]


def test_only_options_that_had_a_value_are_named(tmp_path):
    out = run(tmp_path, [NULL_ON_DEBIAN], {"Homelab": "ntp: true\n"})
    assert out.notes == [Note("info", "demo", "role demo ignores ntp on this host")]


def test_nothing_changed_gives_no_note(tmp_path):
    assert run(tmp_path, [NULL_ON_DEBIAN], {"Homelab": "zone: a\n"}).notes == []


def test_the_note_text_is_the_entrys_own_and_may_use_names(tmp_path):
    entry = {**NULL_ON_DEBIAN, "note": "sync of {{ servers | join(',') }} is skipped on {{ host.name }}"}
    out = run(tmp_path, [entry], {"Homelab": LAB})
    assert out.notes == [Note("info", "demo", "sync of 10.1.1.1 is skipped on h1")]


def test_two_entries_that_both_change_something_give_two_notes_in_order(tmp_path):
    entries = [{"when": "host.debian_like", "zone": None, "note": "first"},
               {"when": "host.debian_like", "ntp": None, "servers": None, "note": "second"}]
    out = run(tmp_path, entries, {"Homelab": LAB})
    assert [n.message for n in out.notes] == ["first", "second"]


def test_the_notes_reach_the_roles_batch(tmp_path):
    out = run(tmp_path, [NULL_ON_DEBIAN], {"Homelab": LAB})
    host = HostInfo(name="h1", type="computer", data={"os": "Debian"}, root=tmp_path, lab={})
    batches = [b for b in batches_for([out], host) if b.name == "demo"]
    assert [n for b in batches for n in b.notes] == out.notes


def test_a_role_without_overrides_is_untouched(tmp_path):
    out = run(tmp_path, None, {"Homelab": LAB})
    assert out.values["ntp"] is True and out.notes == []


@pytest.mark.parametrize("entries, text, index", [
    ([{"when": "applied.origin.ntp", "zone": "x"}], "applied", 0),
    ([{"when": "host.nope", "zone": "x"}], "nope", 0),
    ([{"when": "nothing", "zone": "x"}], "nothing", 0),
    ([{"when": "host.arch_like and", "zone": "x"}], "when", 0),
    ([{"zone": "x"}], "needs a when", 0),
    ([{"when": "host.arch_like", "zone": "x"}, {"when": 3, "zone": "x"}], "needs a when", 1),
    ([{"when": "host.arch_like", "zonee": "x"}], "no option 'zonee'", 0),
    ([{"when": "host.arch_like", "ntp": "maybe"}], "expected true or false", 0),
    ([{"when": "host.arch_like", "level": 9}], "5 or less", 0),
    ([{"when": "host.arch_like", "zone": "x", "note": 3}], "note must be text", 0),
    ([{"when": "host.arch_like", "zone": "x", "note": "{{ nothing }}"}], "nothing", 0),
    ([{"when": "host.arch_like", "zone": "x", "note": "{{ applied.origin.zone }}"}], "applied", 0),
    (["nope"], "must be a map", 0),
    ("nope", "must be a list", None),
])
def test_a_bad_entry_is_refused_when_the_role_is_read(tmp_path, entries, text, index):
    with pytest.raises(BastetError) as err:
        demo_role(tmp_path, entries)
    assert text in err.value.message and err.value.key == "overrides"
    assert err.value.file is not None and err.value.file.name == "demo role.md"
    assert err.value.message.startswith("role demo: overrides")
    if index is not None:
        assert f"overrides[{index}]" in err.value.message
