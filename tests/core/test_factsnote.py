from pathlib import Path

from bastet.core.changes import Change
from bastet.core.factsnote import (
    FACTS_DIR, SECURITY_MARKER, facts_change, facts_path, hardware_facts_change, hardware_facts_path,
    render_facts, render_hardware_facts, split_security,
)
from bastet.core.frontmatter import parse_document

HOST = "pve1"
FACTS = {"os": "Debian 13", "kernel": "6.9", "cpu": "Ryzen", "vmid": 101}


def test_facts_path():
    assert facts_path(Path("/root"), "pve1") == Path("/root") / FACTS_DIR / "pve1 facts.md"


def test_hardware_facts_path():
    assert hardware_facts_path(Path("/root"), "disk1") == Path("/root") / FACTS_DIR / "disk1 facts.md"


def test_render_facts_round_trip():
    text = render_facts(HOST, FACTS, "2026-10-06T10:00:00Z", body="cards\n")
    doc = parse_document(text, Path("/v") / FACTS_DIR / "pve1 facts.md")
    assert doc.data["bastet"] == "facts"
    assert doc.data["host"] == "[[pve1]]"
    assert doc.data["gathered"] == "2026-10-06T10:00:00Z"
    assert doc.data["cssclasses"] == ["bastet-facts"]
    assert doc.data["os"] == "Debian 13"
    assert doc.data["kernel"] == "6.9"
    assert doc.data["vmid"] == 101
    assert doc.body == "cards\n"


def test_render_facts_omits_gathered_when_none():
    text = render_facts(HOST, {}, None)
    doc = parse_document(text, Path("/v/pve1 facts.md"))
    assert "gathered" not in doc.data


def test_render_facts_includes_warnings_and_drift_only_when_present():
    text = render_facts(HOST, FACTS, "now", warnings=["w1"], drift=["d1"])
    doc = parse_document(text, Path("/v/pve1 facts.md"))
    assert doc.data["warnings"] == ["w1"] and doc.data["drift"] == ["d1"]
    assert "warnings" not in parse_document(render_facts(HOST, FACTS, "now"), Path("/v/pve1 facts.md")).data


def test_render_facts_key_order_matches_extract_then_alphabetical():
    text = render_facts(HOST, {"vmid": 1, "kernel": "6.9", "os": "Debian 13"}, "now")
    assert text.index("os:") < text.index("kernel:") < text.index("vmid:")


def test_facts_change_new_file(tmp_path):
    change = facts_change(tmp_path, HOST, FACTS, "2026-10-06T10:00:00Z")
    assert isinstance(change, Change)
    assert change.before is None
    assert change.path == facts_path(tmp_path, HOST)
    assert "Debian 13" in change.after


def test_facts_change_new_file_has_empty_body(tmp_path):
    """A brand new facts note has no cards yet -- refresh fills them in moments later, in the same run."""
    change = facts_change(tmp_path, HOST, FACTS, "2026-10-06T10:00:00Z")
    doc = parse_document(change.after, facts_path(tmp_path, HOST))
    assert doc.body == ""


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


def test_facts_change_preserves_existing_body(tmp_path):
    """Gather never touches sections 1-4 of the body -- only refresh (1-3) and check/apply (4) do."""
    path = facts_path(tmp_path, HOST)
    path.parent.mkdir(parents=True)
    path.write_text(render_facts(HOST, FACTS, "2026-10-06T10:00:00Z", body="> [!grid]\ncards here\n"), encoding="utf-8")
    new_facts = {**FACTS, "os": "Debian 14"}
    change = facts_change(tmp_path, HOST, new_facts, "2026-10-06T11:00:00Z")
    assert "cards here" in change.after


def test_facts_change_none_when_warnings_and_drift_also_unchanged(tmp_path):
    path = facts_path(tmp_path, HOST)
    path.parent.mkdir(parents=True)
    path.write_text(render_facts(HOST, FACTS, "x", warnings=["w"]), encoding="utf-8")
    assert facts_change(tmp_path, HOST, dict(FACTS), "y", warnings=["w"]) is None


def test_facts_change_when_warnings_change(tmp_path):
    path = facts_path(tmp_path, HOST)
    path.parent.mkdir(parents=True)
    path.write_text(render_facts(HOST, FACTS, "x", warnings=["w"]), encoding="utf-8")
    change = facts_change(tmp_path, HOST, dict(FACTS), "y", warnings=["w2"])
    assert change is not None
    doc = parse_document(change.after, path)
    assert doc.data["warnings"] == ["w2"]


def test_facts_change_clears_warnings_when_explicitly_empty(tmp_path):
    path = facts_path(tmp_path, HOST)
    path.parent.mkdir(parents=True)
    path.write_text(render_facts(HOST, FACTS, "x", warnings=["w"]), encoding="utf-8")
    change = facts_change(tmp_path, HOST, dict(FACTS), "y", warnings=[])
    assert change is not None
    doc = parse_document(change.after, path)
    assert "warnings" not in doc.data


def test_facts_change_leaves_warnings_untouched_when_not_passed(tmp_path):
    """A caller that doesn't know this host's warnings this run (e.g. a side-effect merge for a
    guest's vmid) must never clear what an earlier gather stored."""
    path = facts_path(tmp_path, HOST)
    path.parent.mkdir(parents=True)
    path.write_text(render_facts(HOST, FACTS, "x", warnings=["w"]), encoding="utf-8")
    new_facts = {**FACTS, "os": "Debian 14"}
    change = facts_change(tmp_path, HOST, new_facts, "y")
    doc = parse_document(change.after, path)
    assert doc.data["warnings"] == ["w"]


def test_split_security_round_trips():
    before, section = split_security("cards\n" + SECURITY_MARKER + "\nSecurity text\n")
    assert before == "cards\n" and section == SECURITY_MARKER + "\nSecurity text\n"


def test_split_security_empty_when_no_marker():
    assert split_security("cards\n") == ("cards\n", "")


def test_render_hardware_facts_round_trip():
    text = render_hardware_facts("disk1", {"serial": "S1", "missing_since": "2026-10-01"}, "2026-10-06T10:00:00Z")
    doc = parse_document(text, Path("/v") / FACTS_DIR / "disk1 facts.md")
    assert doc.data["item"] == "[[disk1]]" and doc.data["serial"] == "S1" and doc.data["missing_since"] == "2026-10-01"


def test_hardware_facts_change_new_file(tmp_path):
    change = hardware_facts_change(tmp_path, "disk1", {"serial": "S1"}, "2026-10-06T10:00:00Z")
    assert change is not None and "S1" in change.after


def test_hardware_facts_change_preserves_body(tmp_path):
    path = hardware_facts_path(tmp_path, "disk1")
    path.parent.mkdir(parents=True)
    path.write_text(render_hardware_facts("disk1", {"serial": "S1"}, "x", body="cards here\n"), encoding="utf-8")
    change = hardware_facts_change(tmp_path, "disk1", {"serial": "S2"}, "y")
    assert change is not None and "cards here" in change.after


def test_hardware_facts_change_none_when_only_gathered_differs(tmp_path):
    path = hardware_facts_path(tmp_path, "disk1")
    path.parent.mkdir(parents=True)
    path.write_text(render_hardware_facts("disk1", {"serial": "S1"}, "x"), encoding="utf-8")
    assert hardware_facts_change(tmp_path, "disk1", {"serial": "S1"}, "y") is None
