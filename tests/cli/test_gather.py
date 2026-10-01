import base64
import json
import re
import subprocess
from pathlib import Path

import pytest

import bastet.cli.gather as gather_mod
from bastet.cli.app import app
from bastet.core.errors import AuthFailed, Unreachable
from bastet.core.hostkeys import parse_keyscan
from bastet.core.remote import CommandResult
from gather_fixtures import LAPTOP, VPS, stdout_for

KEYS = parse_keyscan(f"h ssh-ed25519 {base64.b64encode(b'fake-host-key').decode()}\n")


class FakeRunner:
    def __init__(self, outputs, name="fake"):
        self.outputs = outputs
        self.name = name

    def run(self, script, *, timeout=120):
        mark = re.search(r"'(@@BASTET[^']*@@)'", script).group(1)
        return CommandResult(stdout_for(self.outputs, mark), "", 0)


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout


def add_host(root: Path, name: str, text: str) -> None:
    (root / "hosts" / f"{name}.md").write_text(text)
    git(root, "add", f"hosts/{name}.md")
    git(root, "commit", "-q", "-m", f"add {name}")


@pytest.fixture
def laptop(inventory, monkeypatch):
    add_host(inventory, "hp-13", "---\nbastet: host\ntype: laptop\nip: dhcp\nconnection: local\n---\n# hp-13\n")
    monkeypatch.setattr(gather_mod, "local_runner", lambda: FakeRunner(LAPTOP, "local"))

    def no_network(address, recorded=None):
        raise Unreachable(f"{address}: offline in tests")

    monkeypatch.setattr(gather_mod, "scan_keys", no_network)
    return inventory


@pytest.fixture
def vps(inventory, monkeypatch):
    add_host(inventory, "vps1", "---\nbastet: host\ntype: vps\nprovider: linode\nip: 203.0.113.10\n---\n# vps1\n")
    monkeypatch.setattr(gather_mod, "scan_keys", lambda address, recorded=None: KEYS)

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
    result = runner.invoke(app, ["gather", "hp-13", "-y"])
    assert result.exit_code == 0, result.output
    text = (laptop / "hosts" / "hp-13.md").read_text()
    assert "os: Arch Linux" in text and "ram: 16 GB" in text and "cpu_cores: 4" in text
    assert "![[hardware-here.base]]" in text
    assert (laptop / "_bastet" / "hardware-here.base").exists()
    assert "Bastet gather: hp-13" in git(laptop, "log", "--format=%an %s").splitlines()
    snaps = list((tmp_path / "data" / "bastet" / "snapshots" / "hp-13").glob("*.json"))
    assert len(snaps) == 1 and json.loads(snaps[0].read_text())["host"] == "hp-13"


def test_second_gather_changes_nothing(runner, laptop):
    runner.invoke(app, ["gather", "-y"])
    head = git(laptop, "rev-parse", "HEAD")
    result = runner.invoke(app, ["gather", "-y"])
    assert result.exit_code == 0 and "up to date" in result.output
    assert git(laptop, "rev-parse", "HEAD") == head


def test_hand_set_value_kept_with_attribution(runner, laptop):
    runner.invoke(app, ["gather", "-y"])
    p = laptop / "hosts" / "hp-13.md"
    p.write_text(p.read_text().replace("ram: 16 GB", "ram: 32 GB"))
    git(laptop, "commit", "-q", "-am", "upgraded ram")
    result = runner.invoke(app, ["gather", "-y"])
    assert result.exit_code == 0
    assert "ram: 32 GB" in p.read_text()
    assert "Tester" in result.output and "--take ram" in result.output


def test_take_accepts_observed(runner, laptop):
    runner.invoke(app, ["gather", "-y"])
    p = laptop / "hosts" / "hp-13.md"
    p.write_text(p.read_text().replace("ram: 16 GB", "ram: 32 GB"))
    git(laptop, "commit", "-q", "-am", "upgraded ram")
    runner.invoke(app, ["gather", "--take", "ram", "-y"])
    assert "ram: 16 GB" in p.read_text()


def test_vps_first_contact_refused_with_yes(runner, vps):
    result = runner.invoke(app, ["gather", "vps1", "-y"])
    assert result.exit_code == 0 and "first contact" in result.output
    assert "os:" not in (vps / "hosts" / "vps1.md").read_text()


