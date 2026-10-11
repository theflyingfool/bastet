import subprocess
from pathlib import Path

from bastet.cli.app import app


def authors(root: Path) -> list[str]:
    out = subprocess.run(["git", "-C", str(root), "log", "--format=%an %s"], capture_output=True, text=True, check=True)
    return out.stdout.strip().splitlines()


def test_add_host_yes_writes_and_commits(runner, inventory):
    result = runner.invoke(app, ["add", "host", "edge1", "--type", "vps", "--provider", "linode", "--ip", "203.0.113.10", "--yes"])
    assert result.exit_code == 0, result.output
    assert "+++ b/hosts/edge1.md" in result.output
    assert (inventory / "hosts" / "edge1.md").read_text().startswith("---\nbastet: host\n")
    assert any(line.startswith("Bastet add host edge1") for line in authors(inventory))


def test_add_host_declined_writes_nothing(runner, inventory):
    result = runner.invoke(app, ["add", "host", "edge1", "--type", "vps", "--provider", "linode", "--ip", "203.0.113.10"], input="n\n")
    assert result.exit_code == 0, result.output
    assert "Nothing written" in result.output
    assert not (inventory / "hosts" / "edge1.md").exists()


def test_add_host_suggests_address(runner, inventory):
    result = runner.invoke(app, ["add", "host", "git1", "--type", "lxc", "--on", "pve1", "--network", "servers", "-y"])
    assert result.exit_code == 0, result.output
    assert "10.0.20.10" in result.output
    assert "ip: 10.0.20.10" in (inventory / "hosts" / "git1.md").read_text()


def test_add_host_error_is_clean(runner, inventory):
    result = runner.invoke(app, ["add", "host", "pve1", "--type", "server", "--ip", "10.0.10.99", "-y"])
    assert result.exit_code == 1 and "already exists" in result.output and "Traceback" not in result.output


def test_add_hardware_command_is_gone(runner, inventory):
    result = runner.invoke(app, ["add", "hardware"])
    assert result.exit_code != 0 and "No such command" in result.output


def test_add_local_host_asks_no_address_questions(runner, inventory, monkeypatch):
    import bastet.cli.add as add_mod
    monkeypatch.setattr(add_mod, "_set_up_this_machine", lambda **k: None)
    result = runner.invoke(app, ["add", "host", "laptop1", "--type", "computer", "--local"], input="\ny\n")
    assert result.exit_code == 0, result.output
    assert "IP" not in result.output.split("laptop1")[0] and "Name to reach it by" not in result.output
    assert "connection: local" in (inventory / "hosts" / "laptop1.md").read_text()


def test_add_host_menu_lists_the_types_in_their_order(runner, inventory):
    result = runner.invoke(app, ["add", "host", "thing1"], input="9\n")  # picks `other`; the prompts that follow run out of input, which is fine here
    names = [line.split()[1] for line in result.output.splitlines() if line.startswith("  ") and line[2:3].isdigit()][:9]
    assert names == ["computer", "server", "proxmox", "unifi", "vm", "lxc", "vps", "undefined", "other"]
    assert "  1. computer  - A user's workstation" in result.output
