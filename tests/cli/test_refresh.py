import subprocess
from pathlib import Path

from bastet.cli.app import app


def log(root: Path) -> list[str]:
    return subprocess.run(["git", "-C", str(root), "log", "--format=%an %s"], capture_output=True, text=True).stdout.splitlines()


def test_refresh_writes_summaries_and_dashboard_once(runner, inventory):
    result = runner.invoke(app, ["refresh"])
    assert result.exit_code == 0, result.output
    assert (inventory / "_bastet" / "summary" / "pve1 summary.md").exists()
    assert (inventory / "_bastet" / "bastet dashboard.md").exists()
    assert log(inventory)[0].startswith("Bastet refresh:")
    again = runner.invoke(app, ["refresh"])
    assert again.exit_code == 0 and "up to date" in again.output
    assert len(log(inventory)) == len(log(inventory))
    assert log(inventory)[0].startswith("Bastet refresh:") and log(inventory)[1] == "Tester seed"


def test_show_refreshes_generated_notes(runner, inventory):
    result = runner.invoke(app, ["show"])
    assert result.exit_code == 0, result.output
    assert (inventory / "_bastet" / "summary" / "pve1 summary.md").exists()


def test_add_host_embeds_dashboard_and_refreshes(runner, inventory):
    result = runner.invoke(app, ["add", "host", "edge1", "--type", "vps", "--provider", "linode", "--ip", "203.0.113.10", "-y"])
    assert result.exit_code == 0, result.output
    assert "![[bastet dashboard]]" in (inventory / "Homelab.md").read_text()
    assert "![[edge1 summary]]" in (inventory / "hosts" / "edge1.md").read_text()
    assert (inventory / "_bastet" / "summary" / "edge1 summary.md").exists()
    assert any(line == "Bastet add host edge1" for line in log(inventory))
