"""The live view of a run's events on the terminal, from -vv."""

from __future__ import annotations

from bastet.events.model import Event
from bastet.ui import out

MARKS = {
    "compliant": ("✓", "green"), "changed": ("✓", "green"), "would-change": ("~", "yellow"),
    "attention": ("⚠", "yellow"), "failed": ("✗", "red"), "skipped": ("–", "dim"),
}


class TerminalSink:
    name = "terminal"

    def __init__(self, level: int) -> None:
        self.level = level

    def close(self) -> None:
        pass

    def handle(self, event: Event) -> None:
        if event.level > self.level:
            return
        for text, style in self._lines(event):
            out.secho(text, style)

    def _lines(self, e: Event) -> list[tuple[str, str | None]]:
        h = f"{e.host}: " if e.host else ""
        d = e.data
        if e.kind == "host_started":
            return [(f"{h}{d['mode']} started", "dim")]
        if e.kind == "host_finished":
            counts = f"{d.get('changed', 0)} changed · {d.get('failed', 0)} failed · {d.get('skipped', 0)} skipped"
            bad = d["status"] in ("error", "failed")
            return [(f"{h}{d['status']}: {counts}", "red" if bad else "green")]
        if e.kind == "host_skipped":
            return [(f"{h}skipped: {d['reason']}", "dim")]
        if e.kind == "phase_started":
            return [(f"{h}{d['phase']}…", "dim")]
        if e.kind == "phase_finished":
            return [(f"{h}{d['phase']} done ({d['duration']:.1f}s)", "dim")]
        if e.kind == "item_checked":
            mark, style = MARKS.get(d["status"], ("·", None))
            lines: list[tuple[str, str | None]] = [(f"{h}  {mark} {d['item']}  {d['status']}", style)]
            lines += [(f"{h}      {change}", style) for change in d.get("changes") or []]
            if d.get("error"):
                lines.append((f"{h}      {d['error']}", "red"))
            return lines
        if e.kind == "command_run":
            result = "error" if d["exit"] is None else f"exit {d['exit']}"
            lines = [(f"{h}  $ {d['command']}  → {result} ({d['duration']:.1f}s)", "dim")]
            if self.level >= 4:
                for stream in ("stdout", "stderr"):
                    lines += [(f"{h}    {line}", "dim") for line in (d.get(stream) or "").splitlines()]
            return lines
        if e.kind == "trigger_fired":
            ok = d["ok"]
            return [(f"{h}  trigger {d['trigger']} " + ("✓" if ok else f"✗ {d.get('error') or ''}".rstrip()),
                     "green" if ok else "red")]
        if e.kind == "note":
            return [(f"{h}{d['message']}", "yellow")]
        if e.kind == "run_finished":
            return [(f"run {e.run_id}: {d['status']} in {d['duration']:.1f}s (bastet log export {e.run_id})", "dim")]
        return []