def test_vps_accept_hostkey_falls_back_to_own_login(runner, vps):
    result = runner.invoke(app, ["gather", "vps1", "-y", "--accept-new-hostkey"])
    assert result.exit_code == 0, result.output
    text = (vps / "hosts" / "vps1.md").read_text()
    assert f"ssh_host_key: ssh-ed25519 {KEYS[0].fingerprint}" in text
    assert "os: Debian GNU/Linux 13 (trixie)" in text and "storage: 80 GB" in text
    assert "not set up" in result.output


def test_vps_interactive_trust(runner, vps):
    result = runner.invoke(app, ["gather", "vps1"], input="y\ny\n")
    assert result.exit_code == 0, result.output
    assert "ssh_host_key:" in (vps / "hosts" / "vps1.md").read_text()


def test_changed_hostkey_stops(runner, vps):
    p = vps / "hosts" / "vps1.md"
    p.write_text(p.read_text().replace("ip: 203.0.113.10\n", "ip: 203.0.113.10\nssh_host_key: ssh-ed25519 SHA256:old\n"))
    git(vps, "commit", "-q", "-am", "key")
    before = p.read_text()
    result = runner.invoke(app, ["gather", "vps1", "-y"])
    assert "host key changed" in result.output and "--accept-new-hostkey" in result.output
    assert p.read_text() == before


def test_unreachable_host_does_not_stop_others(runner, laptop, monkeypatch):
    add_host(laptop, "vps1", "---\nbastet: host\ntype: vps\nprovider: linode\nip: 203.0.113.10\n---\n# vps1\n")

    def down(address, recorded=None):
        raise Unreachable(f"{address}: no SSH host keys")

    monkeypatch.setattr(gather_mod, "scan_keys", down)
    result = runner.invoke(app, ["gather", "-y"])
    assert result.exit_code == 0, result.output
    assert "vps1" in result.output and "no SSH host keys" in result.output
    assert "os: Arch Linux" in (laptop / "hosts" / "hp-13.md").read_text()


def test_dhcp_host_without_address_is_reported(runner, inventory):
    add_host(inventory, "roamer", "---\nbastet: host\ntype: laptop\nip: dhcp\n---\n# roamer\n")
    result = runner.invoke(app, ["gather", "roamer", "-y"])
    assert result.exit_code == 0 and "no address" in result.output


def test_unknown_host_name(runner, inventory):
    result = runner.invoke(app, ["gather", "nope"])
    assert result.exit_code == 1 and "no host named 'nope'" in result.output


def test_accepted_key_replaces_recorded_and_pins_only_one(runner, vps, monkeypatch):
    evil = parse_keyscan(f"h ssh-rsa {base64.b64encode(b'evil').decode()}\n")
    monkeypatch.setattr(gather_mod, "scan_keys", lambda address, recorded=None: KEYS + evil)
    seen = {}
    real_write = gather_mod.hostkeys.write_known_hosts

    def spy(keys, address, port, directory):
        seen["keys"] = list(keys)
        return real_write(keys, address, port, directory)

    monkeypatch.setattr(gather_mod.hostkeys, "write_known_hosts", spy)
    p = vps / "hosts" / "vps1.md"
    p.write_text(p.read_text().replace("ip: 203.0.113.10\n", "ip: 203.0.113.10\nssh_host_key: ssh-ed25519 SHA256:old\n"))
    git(vps, "commit", "-q", "-am", "old key")
    result = runner.invoke(app, ["gather", "vps1", "-y", "--accept-new-hostkey"])
    assert result.exit_code == 0, result.output
    assert seen["keys"] == KEYS
    assert f"ssh_host_key: ssh-ed25519 {KEYS[0].fingerprint}" in p.read_text()


def test_unexpected_error_on_one_host_does_not_stop_others(runner, laptop, monkeypatch):
    add_host(laptop, "vps1", "---\nbastet: host\ntype: vps\nprovider: linode\nip: 203.0.113.10\n---\n# vps1\n")

    def boom(address, recorded=None):
        raise RuntimeError("something odd")

    monkeypatch.setattr(gather_mod, "scan_keys", boom)
    result = runner.invoke(app, ["gather", "-y"])
    assert result.exit_code == 0, result.output
    assert "something odd" in result.output
    assert "os: Arch Linux" in (laptop / "hosts" / "hp-13.md").read_text()


from gather_fixtures import SERVER  # noqa: E402


