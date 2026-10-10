import subprocess
from pathlib import Path

from bastet.cli.app import app


def head_author(root: Path) -> str:
    lines = subprocess.run(["git", "-C", str(root), "log", "--format=%an %s"], capture_output=True, text=True).stdout.splitlines()
    return next(line for line in lines if not line.startswith("Bastet refresh:"))


def test_interactive_vps(runner, inventory):
    result = runner.invoke(app, ["add", "host"], input="edge1\nvps\nlinode\n203.0.113.10\ny\n")
    assert result.exit_code == 0, result.output
    text = (inventory / "hosts" / "edge1.md").read_text()
    assert "type: vps\nprovider: linode\nip: 203.0.113.10\n" in text
    assert head_author(inventory).startswith("Bastet add host edge1")


def test_interactive_lxc_picks_parent_network_and_suggestion(runner, inventory):
    result = runner.invoke(app, ["add", "host", "git1", "--type", "lxc"], input="1\nservers\n\ny\n")
    assert result.exit_code == 0, result.output
    text = (inventory / "hosts" / "git1.md").read_text()
    assert 'runs_on: "[[pve1]]"' in text and "network: servers\nip: 10.0.20.10\n" in text


def test_yes_without_type_is_error(runner, inventory):
    result = runner.invoke(app, ["add", "host", "x", "-y"])
    assert result.exit_code == 1 and "--type" in result.output
