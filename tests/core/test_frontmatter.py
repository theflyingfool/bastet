from pathlib import Path

import pytest

from bastet.core.errors import BastetError
from bastet.core.frontmatter import new_document, parse_document, set_keys

P = Path("/v/hosts/pve1.md")

TEXT = """---
bastet: host
# a comment
type: proxmox
interfaces:
  - name: eno1
    mac: aa:bb:cc:dd:ee:01
ip: 10.0.10.11
---
# pve1
Prose.
"""


def test_parse_document():
    doc = parse_document(TEXT, P)
    assert doc.data["type"] == "proxmox"
    assert doc.data["interfaces"][0]["name"] == "eno1"
    assert doc.body == "# pve1\nProse.\n"
    assert doc.key_lines == {"bastet": 2, "type": 4, "interfaces": 5, "ip": 8}
    assert doc.name == "pve1"


def test_no_frontmatter_is_none():
    assert parse_document("# just a note\n", P) is None


def test_crlf_accepted():
    doc = parse_document(TEXT.replace("\n", "\r\n"), P)
    assert doc.data["ip"] == "10.0.10.11"


def test_unclosed_frontmatter():
    with pytest.raises(BastetError) as e:
        parse_document("---\nbastet: host\n", P)
    assert e.value.file == P and e.value.line == 1


def test_invalid_yaml_has_line():
    with pytest.raises(BastetError) as e:
        parse_document("---\nbastet: host\nip: [x\n---\n", P)
    assert e.value.file == P and e.value.line is not None and e.value.line >= 2


def test_non_mapping_frontmatter():
    with pytest.raises(BastetError) as e:
        parse_document("---\n- a\n---\n", P)
    assert "mapping" in e.value.message


def test_set_existing_scalar_keeps_everything_else():
    out = set_keys(TEXT, {"ip": "10.0.10.12"}, P)
    assert out == TEXT.replace("ip: 10.0.10.11", "ip: 10.0.10.12")


def test_set_replaces_whole_block():
    out = set_keys(TEXT, {"interfaces": [{"name": "eno2"}]}, P)
    assert "  - name: eno2\nip: 10.0.10.11\n" in out
    assert "eno1" not in out
    assert "# a comment" in out


def test_set_appends_new_key_at_end():
    out = set_keys(TEXT, {"os": "Proxmox VE 9.0"}, P)
    assert "ip: 10.0.10.11\nos: Proxmox VE 9.0\n---\n# pve1" in out


def test_set_creates_frontmatter_when_missing():
    out = set_keys("# note\n", {"bastet": "location"}, P)
    assert out == "---\nbastet: location\n---\n# note\n"


def test_new_document():
    assert new_document({"bastet": "host", "type": "vps"}, "# edge1\n") == (
        "---\nbastet: host\ntype: vps\n---\n# edge1\n"
    )


def test_set_keys_blank_line_inside_nested_block():
    text = "---\nnetworks:\n  lab:\n    cidr: a\n\n  mgmt:\n    cidr: b\nname: x\n---\n"
    out = set_keys(text, {"networks": {"only": {"cidr": "c"}}}, P)
    assert "mgmt" not in out and "lab" not in out
    assert "only:" in out and "name: x" in out


def test_set_keys_quoted_key():
    text = '---\n"my key": 1\nother: 2\n---\n'
    out = set_keys(text, {"my key": 3}, P)
    assert out.count("my key") == 1 and "my key: 3" in out and "other: 2" in out


def test_set_keys_preserves_crlf():
    text = "---\r\na: 1\r\nb: 2\r\n---\r\nbody\r\n"
    assert set_keys(text, {"a": 3}, P) == "---\r\na: 3\r\nb: 2\r\n---\r\nbody\r\n"


def test_key_lines_include_quoted_keys():
    doc = parse_document('---\n"my key": 1\nb: 2\n---\n', P)
    assert doc.key_lines == {"my key": 2, "b": 3}


def test_set_keys_comment_at_column_zero_inside_list():
    text = "---\ninterfaces:\n  - name: a\n# note\n  - name: b\nram: 8 GB\n---\n"
    out = set_keys(text, {"interfaces": [{"name": "c"}]}, P)
    assert "name: b" not in out and "name: a" not in out
    assert "  - name: c\nram: 8 GB\n" in out
