import base64
from pathlib import Path

import pytest

import bastet.cli.gather as gather_mod
from bastet.cli.app import app
from bastet.core.factsnote import facts_path, render_facts
from bastet.core.hostkeys import parse_keyscan, record
from bastet.core.remote import CommandResult
from conftest import git
from unifi_fixtures import AP, GATEWAY, HOST_MAC, SWITCH

KEYS = parse_keyscan(f"h ssh-ed25519 {base64.b64encode(b'fake-unifi-key').decode()}\n")
REC = record(KEYS[0])
DUMPS = {"10.10.0.1": GATEWAY, "10.10.0.3": AP, "10.10.0.5": SWITCH}


class DumpRunner:
    def __init__(self, address):
        self.address, self.name = address, f"admin@{address}"

    def run(self, script, *, timeout=120):
        if "mca-dump" not in script:
            return CommandResult("", "", 127)
        return CommandResult(DUMPS.get(self.address, ""), "", 0 if self.address in DUMPS else 127)


@pytest.fixture
def unifi_lab(inventory, monkeypatch):
    h = inventory / "hosts"
    (h / "uxg.md").write_text(f"---\nbastet: host\ntype: unifi-gateway\nip: 10.10.0.1\ngather: true\nssh_host_key: {REC}\n---\n# uxg\n")
    (h / "ap.md").write_text(f"---\nbastet: host\ntype: unifi-ap\nip: 10.10.0.3\ngather: true\nssh_host_key: {REC}\n---\n# ap\n")
    (h / "sw.md").write_text(f"---\nbastet: host\ntype: unifi-switch\nip: 10.10.0.5\ngather: true\nssh_host_key: {REC}\n---\n# sw\n")
    (h / "nas.md").write_text("---\nbastet: host\ntype: server\nip: 10.10.0.20\ngather: false\n---\n# nas\n")
    facts_path(inventory, "nas").parent.mkdir(parents=True, exist_ok=True)
    facts_path(inventory, "nas").write_text(
        render_facts("nas", {"interfaces": [{"name": "eno1", "mac": HOST_MAC}]}, "2026-10-06T10:00:00Z"))
    git(inventory, "add", ".")
    git(inventory, "commit", "-q", "-m", "unifi")
    monkeypatch.setattr(gather_mod, "scan_keys", lambda address, recorded=None, port=22: KEYS)
    monkeypatch.setattr(gather_mod, "ssh_runner", lambda target: DumpRunner(target.address))
    return inventory


def facts(root: Path, name: str) -> str:
    path = facts_path(root, name)
    return path.read_text() if path.exists() else ""


def test_gather_unifi_writes_facts_hardware_and_links(runner, unifi_lab, tmp_path):
    result = runner.invoke(app, ["run", "-g", "uxg", "ap", "sw", "-y"])
    assert result.exit_code == 0, result.output
    uxg = facts(unifi_lab, "uxg")
    assert "firmware: 6.0.10" in uxg and "mac: 02:00:00:00:00:01" in uxg and "media: SFP+" in uxg
    assert "SECRET" not in uxg
    hw = (unifi_lab / "hardware" / "Ubiquiti Gateway Fiber 1C0B8B000001.md").read_text()
    assert "category: gateway" in hw
    nas = facts(unifi_lab, "nas")
    assert "port: eno1" in nas and 'to: "[[sw]]"' in nas and 'to_port: "2"' in nas


def test_device_without_mca_dump_is_an_error(runner, unifi_lab):
    (unifi_lab / "hosts" / "odd.md").write_text(f"---\nbastet: host\ntype: unifi-switch\nip: 10.10.0.9\ngather: true\nssh_host_key: {REC}\n---\n# odd\n")
    result = runner.invoke(app, ["run", "-g", "odd", "uxg", "-y"])
    assert "odd: mca-dump" in result.output and "firmware: 6.0.10" in facts(unifi_lab, "uxg")


def test_link_conflict_is_a_warning_and_the_file_wins(runner, unifi_lab):
    nas = unifi_lab / "hosts" / "nas.md"
    nas.write_text(nas.read_text().replace(
        "gather: false\n", 'gather: false\nlinks:\n  - port: eno1\n    to: "[[uxg]]"\n    to_port: "9"\n  - just a note\n'))
    result = runner.invoke(app, ["run", "-g", "sw", "-y"])
    assert result.exit_code == 0, result.output
    assert "⚠ nas: link eno1: seen on [[sw]] port 2" in result.output
    text = nas.read_text()
    assert 'to_port: "9"' in text and "just a note" in text and "[[sw]]" not in text
