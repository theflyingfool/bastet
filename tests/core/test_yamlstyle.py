import datetime as dt

import yaml

from bastet.core.yamlstyle import dump_frontmatter


def test_simple_scalars():
    assert dump_frontmatter({"bastet": "host", "ip": "10.0.10.11", "n": 3, "ok": True}) == (
        "bastet: host\nip: 10.0.10.11\nn: 3\nok: true\n"
    )


def test_wikilinks_double_quoted():
    assert dump_frontmatter({"location": "[[Closet]]"}) == 'location: "[[Closet]]"\n'


def test_list_of_links_block_style():
    assert dump_frontmatter({"groups": ["[[pvenodes]]"]}) == 'groups:\n  - "[[pvenodes]]"\n'


def test_list_of_maps_matches_obsidian_output():
    data = {
        "interfaces": [
            {"name": "eno1", "mac": "aa:bb:cc:dd:ee:01", "speed": "1G"},
            {"name": "enp65s0f0", "mac": "aa:bb:cc:dd:ee:02", "speed": "10G"},
        ]
    }
    assert dump_frontmatter(data) == (
        "interfaces:\n"
        "  - name: eno1\n"
        "    mac: aa:bb:cc:dd:ee:01\n"
        "    speed: 1G\n"
        "  - name: enp65s0f0\n"
        "    mac: aa:bb:cc:dd:ee:02\n"
        "    speed: 10G\n"
    )


def test_nested_map_block_style():
    assert dump_frontmatter({"oob": {"type": "ipmi", "address": "10.0.10.9"}}) == (
        "oob:\n  type: ipmi\n  address: 10.0.10.9\n"
    )


def test_strings_that_yaml_would_retype_are_quoted():
    assert dump_frontmatter({"d": "2024-03-01"}) == 'd: "2024-03-01"\n'
    assert dump_frontmatter({"v": "yes"}) == 'v: "yes"\n'
    assert dump_frontmatter({"t": "10:20"}) == 't: "10:20"\n'


def test_dates_unquoted():
    assert dump_frontmatter({"purchased": dt.date(2024, 3, 2)}) == "purchased: 2024-03-02\n"


def test_empty_and_none():
    assert dump_frontmatter({}) == ""
    assert dump_frontmatter({"a": [], "b": {}, "c": None}) == "a: []\nb: {}\nc:\n"


def test_round_trip_tricky_values():
    data = {
        "colon": "a: b",
        "hash": "#x",
        "lead": " space",
        "empty": "",
        "multi": "line1\nline2",
        "num_str": "123",
        "float": 1.5,
        "nested": {"list": ["x", {"k": "v"}], "flag": False},
        "with space": "ok",
    }
    assert yaml.safe_load(dump_frontmatter(data)) == data
