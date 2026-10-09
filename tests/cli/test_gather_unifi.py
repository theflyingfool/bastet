import base64
import json
import re
from pathlib import Path

import pytest

import bastet.cli.gather as gather_mod
from bastet.cli.app import app
from bastet.core.factsnote import facts_path, render_facts
from bastet.core.remote import CommandResult
from conftest import git
from gather_fixtures import LAPTOP, stdout_for
from unifi_fixtures import AP, GATEWAY, HOST_MAC, SWITCH

from bastet.core.hostkeys import parse_keyscan, record  # noqa: E402

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
    assert "interface: br0" in uxg and "198.51.100" not in uxg
    assert "10.10.0.0/24 (br0) is on the gateway but not in the lab file's networks" in result.output
    hw = (unifi_lab / "hardware" / "Ubiquiti Gateway Fiber 1C0B8B000001.md").read_text()
    assert "category: gateway" in hw and 'installed_in: "[[uxg]]"' in hw
    assert 'to: "[[uxg]]"' in facts(unifi_lab, "ap")
    assert "to" not in (unifi_lab / "hosts" / "ap.md").read_text()
    nas = facts(unifi_lab, "nas")
    assert "port: eno1" in nas and 'to: "[[sw]]"' in nas and 'to_port: "2"' in nas
    nas_note = (unifi_lab / "hosts" / "nas.md").read_text()
    assert "links" not in nas_note
    snaps = list((tmp_path / "data" / "bastet" / "snapshots" / "uxg").glob("*.json"))
    assert snaps and "SECRET-AUTHKEY" not in snaps[0].read_text()
    again = runner.invoke(app, ["run", "-g", "uxg", "ap", "sw", "-y"])
    assert again.exit_code == 0 and (unifi_lab / "hosts" / "nas.md").read_text() == nas_note


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


def test_links_survive_a_direct_gather_of_the_host(runner, unifi_lab, monkeypatch):
    """`links` in a facts note comes from something else's gather (a UniFi device seeing the host's
    cabling), never the host's own -- a direct gather of the host itself must keep it."""
    result = runner.invoke(app, ["run", "-g", "sw", "-y"])
    assert result.exit_code == 0, result.output
    assert 'to: "[[sw]]"' in facts(unifi_lab, "nas")

    class NasRunner:
        name = "x"

        def run(self, script, *, timeout=120):
            match = re.search(r"'(@@BASTET[^']*@@)'", script)
            if match is None:
                return CommandResult("", "", 0)
            return CommandResult(stdout_for(dict(LAPTOP, hostname="nas"), match.group(1)), "", 0)

    monkeypatch.setattr(gather_mod, "ssh_runner", lambda target: NasRunner())
    result = runner.invoke(app, ["run", "-g", "nas", "-y", "--accept-new-hostkey"])
    assert result.exit_code == 0, result.output
    note = facts(unifi_lab, "nas")
    assert 'to: "[[sw]]"' in note and "os: Arch Linux" in note
    assert "links" not in (unifi_lab / "hosts" / "nas.md").read_text()


def test_unifi_gather_replaces_links_not_merges_them(runner, unifi_lab, monkeypatch):
    """The UniFi path always writes what it currently sees for a host's `links` -- it doesn't keep
    yesterday's entry once the cabling has moved, unlike the keep-if-not-observed rule a host's own
    gather uses for OBSERVED_BY_OTHERS keys."""
    result = runner.invoke(app, ["run", "-g", "sw", "-y"])
    assert result.exit_code == 0, result.output
    assert 'to_port: "2"' in facts(unifi_lab, "nas")

    switch_data = json.loads(SWITCH)
    switch_data["port_table"][0]["mac_table"] = []
    switch_data["port_table"][1]["mac_table"] = [{"mac": HOST_MAC}]
    moved = json.dumps(switch_data)

    class MovedRunner:
        def __init__(self, address):
            self.address, self.name = address, f"admin@{address}"

        def run(self, script, *, timeout=120):
            if "mca-dump" not in script:
                return CommandResult("", "", 127)
            return CommandResult(moved, "", 0)

    monkeypatch.setattr(gather_mod, "ssh_runner", lambda target: MovedRunner(target.address))
    result = runner.invoke(app, ["run", "-g", "sw", "-y"])
    assert result.exit_code == 0, result.output
    after = facts(unifi_lab, "nas")
    assert 'to_port: "8"' in after and 'to_port: "2"' not in after


