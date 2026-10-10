import base64
import json
import re
import subprocess
from pathlib import Path

import pytest

import bastet.cli.gather as gather_mod
from bastet.cli.app import app
from bastet.core.errors import AuthFailed, Unreachable
from bastet.core.factsnote import facts_path, render_facts
from bastet.core.hostkeys import parse_keyscan
from bastet.core.remote import CommandResult
from gather_fixtures import LAPTOP, VPS, stdout_for

KEYS = parse_keyscan(f"h ssh-ed25519 {base64.b64encode(b'fake-host-key').decode()}\n")


class FakeRunner:
    def __init__(self, outputs, name="fake"):
        self.outputs = outputs
        self.name = name

    def run(self, script, *, timeout=120):
        match = re.search(r"'(@@BASTET[^']*@@)'", script)
        if match is None:
            return CommandResult("", "", 0)  # the cheap `true` probe: always succeeds
        return CommandResult(stdout_for(self.outputs, match.group(1)), "", 0)


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout


def add_host(root: Path, name: str, text: str) -> None:
    (root / "hosts" / f"{name}.md").write_text(text)
    git(root, "add", f"hosts/{name}.md")
    git(root, "commit", "-q", "-m", f"add {name}")


def facts(root: Path, name: str) -> str:
    path = facts_path(root, name)
    return path.read_text() if path.exists() else ""


LAPTOP_HOST_KEY = f"ssh-ed25519 {KEYS[0].fingerprint}"


@pytest.fixture
def laptop(inventory, monkeypatch):
    add_host(
        inventory, "hp-13",
        f"---\nbastet: host\ntype: laptop\nip: dhcp\nconnection: local\nssh_host_key: {LAPTOP_HOST_KEY}\n---\n# hp-13\n",
    )
    monkeypatch.setattr(gather_mod, "scan_keys", lambda address, recorded=None, port=22: KEYS)
    monkeypatch.setattr(gather_mod, "ssh_runner", lambda target: FakeRunner(LAPTOP, f"{target.user}@{target.address}"))
    return inventory


@pytest.fixture
def vps(inventory, monkeypatch):
    add_host(inventory, "vps1", "---\nbastet: host\ntype: vps\nprovider: linode\nip: 203.0.113.10\n---\n# vps1\n")
    monkeypatch.setattr(gather_mod, "scan_keys", lambda address, recorded=None, port=22: KEYS)

    def runner(target):
        if target.user == "bastet":
            class Refuse:
                name = "bastet@x"

                def run(self, script, *, timeout=120):
                    raise AuthFailed("login refused")
            return Refuse()
        return FakeRunner(VPS, f"{target.user}@{target.address}")

    monkeypatch.setattr(gather_mod, "ssh_runner", runner)
    return inventory


def test_gather_local_laptop_writes_facts(runner, laptop, tmp_path):
    result = runner.invoke(app, ["run", "-g", "hp-13", "-y"])
    assert result.exit_code == 0, result.output
    host = (laptop / "hosts" / "hp-13.md").read_text()
    assert host == f"---\nbastet: host\ntype: laptop\nip: dhcp\nconnection: local\nssh_host_key: {LAPTOP_HOST_KEY}\n---\n# hp-13\n"
    note = facts(laptop, "hp-13")
    assert "os: Arch Linux" in note and "ram: 16 GB" in note and "cpu_cores: 4" in note
    assert (laptop / "hardware" / "HP Spectre x360 Convertible 13-ae0xx 5CD1234XYZ.md").exists()
    assert (laptop / "_bastet" / "hardware-here.base").exists()
    assert any(line.startswith("Bastet gather: hp-13 (+") for line in git(laptop, "log", "--format=%an %s").splitlines())
    snaps = list((tmp_path / "data" / "bastet" / "snapshots" / "hp-13").glob("*.json"))
    assert len(snaps) == 1 and json.loads(snaps[0].read_text())["host"] == "hp-13"


def test_second_gather_changes_nothing(runner, laptop):
    runner.invoke(app, ["run", "-g", "-y"])
    head = git(laptop, "rev-parse", "HEAD")
    result = runner.invoke(app, ["run", "-g", "-y"])
    assert result.exit_code == 0 and "up to date" in result.output
    assert git(laptop, "rev-parse", "HEAD") == head


def test_first_gather_hints_at_add_role_on_a_terminal_without_yes(runner, laptop, monkeypatch):
    import bastet.cli.common as common_mod

    monkeypatch.setattr(common_mod, "_stdout_is_tty", lambda: True)
    result = runner.invoke(app, ["run", "-g", "hp-13"], input="y\n")
    assert result.exit_code == 0, result.output
    assert "next: bastet add role --to hp-13" in result.output


def test_first_gather_hint_suppressed_with_yes(runner, laptop, monkeypatch):
    import bastet.cli.common as common_mod

    monkeypatch.setattr(common_mod, "_stdout_is_tty", lambda: True)
    result = runner.invoke(app, ["run", "-g", "hp-13", "-y"])
    assert result.exit_code == 0, result.output
    assert "next:" not in result.output


