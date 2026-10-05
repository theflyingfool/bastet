import subprocess

from bastet.cli.app import app


def log(root) -> list[str]:
    return subprocess.run(["git", "-C", str(root), "log", "--format=%H"], capture_output=True, text=True).stdout.splitlines()


def test_show_writes_and_commits_nothing(runner, inventory):
    before = log(inventory)
    result = runner.invoke(app, ["show"])
    assert result.exit_code == 0, result.output
    assert log(inventory) == before
    assert not (inventory / "_bastet").exists()


def test_show_lists_hosts(runner, inventory):
    result = runner.invoke(app, ["show"])
    assert result.exit_code == 0, result.output
    assert "pve1" in result.output and "proxmox-node" in result.output and "10.0.10.11" in result.output


def test_show_problems_exit_1(runner, inventory):
    (inventory / "hosts" / "bad.md").write_text("---\nbastet: host\ntype: vpz\n---\n")
    result = runner.invoke(app, ["show"])
    assert result.exit_code == 1
    assert "hosts/bad.md" in result.output and "unknown host type 'vpz'" in result.output


def test_show_one_with_links(runner, inventory):
    (inventory / "hardware").mkdir()
    (inventory / "hardware" / "d1.md").write_text(
        '---\nbastet: hardware\ncategory: drive\ninstalled_in: "[[pve1]]"\n---\n'
    )
    result = runner.invoke(app, ["show", "PVE1"])
    assert result.exit_code == 0, result.output
    assert "type: proxmox-node" in result.output
    assert "d1 (installed_in)" in result.output


def test_show_unknown_name(runner, inventory):
    result = runner.invoke(app, ["show", "nope"])
    assert result.exit_code == 1 and "no object named 'nope'" in result.output


def test_missing_config_is_clean_error(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("BASTET_CONFIG", str(tmp_path / "none.yml"))
    result = runner.invoke(app, ["show"])
    assert result.exit_code == 1
    assert "config file not found" in result.output
    assert "Traceback" not in result.output
