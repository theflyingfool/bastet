import json

from bastet.core.collect import (
    MARK, PROBES, Probe, ProbeResult, Snapshot, build_script, collect, parse_sections, save_snapshot,
)
from bastet.core.remote import LocalRunner


def test_probe_names_unique_and_required_set():
    names = [p.name for p in PROBES]
    assert len(names) == len(set(names))
    assert {p.name for p in PROBES if p.required} >= {"os_release", "uname", "lscpu", "meminfo", "lsblk", "ip_addr"}


def test_script_runs_locally_and_marks_missing_tools():
    probes = (
        Probe("greet", "echo hello", "echo"),
        Probe("nope", "definitely-not-a-real-command-xyz", "nope"),
        Probe("multi", "printf 'a\\nb\\n'", "printf"),
    )
    snap = collect(LocalRunner(), "testhost", probes)
    assert snap.results["greet"] == ProbeResult(0, "hello")
    assert snap.results["nope"].missing
    assert snap.results["multi"].output == "a\nb"
    assert snap.host == "testhost" and snap.runner == "local"


def test_parse_sections():
    out = f"{MARK} a 0\nline1\nline2\n{MARK} b 1\n\n"
    assert parse_sections(out) == {"a": ProbeResult(0, "line1\nline2"), "b": ProbeResult(1, "")}


def test_build_script_has_every_probe():
    script = build_script()
    for p in PROBES:
        assert f"'{p.name}'" in script


def test_save_snapshot(tmp_path):
    snap = Snapshot("vps1", "bastet@h", "2026-10-01T12:00:00Z", {"a": ProbeResult(0, "x")})
    path = save_snapshot(snap, tmp_path)
    assert path.parent == tmp_path / "snapshots" / "vps1"
    data = json.loads(path.read_text())
    assert data["results"]["a"] == {"returncode": 0, "output": "x"} and data["runner"] == "bastet@h"