def test_second_gather_does_not_repeat_the_first_gather_hint(runner, laptop, monkeypatch):
    import bastet.cli.common as common_mod

    monkeypatch.setattr(common_mod, "_stdout_is_tty", lambda: True)
    runner.invoke(app, ["run", "-g", "hp-13"], input="y\n")
    result = runner.invoke(app, ["run", "-g", "hp-13"], input="y\n")
    assert "next:" not in result.output


def test_gather_never_writes_host_notes_only_facts_notes(runner, laptop, monkeypatch):
    """The guard: a two-host gather leaves every hosts/*.md byte-identical, with a facts note per
    host holding the observed values instead."""
    add_host(laptop, "vps1", "---\nbastet: host\ntype: vps\nprovider: linode\nip: 203.0.113.10\n---\n# vps1\n")
    before = {p.name: p.read_text() for p in (laptop / "hosts").glob("*.md")}

    def ssh_runner(target):
        if target.address == "127.0.0.1":
            return FakeRunner(LAPTOP, f"{target.user}@{target.address}")
        if target.user == "bastet":
            class Refuse:
                name = "bastet@x"

                def run(self, script, *, timeout=120):
                    raise AuthFailed("login refused")
            return Refuse()
        return FakeRunner(VPS, f"{target.user}@{target.address}")

    monkeypatch.setattr(gather_mod, "ssh_runner", ssh_runner)
    result = runner.invoke(app, ["run", "-g", "-y", "--accept-new-hostkey"])
    assert result.exit_code == 0, result.output
    after = {p.name: p.read_text() for p in (laptop / "hosts").glob("*.md")}
    assert after == before
    assert "os: Arch Linux" in facts(laptop, "hp-13") and "ssh_host_key" in facts(laptop, "hp-13")
    assert "os: Debian GNU/Linux 13 (trixie)" in facts(laptop, "vps1") and "ssh_host_key" in facts(laptop, "vps1")


def test_gather_guard_node_with_guest_and_unifi_link(runner, inventory, monkeypatch):
    """The guard, extended: a Proxmox node observing a guest's vmid, and a UniFi switch proposing a
    link onto a plain host, both still leave every hosts/*.md byte-identical -- the vmid and the link
    land in facts notes instead."""
    from bastet.core.hostkeys import record
    from gather_fixtures import SERVER
    from unifi_fixtures import HOST_MAC, SWITCH

    add_host(inventory, "git1", '---\nbastet: host\ntype: lxc\nruns_on: "[[pve1]]"\nip: 10.0.20.21/24\n---\n# git1\n')
    rec = record(KEYS[0])
    add_host(inventory, "sw", f"---\nbastet: host\ntype: unifi-switch\nip: 10.10.0.5\nssh_host_key: {rec}\n---\n# sw\n")
    add_host(
        inventory, "nas",
        "---\nbastet: host\ntype: server\nip: 10.10.0.20\ngather: false\n"
        'links:\n  - port: eno1\n    to: "[[other-switch]]"\n    to_port: "9"\n'
        "---\n# nas\n",
    )
    facts_path(inventory, "nas").parent.mkdir(parents=True, exist_ok=True)
    facts_path(inventory, "nas").write_text(
        render_facts("nas", {"interfaces": [{"name": "eno1", "mac": HOST_MAC}]}, "2026-10-06T10:00:00Z"))
    git(inventory, "add", str(facts_path(inventory, "nas").relative_to(inventory)))
    git(inventory, "commit", "-q", "-m", "nas facts")
    before = {p.name: p.read_text() for p in (inventory / "hosts").glob("*.md")}

    monkeypatch.setattr(gather_mod, "scan_keys", lambda address, recorded=None, port=22: KEYS)

    class DumpRunner:
        name = "admin@10.10.0.5"

        def run(self, script, *, timeout=120):
            if "mca-dump" not in script:
                return CommandResult("", "", 127)
            return CommandResult(SWITCH, "", 0)

    def ssh_runner(target):
        if target.address == "10.10.0.5":
            return DumpRunner()
        if target.user == "bastet":
            class Refuse:
                name = "bastet@x"

                def run(self, script, *, timeout=120):
                    raise AuthFailed("login refused")
            return Refuse()
        return FakeRunner(SERVER, f"{target.user}@{target.address}")

    monkeypatch.setattr(gather_mod, "ssh_runner", ssh_runner)
    result = runner.invoke(app, ["run", "-g", "pve1", "sw", "-y", "--accept-new-hostkey"])
    assert result.exit_code == 0, result.output

    after = {p.name: p.read_text() for p in (inventory / "hosts").glob("*.md")}
    assert after == before

    assert "vmid: 104" in facts(inventory, "git1")
    assert 'to: "[[sw]]"' in facts(inventory, "nas")  # observed, raw, in the facts note

    # the port conflicts with nas's own declared link -- reported, and the declared entry still wins
    assert "link eno1: seen on [[sw]] port 2" in result.output and "left as written" in result.output
    from bastet.core.hosttypes import load_host_types
    from bastet.core.hostview import host_data
    from bastet.core.inventory import load_inventory

    inv = load_inventory(inventory, load_host_types())
    data = host_data(inv, inv.get("nas"), load_host_types())
    assert data["links"] == [{"port": "eno1", "to": "[[other-switch]]", "to_port": "9"}]


