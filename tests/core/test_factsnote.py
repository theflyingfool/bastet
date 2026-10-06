from pathlib import Path

from bastet.core.changes import Change
from bastet.core.factsnote import FACTS_DIR, facts_change, facts_path, render_facts
from bastet.core.frontmatter import parse_document

HOST = "pve1"
FACTS = {"os": "Debian 13", "kernel": "6.9", "cpu": "Ryzen", "vmid": 101}


def test_facts_path():
    assert facts_path(Path("/root"), "pve1") == Path("/root") / FACTS_DIR / "pve1.md"


def test_render_facts_round_trip():
    text = render_facts(HOST, FACTS, "2026-10-06T10:00:00Z")
    doc = parse_document(text, Path("/v") / FACTS_DIR / "pve1.md")
    assert doc.data["bastet"] == "facts"
    assert doc.data["host"] == "[[pve1]]"
    assert doc.data["gathered"] == "2026-10-06T10:00:00Z"
    assert doc.data["cssclasses"] == ["bastet-facts"]
    assert doc.data["os"] == "Debian 13"
    assert doc.data["kernel"] == "6.9"
    assert doc.data["vmid"] == 101
    assert "# pve1 facts" in doc.body
    assert "Written by Bastet on every gather; don't edit. Your settings live in [[pve1]]." in doc.body
    assert "![[pve1 summary]]" in doc.body


def test_render_facts_key_order_matches_extract_then_alphabetical():
    text = render_facts(HOST, {"vmid": 1, "kernel": "6.9", "os": "Debian 13"}, "now")
    assert text.index("os:") < text.index("kernel:") < text.index("vmid:")


def test_facts_change_new_file(tmp_path):
    change = facts_change(tmp_path, HOST, FACTS, "2026-10-06T10:00:00Z")
    assert isinstance(change, Change)
    assert change.before is None
    assert change.path == facts_path(tmp_path, HOST)
    assert "Debian 13" in change.after


def test_facts_change_none_when_only_gathered_differs(tmp_path):
    path = facts_path(tmp_path, HOST)
    path.parent.mkdir(parents=True)
    path.write_text(render_facts(HOST, FACTS, "2026-10-06T10:00:00Z"), encoding="utf-8")
    assert facts_change(tmp_path, HOST, dict(FACTS), "2026-10-06T11:00:00Z") is None


def test_facts_change_when_facts_differ(tmp_path):
    path = facts_path(tmp_path, HOST)
    path.parent.mkdir(parents=True)
    path.write_text(render_facts(HOST, FACTS, "2026-10-06T10:00:00Z"), encoding="utf-8")
    new_facts = {**FACTS, "os": "Debian 14"}
    change = facts_change(tmp_path, HOST, new_facts, "2026-10-06T11:00:00Z")
    assert change is not None and "Debian 14" in change.after
