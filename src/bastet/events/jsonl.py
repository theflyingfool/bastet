"""The run record: one JSONL file per run under the controller's data directory."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from bastet.core.errors import BastetError
from bastet.events.model import Event
from bastet.ui import out

_ID = re.compile(r"[0-9A-Za-z-]+")
_TAIL = 65536


def runs_dir(data: Path) -> Path:
    return data / "runs"


class JsonlSink:
    name = "jsonl"

    def __init__(self, directory: Path, run_id: str) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)
        self.path = directory / f"{run_id}.jsonl"
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        self._file = os.fdopen(fd, "w", encoding="utf-8")

    def handle(self, event: Event) -> None:
        self._file.write(event.to_json() + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()


def _files(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.jsonl")) if directory.is_dir() else []


def prune(directory: Path, *, keep_runs: int, keep_days: int, now: float | None = None) -> list[Path]:
    files = _files(directory)
    doomed = set(files[:-keep_runs]) if len(files) > keep_runs else set()
    cutoff = (now if now is not None else time.time()) - keep_days * 86400
    doomed |= {f for f in files if f.stat().st_mtime < cutoff}
    removed: list[Path] = []
    for path in sorted(doomed):
        try:
            path.unlink()
            removed.append(path)
        except OSError as exc:
            out.secho(f"warning: could not remove old run record {path.name}: {exc}", fg="yellow", err=True)
    return removed


def _parse(line: str) -> dict | None:
    try:
        parsed = json.loads(line)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def summarize(path: Path) -> dict:
    info = {"id": path.stem, "command": "", "started": "", "status": "unfinished", "hosts": 0, "changed": 0, "failed": 0}
    try:
        with path.open("rb") as f:
            first = f.readline().decode("utf-8", "replace")
            size = f.seek(0, os.SEEK_END)
            f.seek(max(0, size - _TAIL))
            tail = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return info
    started = _parse(first)
    if started and started.get("kind") == "run_started":
        info["command"] = started["data"].get("command", "")
        info["started"] = started.get("t", "")
    finished = _parse(tail[-1]) if tail else None
    if finished and finished.get("kind") == "run_finished":
        data = finished["data"]
        info.update(status=data.get("status", "unfinished"), hosts=data.get("hosts", 0),
                    changed=data.get("changed", 0), failed=data.get("failed", 0))
    return info


def resolve_run(directory: Path, ident: str) -> Path:
    if not _ID.fullmatch(ident):
        raise BastetError(f"{ident!r} is not a run id")
    files = _files(directory)
    if ident == "latest":
        if not files:
            raise BastetError("no runs recorded yet")
        return files[-1]
    matches = [f for f in files if f.stem.startswith(ident)]
    if not matches:
        raise BastetError(f"no run matching {ident!r}")
    if len(matches) > 1:
        raise BastetError(f"more than one run matches {ident!r}: " + ", ".join(f.stem for f in matches))
    return matches[0]
