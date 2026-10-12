from pathlib import Path

import pytest

from bastet.core.errors import BastetError
from bastet.roles.contract import RoleDef, _option, check_values, with_defaults

ITEMS = {"type": "object", "fields": {"x": {"type": "int"}, "y": {"type": "int"}}}
DEFAULT = {"a": {"x": 1}, "b": {}}


def role(merge=True):
    raw = {"type": "map", "default": DEFAULT, "items": ITEMS}
    if merge:
        raw["merge_default"] = True
    return RoleDef("demo", "", {"things": _option("demo.things", raw, Path("demo.yml"))}, Path("demo.yml"))


def got(values, merge=True):
    r = role(merge)
    return with_defaults(r, check_values(r, values, "demo"))["things"]


def test_no_value_gives_the_default():
    assert got({}) == {"a": {"x": 1}, "b": {}}


def test_none_given_gives_the_default():
    assert with_defaults(role(), {"things": None})["things"] == {"a": {"x": 1}, "b": {}}


def test_a_new_key_is_added_beside_the_defaults():
    assert got({"things": {"c": {"y": 2}}}) == {"a": {"x": 1}, "b": {}, "c": {"y": 2}}


def test_a_given_entry_wins_and_a_partial_one_merges_over_the_default_entry():
    assert got({"things": {"a": {"x": 5, "y": 3}}}) == {"a": {"x": 5, "y": 3}, "b": {}}
    assert got({"things": {"a": {"y": 3}}}) == {"a": {"x": 1, "y": 3}, "b": {}}


def test_the_default_is_not_changed_by_a_merge():
    got({"things": {"a": {"y": 3}}})
    assert DEFAULT == {"a": {"x": 1}, "b": {}}


def test_without_the_flag_the_given_map_replaces_the_default():
    assert got({"things": {"c": {"y": 2}}}, merge=False) == {"c": {"y": 2}}


def test_the_flag_on_a_non_map_option_is_refused_naming_the_option():
    with pytest.raises(BastetError, match="demo.name"):
        _option("demo.name", {"type": "string", "merge_default": True}, Path("demo.yml"))
