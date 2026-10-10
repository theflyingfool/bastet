"""A run's note in the vault, rendered from its events (the dict lines the JSONL holds)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from bastet.core.secrets.redact import ACTIVE
from bastet.core.yamlstyle import dump_frontmatter
from bastet.events.model import level_of

RUNS_DIR = "_bastet/runs"
MAX_DETAIL = 3
MARKS = {"changed": "✓", "compliant": "·", "would-change": "~", "attention": "⚠", "failed": "✗", "skipped": "–"}


def infer_mode(command: str) -> str:
    words = command.split()
    if "-a" in words:
        return "apply"
    if "-c" in words:
        return "check"
    return "gather" if "-g" in words else "apply"


def run_suffix(run_id: str) -> str:
    return run_id.rsplit("-", 1)[-1]


def _when(started: str) -> datetime:
    return datetime.fromisoformat(started.replace("Z", "+00:00"))


def note_name(started: str, mode: str, run_id: str) -> str:
    return f"{_when(started).strftime('%Y-%m-%d %H%M')} {mode} {run_suffix(run_id)}"


@dataclass
class RunSummary:
    run_id: str
    command: str
    mode: str
    started: str
    user: str
    status: str
    duration: float
    hosts: list[str]
    changed: int
    failed: int
    skipped: int


_RANK = {"ok": 0, "failed": 1, "error": 2}


def summarize(events: list[dict], status: str | None = None) -> RunSummary:
    start = next((e for e in events if e["kind"] == "run_started"), None)
    data = start["data"] if start else {}
    finish = next((e for e in reversed(events) if e["kind"] == "run_finished"), None)
    latest: dict[str, dict] = {}

    def host_row(name: str) -> dict:
        return latest.setdefault(name, {"status": "ok", "changed": 0, "failed": 0, "skipped": 0})

    for e in events:
        if e["kind"] == "host_finished" and e["host"]:
            row, d = host_row(e["host"]), e["data"]
            if _RANK.get(d.get("status", "ok"), 0) > _RANK[row["status"]]:
                row["status"] = d["status"]
            for key in ("changed", "failed", "skipped"):
                if key in d:                        # a scope that omits counts keeps the earlier ones
                    row[key] = int(d[key] or 0)
        elif e["kind"] == "host_skipped" and e["host"] and str(e["data"].get("reason", "")).startswith("error:"):
            row = host_row(e["host"])               # a planning error: a failed host
            row["status"] = max(row["status"], "failed", key=_RANK.get)
            row["failed"] = max(row["failed"], 1)
    bad = any(r["status"] != "ok" or r["failed"] for r in latest.values())
    command = data.get("command", "")
    return RunSummary(
        run_id=events[0]["run_id"] if events else "", command=command, mode=data.get("mode") or infer_mode(command),
        started=start["t"] if start else "", user=data.get("user", ""),
        status=status or (finish["data"]["status"] if finish else ("failed" if bad else "ok")),
        duration=finish["data"]["duration"] if finish else max((e["elapsed"] for e in events), default=0.0),
        hosts=list(latest), changed=sum(r["changed"] for r in latest.values()),
        failed=sum(r["failed"] for r in latest.values()), skipped=sum(r["skipped"] for r in latest.values()),
    )


def _item_line(d: dict) -> list[str]:
    mark = MARKS.get(d["status"], "·")
    lines = [f"- {mark} {d['item']}" + (f": {'; '.join(d['changes'])}" if d.get("changes") else f" ({d['status']})")]
    if d.get("error"):
        lines.append(f"  - {d['error']}")
    return lines


def _host_section(host: str, events: list[dict], detail: int) -> list[str]:
    mine = [e for e in events if e["host"] == host]
    done = next((e["data"] for e in reversed(mine) if e["kind"] == "host_finished"), None)
    skip = next((e["data"] for e in mine if e["kind"] == "host_skipped"), None)
    failed_plan = skip and str(skip.get("reason", "")).startswith("error:")
    lines = ["", f"## {host}: {done['status'] if done else ('failed' if failed_plan else 'skipped')}"]
    if skip:
        lines.append(f"- skipped: {skip['reason']}")
    if done and done.get("error"):
        lines.append(f"- error: {done['error']}")
    lines += [f"- ✗ trigger {e['data']['trigger']}: {e['data'].get('error') or 'failed'}"
              for e in mine if e["kind"] == "trigger_fired" and not e["data"]["ok"]]
    if detail == 1:
        last: dict[str, dict] = {}
        for e in mine:
            if e["kind"] == "item_checked":
                last[e["data"]["item"]] = e["data"]
        for d in last.values():
            if d["status"] != "compliant":
                lines += _item_line(d)
        lines += [f"- {e['data']['message']}" for e in mine if e["kind"] == "note"]
        return lines
    for e in mine:
        d, kind = e["data"], e["kind"]
        if level_of(kind, d) > detail:
            continue
        if kind == "phase_started":
            lines += ["", f"### {d['phase']}"]
        elif kind == "item_checked":
            lines += _item_line(d)
        elif kind == "command_run":
            result = "error" if d["exit"] is None else f"exit {d['exit']}"
            lines.append(f"- `$ {d['command']}` → {result} ({d['duration']:.1f}s)")
        elif kind == "trigger_fired" and d["ok"]:
            lines.append(f"- trigger {d['trigger']} ✓")
        elif kind == "note":
            lines.append(f"- {d['message']}")
    return lines


def render_run_note(events: list[dict], detail: int, status: str | None = None) -> str:
    detail = max(1, min(detail, MAX_DETAIL))
    s = summarize(events, status)
    when = _when(s.started) if s.started else datetime.now()
    frontmatter = {
        "bastet": "run", "generated": True, "run": s.run_id, "command": s.command, "mode": s.mode, "started": s.started,
        "hosts": [f"[[{h}]]" for h in s.hosts], "changed": s.changed, "failed": s.failed, "status": s.status,
        "detail": detail,
    }
    plural = "host" if len(s.hosts) == 1 else "hosts"
    lines = [
        f"# {s.mode} {when.strftime('%Y-%m-%d %H:%M')}", "",
        f"`{s.command}` · by {s.user or 'unknown'} · {len(s.hosts)} {plural} · {s.changed} changed · "
        f"{s.failed} failed · took {s.duration:.1f}s · {s.status}",
    ]
    run_notes = [e["data"]["message"] for e in events if e["kind"] == "note" and not e["host"]]
    if run_notes:
        lines += ["", "## Notes", *[f"- {m}" for m in run_notes]]
    hosts = list(s.hosts) + [e["host"] for e in events if e["kind"] == "host_skipped" and e["host"] not in s.hosts]
    for host in dict.fromkeys(hosts):
        lines += _host_section(host, events, detail)
    text = "---\n" + dump_frontmatter(frontmatter) + "---\n" + "\n".join(lines) + "\n"
    return ACTIVE.mask(text)


def find_notes(root: Path, run_id: str) -> list[Path]:
    """Notes under _bastet/runs whose `run` is `run_id` (found by the suffix in the name, confirmed by the frontmatter)."""
    folder = root / RUNS_DIR
    found = []
    for path in sorted(folder.glob(f"* {run_suffix(run_id)}.md")) if folder.is_dir() else []:
        try:
            head = path.read_text(encoding="utf-8")[:2000]
        except OSError:
            continue
        if re.search(r"^bastet: run$", head, re.M) and re.search(rf"^run: {re.escape(run_id)}$", head, re.M):
            found.append(path)
    return found