def test_host_fact_on_note_is_silently_overwritten_no_attribution(runner, laptop):
    """Host facts have no attribution or --take any more: a hand-set value in the note is simply
    replaced by the observed one in the facts note, with no warning."""
    runner.invoke(app, ["run", "-g", "-y"])
    p = laptop / "hosts" / "hp-13.md"
    p.write_text(p.read_text().replace("ip: dhcp", "ip: dhcp\nram: 32 GB"))
    git(laptop, "commit", "-q", "-am", "upgraded ram")
    result = runner.invoke(app, ["run", "-g", "-y"])
    assert result.exit_code == 0
    assert "ram: 32 GB" in p.read_text()
    assert "ram: 16 GB" in facts(laptop, "hp-13")
    assert "Tester" not in result.output and "--take ram" not in result.output


def test_vps_first_contact_refused_with_yes(runner, vps):
    result = runner.invoke(app, ["run", "-g", "vps1", "-y"])
    assert result.exit_code == 0 and "first contact" in result.output
    assert "os:" not in (vps / "hosts" / "vps1.md").read_text()


def test_vps_accept_hostkey_falls_back_to_own_login(runner, vps):
    result = runner.invoke(app, ["run", "-g", "vps1", "-y", "--accept-new-hostkey"])
    assert result.exit_code == 0, result.output
    text = facts(vps, "vps1")
    assert f"ssh_host_key: ssh-ed25519 {KEYS[0].fingerprint}" in text
    assert "os: Debian GNU/Linux 13 (trixie)" in text and "storage: 80 GB" in text
    assert "not set up" in result.output
    assert "ssh_host_key" not in (vps / "hosts" / "vps1.md").read_text()


def test_vps_interactive_trust(runner, vps):
    result = runner.invoke(app, ["run", "-g", "vps1"], input="y\ny\n")
    assert result.exit_code == 0, result.output
    assert "ssh_host_key:" in facts(vps, "vps1")


def test_changed_hostkey_stops(runner, vps):
    p = vps / "hosts" / "vps1.md"
    p.write_text(p.read_text().replace("ip: 203.0.113.10\n", "ip: 203.0.113.10\nssh_host_key: ssh-ed25519 SHA256:old\n"))
    git(vps, "commit", "-q", "-am", "key")
    before = p.read_text()
    result = runner.invoke(app, ["run", "-g", "vps1", "-y"])
    assert "host key changed" in result.output and "--accept-new-hostkey" in result.output
    assert p.read_text() == before
    assert "gathered:" not in facts(vps, "vps1")  # refresh may still create the facts note's cards


def test_changed_key_in_the_facts_note_is_refused_then_accepted(runner, vps, monkeypatch):
    monkeypatch.setattr(gather_mod, "scan_keys", lambda address, recorded=None, port=22: KEYS)
    runner.invoke(app, ["run", "-g", "vps1", "-y", "--accept-new-hostkey"])
    recorded = facts(vps, "vps1")
    assert f"ssh_host_key: ssh-ed25519 {KEYS[0].fingerprint}" in recorded

    evil = parse_keyscan(f"h ssh-rsa {base64.b64encode(b'new-key').decode()}\n")
    monkeypatch.setattr(gather_mod, "scan_keys", lambda address, recorded=None, port=22: evil)
    result = runner.invoke(app, ["run", "-g", "vps1", "-y"])
    assert "host key changed" in result.output and "--accept-new-hostkey" in result.output
    assert facts(vps, "vps1") == recorded  # the facts note is untouched by the refusal

    result = runner.invoke(app, ["run", "-g", "vps1", "-y", "--accept-new-hostkey"])
    assert result.exit_code == 0, result.output
    assert f"ssh_host_key: ssh-rsa {evil[0].fingerprint}" in facts(vps, "vps1")


def test_facts_note_key_wins_over_a_stale_host_note_key(runner, vps, monkeypatch):
    """A fallback-only use case: once the facts note has the key, a leftover (and now wrong)
    ssh_host_key on the host note must not cause a false 'changed' refusal."""
    monkeypatch.setattr(gather_mod, "scan_keys", lambda address, recorded=None, port=22: KEYS)
    runner.invoke(app, ["run", "-g", "vps1", "-y", "--accept-new-hostkey"])
    p = vps / "hosts" / "vps1.md"
    p.write_text(p.read_text().replace("ip: 203.0.113.10\n", "ip: 203.0.113.10\nssh_host_key: ssh-ed25519 SHA256:old\n"))
    git(vps, "commit", "-q", "-am", "stale key")
    result = runner.invoke(app, ["run", "-g", "vps1", "-y"])
    assert result.exit_code == 0, result.output
    assert "host key changed" not in result.output
    assert "os:" in facts(vps, "vps1")


