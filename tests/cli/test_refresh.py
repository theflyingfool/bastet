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
    assert log(inventory)[0].startswith("Bastet refresh:") and log(inventory)[1] == "Tester seed"


def test_show_does_not_refresh_generated_notes(runner, inventory):
    result = runner.invoke(app, ["show"])
    assert result.exit_code == 0, result.output
    assert not (inventory / "_bastet" / "summary" / "pve1 summary.md").exists()


def test_add_host_embeds_dashboard_and_refreshes(runner, inventory):
    result = runner.invoke(app, ["add", "host", "edge1", "--type", "vps", "--provider", "linode", "--ip", "203.0.113.10", "-y"])
    assert result.exit_code == 0, result.output
    assert "![[bastet dashboard]]" in (inventory / "Homelab.md").read_text()
    assert "![[edge1 summary]]" in (inventory / "hosts" / "edge1.md").read_text()
    assert (inventory / "_bastet" / "summary" / "edge1 summary.md").exists()
    assert any(line == "Bastet add host edge1" for line in log(inventory))


def test_refresh_skipped_not_failed_when_pull_fails(runner, inventory, tmp_path):
    subprocess.run(["git", "-C", str(inventory), "remote", "add", "origin", str(tmp_path / "gone.git")], check=True)
    subprocess.run(["git", "-C", str(inventory), "config", "branch.main.remote", "origin"], check=True)
    subprocess.run(["git", "-C", str(inventory), "config", "branch.main.merge", "refs/heads/main"], check=True)
    before = log(inventory)
    result = runner.invoke(app, ["refresh"])
    assert result.exit_code == 0, result.output
    assert "refresh skipped" in result.output and log(inventory) == before


def test_refresh_skipped_during_merge(runner, inventory):
    (inventory / ".git" / "MERGE_HEAD").write_text("0" * 40 + "\n")
    result = runner.invoke(app, ["refresh"])
    assert result.exit_code == 0 and "refresh skipped" in result.output


def test_bad_user_value_does_not_crash_show(runner, inventory):
    (inventory / "hardware").mkdir()
    (inventory / "hardware" / "m.md").write_text('---\nbastet: hardware\ncategory: server\noob: ipmi\noob_address: 10.0.10.9\ninstalled_in: "[[pve1]]"\n---\n')
    result = runner.invoke(app, ["show"])
    assert result.exit_code == 0, result.output
