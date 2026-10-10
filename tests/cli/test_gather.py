import base64
import json
import re
import subprocess
from pathlib import Path

import pytest

import bastet.cli.gather as gather_mod
from bastet.cli.app import app
from bastet.core.errors import Unreachable
from bastet.core.factsnote import facts_path
from bastet.core.hostkeys import parse_keyscan
from bastet.core.remote import CommandResult
from gather_fixtures import LAPTOP, stdout_for

KEYS = parse_keyscan(f"h ssh-ed25519 {base64.b64encode(b'fake-host-key').decode()}\n")


class FakeRunner:
    def __init__(self, outputs, name="fake"):
        self.outputs = outputs
        self.name = name

    def run(self, script, *, timeout=120):
        match = re.search(r"'(@@BASTET[^']*@@)'", script)
        if match is None:
            return CommandResult("", "", 0)
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


def test_gather_local_laptop_writes_facts(runner, laptop, tmp_path):
    result = runner.invoke(app, ["run", "-g", "hp-13", "-y"])
    assert result.exit_code == 0, result.output
    host = (laptop / "hosts" / "hp-13.md").read_text()
    assert host == f"---\nbastet: host\ntype: laptop\nip: dhcp\nconnection: local\nssh_host_key: {LAPTOP_HOST_KEY}\n---\n# hp-13\n"
    note = facts(laptop, "hp-13")
    assert "os: Arch Linux" in note and "ram: 16 GB" in note and "cpu_cores: 4" in note
    assert (laptop / "hardware" / "HP Spectre x360 Convertible 13-ae0xx 5CD1234XYZ.md").exists()
    assert any(line.startswith("Bastet gather: hp-13 (+") for line in git(laptop, "log", "--format=%an %s").splitlines())


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


def test_unknown_host_name(runner, inventory):
    result = runner.invoke(app, ["run", "-g", "nope"])
    assert result.exit_code == 1 and "no host named 'nope'" in result.output


def test_gather_then_apply_in_one_run_is_one_commit(runner, laptop):
    before = int(git(laptop, "rev-list", "--count", "HEAD").strip())
    result = runner.invoke(app, ["run", "-g", "-a", "hp-13", "-y"])
    assert result.exit_code == 0, result.output
    after = int(git(laptop, "rev-list", "--count", "HEAD").strip())
    assert after - before == 1
    subject = git(laptop, "log", "-1", "--format=%s").strip()
    assert subject.startswith("gather: hp-13") and "apply: hp-13" in subject
