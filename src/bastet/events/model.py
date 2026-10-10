"""Run events: what a run did, as plain data. The JSONL record and the live view are built from these."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from bastet.core.secrets.redact import ACTIVE

SCHEMA = 1

KINDS: dict[str, tuple[str, ...]] = {
    "run_started": ("command", "schema"),
    "run_finished": ("status", "duration"),
    "host_started": ("mode",),
    "host_finished": ("status",),
    "host_skipped": ("reason",),
    "phase_started": ("phase",),
    "phase_finished": ("phase", "duration"),
    "item_checked": ("item", "status", "phase"),
    "command_run": ("phase", "command", "exit", "duration"),
    "trigger_fired": ("trigger", "ok"),
    "note": ("message",),
}


def level_of(kind: str, data: dict) -> int:
    """1 changes and failures, 2 every item and phase, 3 commands, 4 (display only) their output."""
    if kind in ("phase_started", "phase_finished"):
        return 2
    if kind == "command_run":
        return 3
    if kind == "item_checked":
        return 2 if data.get("status") == "compliant" else 1
    return 1


@dataclass(frozen=True)
class Event:
    kind: str
    run_id: str
    t: str
    elapsed: float
    host: str | None
    data: dict

    @property
    def level(self) -> int:
        return level_of(self.kind, self.data)

    def to_json(self) -> str:
        return json.dumps(
            {"kind": self.kind, "run_id": self.run_id, "t": self.t, "elapsed": round(self.elapsed, 3),
             "host": self.host, "data": self.data},
            ensure_ascii=False, default=str,
        )


def make_event(kind: str, run_id: str, started: float, host: str | None, data: dict) -> Event:
    if kind not in KINDS:
        raise ValueError(f"unknown event kind {kind!r}")
    missing = [k for k in KINDS[kind] if k not in data]
    if missing:
        raise ValueError(f"{kind} is missing {', '.join(missing)}")
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return Event(kind, run_id, now, time.monotonic() - started, host, dict(data))


def mask_value(value: object) -> object:
    if isinstance(value, str):
        return ACTIVE.mask(value)
    if isinstance(value, dict):
        return {k: mask_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [mask_value(v) for v in value]
    return value


def mask_event(event: Event) -> Event:
    return replace(event, host=event.host, data=mask_value(event.data))
