import json
import time

import pytest

from bastet.core.config import data_dir
from bastet.core.secrets.redact import ACTIVE
from bastet.events.model import KINDS, Event, level_of, make_event, mask_event, mask_value


def ev(kind="note", host=None, **data):
    data = data or {"message": "hi"}
    return make_event(kind, "20261010-120000-ab12", time.monotonic(), host, data)


def test_every_kind_can_be_made_with_exactly_its_required_keys():
    for kind, keys in KINDS.items():
        event = make_event(kind, "r1", time.monotonic(), None, {k: 1 for k in keys})
        assert event.kind == kind


def test_unknown_kind_and_missing_key_are_errors():
    with pytest.raises(ValueError, match="unknown event kind"):
        make_event("nope", "r1", time.monotonic(), None, {})
    with pytest.raises(ValueError, match="missing"):
        make_event("command_run", "r1", time.monotonic(), "pve1", {"phase": "apply"})


def test_levels():
    assert level_of("run_started", {}) == 1
    assert level_of("phase_started", {}) == 2 and level_of("phase_finished", {}) == 2
    assert level_of("command_run", {}) == 3
    assert level_of("item_checked", {"status": "would-change"}) == 1
    assert level_of("item_checked", {"status": "failed"}) == 1
    assert level_of("item_checked", {"status": "compliant"}) == 2
    assert ev("note", message="x").level == 1


def test_to_json_is_one_line_and_round_trips():
    event = ev("item_checked", "pve1", item="/etc/motd", status="changed", phase="apply", changes=["a → b"], path=__import__("pathlib").Path("/x"))
    line = event.to_json()
    assert "\n" not in line
    parsed = json.loads(line)
    assert parsed["kind"] == "item_checked" and parsed["host"] == "pve1" and parsed["run_id"] == "20261010-120000-ab12"
    assert parsed["data"]["changes"] == ["a → b"] and parsed["data"]["path"] == "/x"
    assert parsed["t"].endswith("Z") and isinstance(parsed["elapsed"], float)


def test_non_ascii_is_kept_readable():
    assert "→" in ev("note", message="a → b").to_json()


def test_mask_value_is_recursive_and_leaves_keys_and_other_types():
    ACTIVE.add("hunter2-value")
    masked = mask_value({"a": ["x hunter2-value", {"b": "hunter2-value"}], "n": 3, "hunter2-value": 1})
    assert "hunter2-value" not in json.dumps({k: v for k, v in masked.items() if k != "hunter2-value"})
    assert masked["n"] == 3 and "hunter2-value" in masked  # keys are not masked


def test_mask_event_masks_the_data_only():
    ACTIVE.add("hunter2-value")
    event = mask_event(ev("note", "pve1", message="pw hunter2-value"))
    assert "hunter2-value" not in event.data["message"] and event.host == "pve1" and event.kind == "note"


def test_the_test_suite_never_uses_the_real_data_directory():
    real = __import__("pathlib").Path.home() / ".local" / "share" / "bastet"
    assert data_dir() != real
