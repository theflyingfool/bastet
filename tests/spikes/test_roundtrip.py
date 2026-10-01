import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "spikes" / "obsidian" / "roundtrip.py"
spec = importlib.util.spec_from_file_location("roundtrip", SCRIPT)
rt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rt)

BEFORE = """---
bastet: host
# a comment
ip: 10.0.10.11
oob: {type: ipmi, address: 10.0.10.9}
purchased: "2024-03-01"
last: x
---
# body
Prose.
"""


def test_identical_is_clean():
    r = rt.compare(BEFORE, BEFORE)
    assert not r.body_changed and not r.order_changed
    assert r.comments_lost == [] and r.value_changes == {} and r.reformatted == []
    assert r.added == [] and r.removed == []


def test_crlf_is_not_a_change():
    r = rt.compare(BEFORE, BEFORE.replace("\n", "\r\n"))
    assert not r.body_changed and r.reformatted == [] and r.comments_lost == []


def test_value_change_detected():
    after = BEFORE.replace("ip: 10.0.10.11", "ip: 10.0.10.12")
    r = rt.compare(BEFORE, after)
    assert r.value_changes == {"ip": ("10.0.10.11", "10.0.10.12")}
    assert r.reformatted == []


def test_comment_lost_detected():
    after = BEFORE.replace("# a comment\n", "")
    assert rt.compare(BEFORE, after).comments_lost == ["# a comment"]


def test_reformatting_without_value_change_detected():
    after = BEFORE.replace(
        "oob: {type: ipmi, address: 10.0.10.9}",
        "oob:\n  type: ipmi\n  address: 10.0.10.9",
    ).replace('purchased: "2024-03-01"', "purchased: 2024-03-01")
    r = rt.compare(BEFORE, after)
    assert "oob" in r.reformatted
    assert "purchased" in r.reformatted or "purchased" in r.value_changes
    assert "oob" not in r.value_changes


def test_order_change_and_added_key():
    after = BEFORE.replace("last: x\n", "").replace("bastet: host\n", "bastet: host\nlast: x\nnew: 1\n")
    r = rt.compare(BEFORE, after)
    assert r.order_changed
    assert r.added == ["new"]


def test_body_change_detected():
    assert rt.compare(BEFORE, BEFORE.replace("Prose.", "Prose!")).body_changed


def test_missing_frontmatter_reported(tmp_path):
    pristine = tmp_path / "p"
    scratch = tmp_path / "s"
    (pristine / "hosts").mkdir(parents=True)
    (scratch / "hosts").mkdir(parents=True)
    (pristine / "hosts" / "a.md").write_text(BEFORE)
    (scratch / "hosts" / "a.md").write_text("no frontmatter here\n")
    out = rt.report(scratch, pristine)
    assert "hosts/a.md" in out and "no frontmatter" in out


def test_missing_file_reported(tmp_path):
    pristine = tmp_path / "p"
    scratch = tmp_path / "s"
    pristine.mkdir()
    scratch.mkdir()
    (pristine / "a.md").write_text(BEFORE)
    assert "missing" in rt.report(scratch, pristine)


def test_prepare_refuses_non_empty(tmp_path):
    (tmp_path / "x").write_text("x")
    with pytest.raises(SystemExit):
        rt.prepare(tmp_path)


def test_prepare_copies_fixture(tmp_path):
    dest = tmp_path / "vault"
    rt.prepare(dest)
    assert (dest / "hosts" / "pve1.md").exists()
    assert (dest / "views" / "hardware-here.base").exists()


def test_malformed_yaml_reported_not_crash(tmp_path):
    pristine = tmp_path / "p"
    scratch = tmp_path / "s"
    pristine.mkdir()
    scratch.mkdir()
    (pristine / "a.md").write_text(BEFORE)
    (scratch / "a.md").write_text("---\nip: [unclosed\n---\nbody\n")
    (pristine / "b.md").write_text(BEFORE)
    (scratch / "b.md").write_text(BEFORE)
    out = rt.report(scratch, pristine)
    assert "a.md" in out and "invalid YAML" in out
    assert "## b.md" in out