def test_unreachable_host_does_not_stop_others(runner, laptop, monkeypatch):
    add_host(laptop, "vps1", "---\nbastet: host\ntype: vps\nprovider: linode\nip: 203.0.113.10\n---\n# vps1\n")

    def down(address, recorded=None, port=22):
        if address == "127.0.0.1":
            return KEYS
        raise Unreachable(f"{address}: no SSH host keys")

    monkeypatch.setattr(gather_mod, "scan_keys", down)
    result = runner.invoke(app, ["run", "-g", "-y"])
    assert result.exit_code == 0, result.output
    assert "vps1" in result.output and "no SSH host keys" in result.output
    assert "os: Arch Linux" in facts(laptop, "hp-13")


def test_dhcp_host_without_address_is_reported(runner, inventory):
    add_host(inventory, "roamer", "---\nbastet: host\ntype: laptop\nip: dhcp\n---\n# roamer\n")
    result = runner.invoke(app, ["run", "-g", "roamer", "-y"])
    assert result.exit_code == 0 and "no address" in result.output


def test_unknown_host_name(runner, inventory):
    result = runner.invoke(app, ["run", "-g", "nope"])
    assert result.exit_code == 1 and "no host named 'nope'" in result.output


def test_jobs_zero_is_a_usage_error(runner, inventory):
    result = runner.invoke(app, ["run", "-g", "nope", "-j", "0"])
    assert result.exit_code == 2
    assert "no host named 'nope'" not in result.output


def test_jobs_option_is_accepted(runner, inventory):
    result = runner.invoke(app, ["run", "-g", "nope", "-j", "2"])
    assert result.exit_code == 1 and "no host named 'nope'" in result.output


def test_gather_malformed_host_file_reports_problem(runner, laptop):
    (laptop / "hosts" / "broken.md").write_text("---\nbastet: host\n")
    result = runner.invoke(app, ["run", "-g", "hp-13", "-y"])
    assert result.exit_code == 0, result.output
    assert "broken.md" in result.output and "ignored" in result.output


def test_gather_named_broken_host_explains_error(runner, laptop):
    (laptop / "hosts" / "broken.md").write_text("---\nbastet: host\n")
    result = runner.invoke(app, ["run", "-g", "broken", "-y"])
    assert result.exit_code == 1
    assert "no host named 'broken'" in result.output
    assert "frontmatter is not closed" in result.output


def test_accepted_key_replaces_recorded_and_pins_only_one(runner, vps, monkeypatch):
    evil = parse_keyscan(f"h ssh-rsa {base64.b64encode(b'evil').decode()}\n")
    monkeypatch.setattr(gather_mod, "scan_keys", lambda address, recorded=None, port=22: KEYS + evil)
    seen = {}
    real_write = gather_mod.hostkeys.write_known_hosts

    def spy(keys, address, port, directory):
        seen["keys"] = list(keys)
        return real_write(keys, address, port, directory)

    monkeypatch.setattr(gather_mod.hostkeys, "write_known_hosts", spy)
    p = vps / "hosts" / "vps1.md"
    p.write_text(p.read_text().replace("ip: 203.0.113.10\n", "ip: 203.0.113.10\nssh_host_key: ssh-ed25519 SHA256:old\n"))
    git(vps, "commit", "-q", "-am", "old key")
    result = runner.invoke(app, ["run", "-g", "vps1", "-y", "--accept-new-hostkey"])
    assert result.exit_code == 0, result.output
    assert seen["keys"] == KEYS
    assert f"ssh_host_key: ssh-ed25519 {KEYS[0].fingerprint}" in facts(vps, "vps1")


def test_unexpected_error_on_one_host_does_not_stop_others(runner, laptop, monkeypatch):
    add_host(laptop, "vps1", "---\nbastet: host\ntype: vps\nprovider: linode\nip: 203.0.113.10\n---\n# vps1\n")

    def boom(address, recorded=None, port=22):
        if address == "127.0.0.1":
            return KEYS
        raise RuntimeError("something odd")

    monkeypatch.setattr(gather_mod, "scan_keys", boom)
    result = runner.invoke(app, ["run", "-g", "-y"])
    assert result.exit_code == 0, result.output
    assert "something odd" in result.output
    assert "os: Arch Linux" in facts(laptop, "hp-13")


from gather_fixtures import SERVER  # noqa: E402


@pytest.fixture
def server(inventory, monkeypatch):
    monkeypatch.setattr(gather_mod, "scan_keys", lambda address, recorded=None, port=22: KEYS)

    def runner(target):
        if target.user == "bastet":
            class Refuse:
                name = "bastet@x"

                def run(self, script, *, timeout=120):
                    raise AuthFailed("login refused")
            return Refuse()
        return FakeRunner(SERVER, f"{target.user}@{target.address}")

    monkeypatch.setattr(gather_mod, "ssh_runner", runner)
    return inventory


