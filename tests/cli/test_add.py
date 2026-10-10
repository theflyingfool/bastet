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


def test_add_host_commits_pending_edits_as_user(runner, inventory):
    (inventory / "hosts" / "pve1.md").write_text("---\nbastet: host\ntype: proxmox\nip: 10.0.10.11\nnote: mine\n---\n")
    result = runner.invoke(app, ["add", "host", "edge1", "--type", "vps", "--provider", "linode", "--ip", "203.0.113.10"], input="y\ny\n")
    assert result.exit_code == 0, result.output
    assert "hosts/pve1.md" in result.output
    log = [line for line in authors(inventory) if not line.startswith("Bastet refresh:")]
    assert log[0].startswith("Bastet add host edge1")
    assert log[1].startswith("Tester ")


def test_add_host_local_skips_ip_questions(runner, inventory):
    """add host --local skips IP and address questions."""
    # Test with --yes for simplicity
    result = runner.invoke(app, ["add", "host", "laptop1", "--type", "laptop", "--local", "-y"])
    assert result.exit_code == 0, result.output
    text = (inventory / "hosts" / "laptop1.md").read_text()
    assert "connection: local" in text
    assert "ip:" not in text  # no IP field
    assert "address:" not in text  # no address field


def test_add_host_local_interactive(runner, inventory):
    """add host --local in interactive mode skips IP and address questions."""
    result = runner.invoke(app, ["add", "host", "mymachine", "--type", "laptop"], input="y\ny\n")  # confirm local, confirm write
    assert result.exit_code == 0, result.output
    text = (inventory / "hosts" / "mymachine.md").read_text()
    assert "connection: local" in text
    assert "ip:" not in text
    assert "address:" not in text


def test_unreachable_remote_warns_and_continues(runner, inventory, tmp_path):
    subprocess.run(["git", "-C", str(inventory), "remote", "add", "origin", str(tmp_path / "gone.git")], check=True)
    subprocess.run(["git", "-C", str(inventory), "config", "branch.main.remote", "origin"], check=True)
    subprocess.run(["git", "-C", str(inventory), "config", "branch.main.merge", "refs/heads/main"], check=True)
    result = runner.invoke(app, ["add", "host", "edge1", "--type", "vps", "--provider", "linode", "--ip", "203.0.113.10", "-y"])
    assert result.exit_code == 0, result.output
    assert "warning" in result.output and (inventory / "hosts" / "edge1.md").exists()
    assert any(line.startswith("Bastet add host edge1") for line in authors(inventory))


def test_pending_personal_notes_left_alone(runner, inventory):
    (inventory / "journal.md").write_text("# personal\n")
    (inventory / "hosts" / "pve1.md").write_text("---\nbastet: host\ntype: proxmox\nip: 10.0.10.11\nnote: mine\n---\n")
    result = runner.invoke(app, ["add", "host", "edge1", "--type", "vps", "--provider", "linode", "--ip", "203.0.113.10", "-y"])
    assert result.exit_code == 0, result.output
    status = subprocess.run(["git", "-C", str(inventory), "status", "--porcelain"], capture_output=True, text=True).stdout
    assert "journal.md" in status and "pve1.md" not in status


def test_hardware_categories_cover_what_bastet_records():
    from bastet.core.hardware import HARDWARE_CATEGORIES
    assert {"transceiver", "cpu", "memory", "usb"} <= set(HARDWARE_CATEGORIES)