def _second_switch(unifi_lab, address="10.10.0.6"):
    """Another UniFi switch, cabled to `nas` on a port of its own -- so `nas` is seen by two devices."""
    (unifi_lab / "hosts" / "sw2.md").write_text(
        f"---\nbastet: host\ntype: unifi-switch\nip: {address}\ngather: true\nssh_host_key: {REC}\n---\n# sw2\n"
    )
    git(unifi_lab, "add", ".")
    git(unifi_lab, "commit", "-q", "-m", "second switch")
    sw2 = json.loads(SWITCH)
    sw2["mac"] = "02:00:00:00:00:09"
    sw2["serial"] = "9041B2000009"
    sw2["port_table"] = [{"port_idx": 5, "name": "Data", "media": "2P5GE", "is_uplink": False, "mac_table": [{"mac": HOST_MAC}]}]
    sw2["lldp_table"] = []
    return address, json.dumps(sw2)


class _MultiDumpRunner:
    def __init__(self, address, dumps):
        self.address, self.name, self.dumps = address, f"admin@{address}", dumps

    def run(self, script, *, timeout=120):
        if "mca-dump" not in script:
            return CommandResult("", "", 127)
        return CommandResult(self.dumps.get(self.address, ""), "", 0 if self.address in self.dumps else 127)


def test_links_seen_by_another_device_survive_a_regather_of_just_one(runner, unifi_lab, monkeypatch):
    """A host cabled to two switches: regathering one of them must not drop what the other saw -- only
    `bastet gather sw` or `bastet gather sw2` alone touches that device's own entries."""
    address, dump = _second_switch(unifi_lab)
    real_dumps = dict(DUMPS, **{address: dump})
    monkeypatch.setattr(gather_mod, "ssh_runner", lambda target: _MultiDumpRunner(target.address, real_dumps))

    result = runner.invoke(app, ["run", "-g", "sw2", "-y"])
    assert result.exit_code == 0, result.output
    assert 'to_port: "5"' in facts(unifi_lab, "nas") and "seen_by: sw2" in facts(unifi_lab, "nas")

    result = runner.invoke(app, ["run", "-g", "sw", "-y"])
    assert result.exit_code == 0, result.output
    after = facts(unifi_lab, "nas")
    assert 'to_port: "2"' in after and "sw" in after  # sw's own, freshly observed
    assert 'to_port: "5"' in after  # sw2's, untouched by this run


def test_unplugged_link_disappears_when_its_device_is_regathered(runner, unifi_lab, monkeypatch):
    """A host that's no longer cabled to a switch: that switch's own regather must drop the stale
    entry it used to see, not keep reporting cabling that's gone."""
    result = runner.invoke(app, ["run", "-g", "sw", "-y"])
    assert result.exit_code == 0, result.output
    assert 'to_port: "2"' in facts(unifi_lab, "nas")

    switch_data = json.loads(SWITCH)
    switch_data["port_table"][0]["mac_table"] = []  # nas unplugged
    unplugged = json.dumps(switch_data)

    class UnpluggedRunner:
        def __init__(self, address):
            self.address, self.name = address, f"admin@{address}"

        def run(self, script, *, timeout=120):
            if "mca-dump" not in script:
                return CommandResult("", "", 127)
            return CommandResult(unplugged, "", 0)

    monkeypatch.setattr(gather_mod, "ssh_runner", lambda target: UnpluggedRunner(target.address))
    result = runner.invoke(app, ["run", "-g", "sw", "-y"])
    assert result.exit_code == 0, result.output
    after = facts(unifi_lab, "nas")
    assert "links" not in after or '"[[sw]]"' not in after


def test_no_lab_networks_means_no_gateway_network_warnings(runner, unifi_lab):
    lab = unifi_lab / "Homelab.md"
    lab.write_text("---\nbastet: lab\n---\n# Homelab\n")
    git(unifi_lab, "commit", "-qam", "no networks")
    result = runner.invoke(app, ["run", "-g", "uxg", "-y"])
    assert result.exit_code == 0, result.output
    assert "is on the gateway but not" not in result.output