def test_gather_server_creates_hardware_files(runner, server):
    result = runner.invoke(app, ["run", "-g", "pve1", "-y", "--accept-new-hostkey"])
    assert result.exit_code == 0, result.output
    hw = sorted(p.name for p in (server / "hardware").glob("*.md"))
    assert "Supermicro SYS-5019C-MR S123456X.md" in hw and len(hw) == 10
    assert (server / "hosts" / "pve1.md").read_text() == "---\nbastet: host\ntype: proxmox\nip: 10.0.10.11\n---\n# pve1\n"
    assert "pools:\n  - name: tank\n    state: ONLINE\n" in facts(server, "pve1")
    assert "git1" in result.output and "media" in result.output and "aren't in the inventory" in result.output
    files = git(server, "log", "-1", "--name-only", "--format=", "--grep=^gather").splitlines()
    assert "_bastet/facts/pve1 facts.md" in files and any(f.startswith("hardware/") for f in files)
    assert "hosts/pve1.md" not in files


def test_root_skipped_note(runner, server, monkeypatch):
    monkeypatch.setattr(gather_mod, "ssh_runner", lambda target: FakeRunner(
        dict(SERVER, privilege="none", dmidecode=(126, ""), smart=(126, ""), ipmi=(126, ""), pve_guests=(126, "")), "x"))
    result = runner.invoke(app, ["run", "-g", "pve1", "-y", "--accept-new-hostkey"])
    assert result.exit_code == 0, result.output
    assert "root-only" in result.output


def test_local_host_writes_hardware_file(runner, laptop):
    result = runner.invoke(app, ["run", "-g", "hp-13", "-y"])
    assert result.exit_code == 0, result.output
    assert (laptop / "hardware" / "HP Spectre x360 Convertible 13-ae0xx 5CD1234XYZ.md").exists()


def test_local_host_with_no_recorded_key_goes_through_first_contact(runner, inventory, monkeypatch):
    add_host(inventory, "hp-13", "---\nbastet: host\ntype: laptop\nip: dhcp\nconnection: local\n---\n# hp-13\n")
    monkeypatch.setattr(gather_mod, "scan_keys", lambda address, recorded=None, port=22: KEYS)
    monkeypatch.setattr(gather_mod, "ssh_runner", lambda target: FakeRunner(LAPTOP, f"{target.user}@{target.address}"))
    result = runner.invoke(app, ["run", "-g", "hp-13"], input="y\ny\n")
    assert result.exit_code == 0, result.output
    assert "first contact" in result.output
    assert f"ssh_host_key: ssh-ed25519 {KEYS[0].fingerprint}" in facts(inventory, "hp-13")


def test_local_host_nothing_answering_reports_sshd_hint(runner, inventory, monkeypatch):
    add_host(inventory, "hp-13", "---\nbastet: host\ntype: laptop\nip: dhcp\nconnection: local\n---\n# hp-13\n")

    def no_sshd(address, recorded=None, port=22):
        raise Unreachable(f"{address}: offline in tests")

    monkeypatch.setattr(gather_mod, "scan_keys", no_sshd)
    result = runner.invoke(app, ["run", "-g", "hp-13", "-y"])
    assert result.exit_code == 0, result.output
    assert "nothing answered on 127.0.0.1:22" in result.output
    assert "start sshd" in result.output


def test_local_host_with_custom_address_nothing_answering_reports_that_address(runner, inventory, monkeypatch):
    add_host(
        inventory, "hp-13",
        "---\nbastet: host\ntype: laptop\nip: dhcp\nconnection: local\naddress: 10.0.0.5\n---\n# hp-13\n",
    )

    def no_sshd(address, recorded=None, port=22):
        raise Unreachable(f"{address}: offline in tests")

    monkeypatch.setattr(gather_mod, "scan_keys", no_sshd)
    result = runner.invoke(app, ["run", "-g", "hp-13", "-y"])
    assert result.exit_code == 0, result.output
    assert "nothing answered on 10.0.0.5:22" in result.output


def test_guests_on_other_nodes_ignored_and_names_quoted(runner, server, monkeypatch):
    guests = json.dumps([
        {"vmid": 104, "name": "git1", "type": "lxc", "node": "pve1", "status": "running"},
        {"vmid": 200, "name": "elsewhere", "type": "qemu", "node": "pve2", "status": "running"},
        {"vmid": 201, "name": "my box", "type": "qemu", "node": "pve1", "status": "running"},
    ])
    monkeypatch.setattr(gather_mod, "ssh_runner", lambda target: FakeRunner(dict(SERVER, pve_guests=guests), "x"))
    result = runner.invoke(app, ["run", "-g", "pve1", "-y", "--accept-new-hostkey"])
    assert "elsewhere" not in result.output
    assert "bastet add host 'my box'" in result.output