@pytest.fixture
def server(inventory, monkeypatch):
    monkeypatch.setattr(gather_mod, "scan_keys", lambda address, recorded=None: KEYS)

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
    result = runner.invoke(app, ["gather", "pve1", "-y", "--accept-new-hostkey"])
    assert result.exit_code == 0, result.output
    hw = sorted(p.name for p in (server / "hardware").glob("*.md"))
    assert "Supermicro SYS-5019C-MR S123456X.md" in hw and len(hw) == 5
    host = (server / "hosts" / "pve1.md").read_text()
    assert "pools:\n  - name: tank\n    state: ONLINE\n" in host
    assert "git1" in result.output and "media" in result.output and "aren't in the inventory" in result.output
    files = git(server, "log", "-1", "--name-only", "--format=", "--grep=^gather").split()
    assert "hosts/pve1.md" in files and any(f.startswith("hardware/") for f in files)


def test_root_skipped_note(runner, server, monkeypatch):
    monkeypatch.setattr(gather_mod, "ssh_runner", lambda target: FakeRunner(
        dict(SERVER, privilege="none", dmidecode=(126, ""), smart=(126, ""), ipmi=(126, ""), pve_guests=(126, "")), "x"))
    result = runner.invoke(app, ["gather", "pve1", "-y", "--accept-new-hostkey"])
    assert result.exit_code == 0, result.output
    assert "root-only" in result.output


def test_local_sudo_validated_once_and_hardware_written(runner, laptop, monkeypatch):
    calls = []
    monkeypatch.setattr(gather_mod, "sudo_validate", lambda: calls.append(1) or True)
    result = runner.invoke(app, ["gather", "hp-13"], input="y\n")
    assert result.exit_code == 0, result.output
    assert calls == [1]
    assert (laptop / "hardware" / "HP Spectre x360 Convertible 13-ae0xx 5CD1234XYZ.md").exists()


def test_yes_skips_sudo_prompt(runner, laptop, monkeypatch):
    calls = []
    monkeypatch.setattr(gather_mod, "sudo_validate", lambda: calls.append(1) or True)
    runner.invoke(app, ["gather", "hp-13", "-y"])
    assert calls == []


def test_guests_on_other_nodes_ignored_and_names_quoted(runner, server, monkeypatch):
    guests = json.dumps([
        {"vmid": 104, "name": "git1", "type": "lxc", "node": "pve1", "status": "running"},
        {"vmid": 200, "name": "elsewhere", "type": "qemu", "node": "pve2", "status": "running"},
        {"vmid": 201, "name": "my box", "type": "qemu", "node": "pve1", "status": "running"},
    ])
    monkeypatch.setattr(gather_mod, "ssh_runner", lambda target: FakeRunner(dict(SERVER, pve_guests=guests), "x"))
    result = runner.invoke(app, ["gather", "pve1", "-y", "--accept-new-hostkey"])
    assert "elsewhere" not in result.output
    assert "bastet add host 'my box'" in result.output



def test_gather_stores_warnings_in_summary_and_refresh_keeps_them(runner, laptop):
    runner.invoke(app, ["gather", "-y"])
    p = laptop / "hosts" / "hp-13.md"
    p.write_text(p.read_text().replace("ram: 16 GB", "ram: 32 GB"))
    git(laptop, "commit", "-q", "-am", "upgraded ram")
    runner.invoke(app, ["gather", "-y"])
    summary = (laptop / "_bastet" / "summary" / "hp-13 summary.md").read_text()
    assert "warnings:" in summary and "ram" in summary and "[!warning]" in summary
    runner.invoke(app, ["refresh"])
    assert "ram" in (laptop / "_bastet" / "summary" / "hp-13 summary.md").read_text()
    dash = (laptop / "_bastet" / "bastet dashboard.md").read_text()
    assert "Needs attention" in dash and "[[hp-13]]" in dash


def test_found_guests_added_when_confirmed(runner, server):
    result = runner.invoke(app, ["gather", "pve1", "--accept-new-hostkey"], input="y\ny\n")
    assert result.exit_code == 0, result.output
    assert "Add all 4" in result.output and "bastet add host git1 --type lxc --on pve1" in result.output
    git1 = (server / "hosts" / "git1.md").read_text()
    assert "type: lxc" in git1 and 'runs_on: "[[pve1]]"' in git1 and "ip: 10.0.20.21/24" in git1 and "vmid: 104" in git1
    media = (server / "hosts" / "media.md").read_text()
    assert "type: vm" in media and "ip: dhcp" in media and "address: 10.0.20.25" in media
    ghost = (server / "hosts" / "ghost.md").read_text()
    assert "ip: dhcp" in ghost and "address:" not in ghost
    assert "ghost" in result.output and "set address" in result.output


