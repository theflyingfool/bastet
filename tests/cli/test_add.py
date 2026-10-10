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