def test_gather_stores_warnings_in_facts_note_and_refresh_keeps_them(runner, server, monkeypatch):
    monkeypatch.setattr(gather_mod, "ssh_runner", lambda target: FakeRunner(
        dict(SERVER, privilege="none", dmidecode=(126, ""), smart=(126, ""), ipmi=(126, ""), pve_guests=(126, "")), "x"))
    runner.invoke(app, ["run", "-g", "pve1", "-y", "--accept-new-hostkey"])
    facts_text = facts(server, "pve1")
    assert "warnings:" in facts_text and "root-only" in facts_text and "[!warning]" in facts_text
    runner.invoke(app, ["refresh"])
    assert "root-only" in facts(server, "pve1")
    dash = (server / "_bastet" / "bastet dashboard.md").read_text()
    assert "Needs attention" in dash and "[[pve1]]" in dash


def test_found_guests_added_when_confirmed(runner, server):
    result = runner.invoke(app, ["run", "-g", "pve1", "--accept-new-hostkey"], input="y\ny\n")
    assert result.exit_code == 0, result.output
    assert "Add all 4" in result.output and "bastet add host git1 --type lxc --on pve1" in result.output
    git1 = (server / "hosts" / "git1.md").read_text()
    assert "type: lxc" in git1 and 'runs_on: "[[pve1]]"' in git1 and "ip: 10.0.20.21/24" in git1
    assert "vmid" not in git1
    assert "vmid: 104" in facts(server, "git1")
    from bastet.core.hosttypes import load_host_types
    from bastet.core.inventory import load_inventory

    reloaded = load_inventory(server, load_host_types())
    assert not [p for p in reloaded.problems if "git1" in str(p.error.file) and "vmid" in p.error.message]
    media = (server / "hosts" / "media.md").read_text()
    assert "type: vm" in media and "ip: dhcp" in media and "address: 10.0.20.25" in media
    ghost = (server / "hosts" / "ghost.md").read_text()
    assert "ip: dhcp" in ghost and "address:" not in ghost
    assert "ghost" in result.output and "set address" in result.output


def test_found_guests_not_added_on_no_or_yes_flag(runner, server):
    result = runner.invoke(app, ["run", "-g", "pve1", "--accept-new-hostkey"], input="n\ny\n")
    assert result.exit_code == 0, result.output
    assert not (server / "hosts" / "git1.md").exists()
    result = runner.invoke(app, ["run", "-g", "pve1", "-y"])
    assert "Add all" not in result.output and not (server / "hosts" / "git1.md").exists()


class InstallingRunner:
    """First collection lacks tools; after an install script runs, the next collection has them."""

    def __init__(self, before, after):
        self.before, self.after, self.installs, self.name = before, after, [], "x"

    def run(self, script, *, timeout=120):
        if "BASTET-INSTALL" in script:
            self.installs.append(script)
            return CommandResult("", "", 0)
        match = re.search(r"'(@@BASTET[^']*@@)'", script)
        if match is None:
            return CommandResult("", "", 0)  # the cheap `true` probe: always succeeds
        return CommandResult(stdout_for(self.after if self.installs else self.before, match.group(1)), "", 0)


def _rack_host(inventory):
    add_host(inventory, "pve3", "---\nbastet: host\ntype: proxmox\nip: 10.0.10.12\n---\n# pve3\n")


def test_missing_tools_installed_when_confirmed_and_recorded(runner, inventory, monkeypatch):
    from gather_fixtures import RACK
    _rack_host(inventory)
    fake = InstallingRunner(dict(RACK, pkg_mgr="apt-get"), dict(RACK, pkg_mgr="apt-get", ipmi=SERVER["ipmi"]))
    monkeypatch.setattr(gather_mod, "scan_keys", lambda address, recorded=None, port=22: KEYS)
    monkeypatch.setattr(gather_mod, "ssh_runner", lambda target: fake)
    result = runner.invoke(app, ["run", "-g", "pve3", "--accept-new-hostkey"], input="y\ny\n")
    assert result.exit_code == 0, result.output
    assert "install ipmitool" in result.output and len(fake.installs) == 1
    assert "bastet_tools:\n  - ipmitool\n" in facts(inventory, "pve3")
    name = next((inventory / "hardware").glob("ASRockRack*.md")).stem
    assert "oob_address: 10.0.10.9" in facts(inventory, name)


def test_tools_not_installed_with_yes_by_default_or_when_host_opts_out(runner, inventory, monkeypatch):
    from gather_fixtures import RACK
    _rack_host(inventory)
    fake = InstallingRunner(dict(RACK, pkg_mgr="apt-get"), dict(RACK, pkg_mgr="apt-get"))
    monkeypatch.setattr(gather_mod, "scan_keys", lambda address, recorded=None, port=22: KEYS)
    monkeypatch.setattr(gather_mod, "ssh_runner", lambda target: fake)
    runner.invoke(app, ["run", "-g", "pve3", "-y", "--accept-new-hostkey"])
    assert fake.installs == []
    p = inventory / "hosts" / "pve3.md"
    p.write_text(p.read_text().replace("type: proxmox\n", "type: proxmox\ninstall_tools: false\n"))
    git(inventory, "commit", "-q", "-am", "no tools here")
    runner.invoke(app, ["run", "-g", "pve3"], input="y\n")
    assert fake.installs == []