def test_found_guests_not_added_on_no_or_yes_flag(runner, server):
    result = runner.invoke(app, ["gather", "pve1", "--accept-new-hostkey"], input="n\ny\n")
    assert result.exit_code == 0, result.output
    assert not (server / "hosts" / "git1.md").exists()
    result = runner.invoke(app, ["gather", "pve1", "-y"])
    assert "Add all" not in result.output and not (server / "hosts" / "git1.md").exists()


class InstallingRunner:
    """First collection lacks tools; after an install script runs, the next collection has them."""

    def __init__(self, before, after):
        self.before, self.after, self.installs, self.name = before, after, [], "x"

    def run(self, script, *, timeout=120):
        if "BASTET-INSTALL" in script:
            self.installs.append(script)
            return CommandResult("", "", 0)
        mark = re.search(r"'(@@BASTET[^']*@@)'", script).group(1)
        return CommandResult(stdout_for(self.after if self.installs else self.before, mark), "", 0)


def _rack_host(inventory):
    add_host(inventory, "sanrio", "---\nbastet: host\ntype: proxmox-node\nip: 10.0.10.12\n---\n# sanrio\n")


def test_missing_tools_installed_when_confirmed_and_recorded(runner, inventory, monkeypatch):
    from gather_fixtures import RACK
    _rack_host(inventory)
    fake = InstallingRunner(dict(RACK, pkg_mgr="apt-get"), dict(RACK, pkg_mgr="apt-get", ipmi=SERVER["ipmi"]))
    monkeypatch.setattr(gather_mod, "scan_keys", lambda address, recorded=None: KEYS)
    monkeypatch.setattr(gather_mod, "ssh_runner", lambda target: fake)
    result = runner.invoke(app, ["gather", "sanrio", "--accept-new-hostkey"], input="y\ny\n")
    assert result.exit_code == 0, result.output
    assert "install ipmitool" in result.output and len(fake.installs) == 1
    host = (inventory / "hosts" / "sanrio.md").read_text()
    assert "bastet_tools:\n  - ipmitool\n" in host
    machine = next((inventory / "hardware").glob("ASRockRack*.md")).read_text()
    assert "oob_address: 10.0.10.9" in machine


def test_tools_not_installed_with_yes_by_default_or_when_host_opts_out(runner, inventory, monkeypatch):
    from gather_fixtures import RACK
    _rack_host(inventory)
    fake = InstallingRunner(dict(RACK, pkg_mgr="apt-get"), dict(RACK, pkg_mgr="apt-get"))
    monkeypatch.setattr(gather_mod, "scan_keys", lambda address, recorded=None: KEYS)
    monkeypatch.setattr(gather_mod, "ssh_runner", lambda target: fake)
    runner.invoke(app, ["gather", "sanrio", "-y", "--accept-new-hostkey"])
    assert fake.installs == []
    p = inventory / "hosts" / "sanrio.md"
    p.write_text(p.read_text().replace("type: proxmox-node\n", "type: proxmox-node\ninstall_tools: false\n"))
    git(inventory, "commit", "-q", "-am", "no tools here")
    runner.invoke(app, ["gather", "sanrio"], input="y\n")
    assert fake.installs == []


def test_config_always_installs_unattended(runner, inventory, monkeypatch, tmp_path):
    from gather_fixtures import RACK
    import os
    cfg = Path(os.environ["BASTET_CONFIG"])
    cfg.write_text(cfg.read_text() + "gather:\n  install_tools: always\n")
    _rack_host(inventory)
    fake = InstallingRunner(dict(RACK, pkg_mgr="apt-get"), dict(RACK, pkg_mgr="apt-get", ipmi=SERVER["ipmi"]))
    monkeypatch.setattr(gather_mod, "scan_keys", lambda address, recorded=None: KEYS)
    monkeypatch.setattr(gather_mod, "ssh_runner", lambda target: fake)
    result = runner.invoke(app, ["gather", "sanrio", "-y", "--accept-new-hostkey"])
    assert result.exit_code == 0, result.output
    assert len(fake.installs) == 1


def test_gather_false_skipped_unless_named(runner, laptop):
    p = laptop / "hosts" / "hp-13.md"
    p.write_text(p.read_text().replace("type: laptop\n", "type: laptop\ngather: false\n"))
    git(laptop, "commit", "-q", "-am", "not ready")
    result = runner.invoke(app, ["gather", "-y"])
    assert "hp-13: skipped (gather: false)" in result.output and "os:" not in p.read_text()
    runner.invoke(app, ["gather", "hp-13", "-y"])
    assert "os: Arch Linux" in p.read_text()