def test_config_always_installs_unattended(runner, inventory, monkeypatch, tmp_path):
    from gather_fixtures import RACK
    import os
    cfg = Path(os.environ["BASTET_CONFIG"])
    cfg.write_text(cfg.read_text() + "gather:\n  install_tools: always\n")
    _rack_host(inventory)
    fake = InstallingRunner(dict(RACK, pkg_mgr="apt-get"), dict(RACK, pkg_mgr="apt-get", ipmi=SERVER["ipmi"]))
    monkeypatch.setattr(gather_mod, "scan_keys", lambda address, recorded=None, port=22: KEYS)
    monkeypatch.setattr(gather_mod, "ssh_runner", lambda target: fake)
    result = runner.invoke(app, ["run", "-g", "pve3", "-y", "--accept-new-hostkey"])
    assert result.exit_code == 0, result.output
    assert len(fake.installs) == 1


def test_gather_false_skipped_unless_named(runner, laptop):
    p = laptop / "hosts" / "hp-13.md"
    p.write_text(p.read_text().replace("type: laptop\n", "type: laptop\ngather: false\n"))
    git(laptop, "commit", "-q", "-am", "not ready")
    result = runner.invoke(app, ["run", "-g", "-y"])
    assert "hp-13: skipped (gather: false)" in result.output and "gathered:" not in facts(laptop, "hp-13")
    runner.invoke(app, ["run", "-g", "hp-13", "-y"])
    assert "os: Arch Linux" in facts(laptop, "hp-13")


def test_unmanaged_type_is_skipped_even_when_named(runner, laptop, monkeypatch):
    """A type with `gather: false` (e.g. `other`) is never connected to, even named explicitly --
    unlike a host-level `gather: false`, which naming the host overrides."""
    add_host(laptop, "tv", "---\nbastet: host\ntype: other\nip: 10.10.0.30\n---\n# tv\n")

    def ssh_runner(target):
        raise AssertionError("an unmanaged type must never be connected to")

    monkeypatch.setattr(gather_mod, "ssh_runner", ssh_runner)
    result = runner.invoke(app, ["run", "-g", "tv", "-y"])
    assert result.exit_code == 0, result.output
    assert "tv: skipped (gather: false)" in result.output and facts(laptop, "tv") == ""


def _git1(inventory, extra=""):
    add_host(inventory, "git1", f'---\nbastet: host\ntype: lxc\nruns_on: "[[pve1]]"\nip: 10.0.20.99/24\n{extra}---\n# git1\n')


def test_guest_drift_reported_inline_on_page_and_dashboard_not_adopted(runner, server):
    _git1(server, "vmid: 104\n")
    result = runner.invoke(app, ["run", "-g", "pve1", "-y", "--accept-new-hostkey"])
    assert result.exit_code == 0, result.output
    assert "git1: drift" in result.output and "10.0.20.99/24" in result.output and "10.0.20.21/24" in result.output
    assert "ip: 10.0.20.99/24" in (server / "hosts" / "git1.md").read_text()
    git1_facts = facts(server, "git1")
    assert "drift:" in git1_facts and "[!danger] Drift" in git1_facts
    dash = (server / "_bastet" / "bastet dashboard.md").read_text()
    assert "[[git1]]" in dash and "drift" in dash.lower()
    runner.invoke(app, ["refresh"])
    assert "drift:" in facts(server, "git1")


def test_guest_drift_clears_when_they_agree_and_vmid_added(runner, server):
    _git1(server)
    p = server / "hosts" / "git1.md"
    p.write_text(p.read_text().replace("10.0.20.99/24", "10.0.20.21/24"))
    git(server, "commit", "-q", "-am", "fix ip")
    result = runner.invoke(app, ["run", "-g", "pve1", "-y", "--accept-new-hostkey"])
    assert "git1: drift" not in result.output
    assert "vmid: 104" in facts(server, "git1")
    assert "vmid" not in p.read_text()
    assert "[!danger]" not in facts(server, "git1")


def test_guest_on_another_node_is_drift(runner, server):
    _git1(server, "vmid: 104\n")
    p = server / "hosts" / "git1.md"
    p.write_text(p.read_text().replace('runs_on: "[[pve1]]"', 'runs_on: "[[pve9]]"'))
    git(server, "commit", "-q", "-am", "moved?")
    result = runner.invoke(app, ["run", "-g", "pve1", "-y", "--accept-new-hostkey"])
    assert "git1: drift" in result.output and "pve9" in result.output and "pve1" in result.output


def test_renamed_guest_matched_by_vmid_is_not_offered_as_new(runner, server):
    add_host(server, "oldname", '---\nbastet: host\ntype: lxc\nruns_on: "[[pve1]]"\nip: 10.0.20.21/24\nvmid: 104\n---\n# oldname\n')
    result = runner.invoke(app, ["run", "-g", "pve1", "--accept-new-hostkey"], input="n\ny\n")
    assert "git1 (lxc 104" not in result.output


def test_recreated_guest_vmid_is_overwritten_not_kept(runner, server):
    """git1 was recreated under a new vmid (its old one, 104, could now belong to a different guest) --
    the node still reports it by name, so the stale vmid already in its facts note must be replaced,
    not kept just because something is already there."""
    _git1(server, "vmid: 999\n")
    result = runner.invoke(app, ["run", "-g", "pve1", "-y", "--accept-new-hostkey"])
    assert result.exit_code == 0, result.output
    note = facts(server, "git1")
    assert "vmid: 104" in note and "vmid: 999" not in note


def test_guest_matched_by_name_even_when_its_old_vmid_now_belongs_to_another_guest(runner, server, monkeypatch):
    """git1 was recreated under vmid 110; its old vmid, 104, now belongs to media. Matching by vmid
    first would wrongly hand git1's update to whichever guest holds 104 -- it must match by name."""
    _git1(server, "vmid: 104\n")
    guests = json.dumps([
        {"id": "lxc/110", "vmid": 110, "name": "git1", "type": "lxc", "node": "pve1", "status": "running"},
        {"id": "qemu/104", "vmid": 104, "name": "media", "type": "qemu", "node": "pve1", "status": "running"},
    ])
    monkeypatch.setattr(gather_mod, "ssh_runner", lambda target: FakeRunner(dict(SERVER, pve_guests=guests), "x"))
    result = runner.invoke(app, ["run", "-g", "pve1", "-y", "--accept-new-hostkey"])
    assert result.exit_code == 0, result.output
    assert "vmid: 110" in facts(server, "git1")


def test_guest_vmid_preserved_through_its_own_direct_gather(runner, server, monkeypatch):
    """vmid is never observed by a guest's own gather (only the node sees it) -- a direct gather of
    the guest itself must keep whatever is already in its facts note."""
    _git1(server)
    result = runner.invoke(app, ["run", "-g", "pve1", "-y", "--accept-new-hostkey"])
    assert result.exit_code == 0, result.output
    assert "vmid: 104" in facts(server, "git1")

    real_ssh_runner = gather_mod.ssh_runner

    def ssh_runner(target):
        if target.address == "10.0.20.99":
            return FakeRunner(dict(LAPTOP, hostname="git1"), f"{target.user}@{target.address}")
        return real_ssh_runner(target)

    monkeypatch.setattr(gather_mod, "ssh_runner", ssh_runner)
    result = runner.invoke(app, ["run", "-g", "git1", "-y", "--accept-new-hostkey"])
    assert result.exit_code == 0, result.output
    note = facts(server, "git1")
    assert "vmid: 104" in note and "os: Arch Linux" in note
    assert "vmid" not in (server / "hosts" / "git1.md").read_text()


def _gather_node_and_guest(runner, server, monkeypatch, order):
    """pve1 and its guest git1, gathered together in one run -- the guest's own facts, its accepted
    host key and the vmid the node observes must all land in the one facts note, in either order."""
    _git1(server)
    real = gather_mod.ssh_runner

    def ssh_runner(target):
        if target.address == "10.0.20.99":
            return FakeRunner(dict(LAPTOP, hostname="git1"), f"{target.user}@{target.address}")
        return real(target)

    monkeypatch.setattr(gather_mod, "ssh_runner", ssh_runner)
    result = runner.invoke(app, ["run", "-g", *order, "-y", "--accept-new-hostkey"])
    assert result.exit_code == 0, result.output
    return facts(server, "git1")


def test_node_and_guest_same_run_node_first(runner, server, monkeypatch):
    note = _gather_node_and_guest(runner, server, monkeypatch, ["pve1", "git1"])
    assert "vmid: 104" in note, "vmid lost"
    assert "os: Arch Linux" in note, "guest facts lost"
    assert "ssh_host_key" in note, "guest's accepted host key lost"
    assert "pools:" not in note  # pve1's own hardware facts, not git1's


def test_node_and_guest_same_run_guest_first(runner, server, monkeypatch):
    note = _gather_node_and_guest(runner, server, monkeypatch, ["git1", "pve1"])
    assert "vmid: 104" in note, "vmid lost"
    assert "os: Arch Linux" in note, "guest facts lost"
    assert "ssh_host_key" in note, "guest's accepted host key lost"


# --- `run -g -a`: one commit for the whole run (plan Task 5) ---


def test_gather_then_apply_in_one_run_is_one_commit(runner, laptop):
    before = int(git(laptop, "rev-list", "--count", "HEAD").strip())
    result = runner.invoke(app, ["run", "-g", "-a", "hp-13", "-y"])
    assert result.exit_code == 0, result.output
    after = int(git(laptop, "rev-list", "--count", "HEAD").strip())
    assert after - before == 1
    subject = git(laptop, "log", "-1", "--format=%s").strip()
    assert subject.startswith("gather: hp-13") and "apply: hp-13" in subject
