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
    assert "pve1" in result.output and "proxmox" in result.output and "10.0.10.11" in result.output


def test_show_problems_exit_1(runner, inventory):
    (inventory / "hosts" / "bad.md").write_text("---\nbastet: host\ntype: vpz\n---\n")
    result = runner.invoke(app, ["show"])
    assert result.exit_code == 1
    assert "hosts/bad.md" in result.output and "unknown host type 'vpz'" in result.output


def test_show_stale_fact_keys_warning(runner, inventory):
    (inventory / "hosts" / "pve1.md").write_text(
        "---\nbastet: host\ntype: proxmox\nip: 10.0.10.11\nos: Debian 12\n---\n# pve1\n"
    )
    result = runner.invoke(app, ["show"])
    assert result.exit_code == 0, result.output
    assert "os are gathered facts" in result.output
    assert "_bastet/facts/pve1 facts.md" in result.output


def test_show_lists_os_from_facts(runner, inventory):
    """A stale `os:` left on the host note must not beat the facts note's fresher value."""
    from bastet.core.factsnote import facts_path, render_facts

    (inventory / "hosts" / "pve1.md").write_text(
        "---\nbastet: host\ntype: proxmox\nip: 10.0.10.11\nos: Debian 12\n---\n# pve1\n"
    )
    facts_path(inventory, "pve1").parent.mkdir(parents=True, exist_ok=True)
    facts_path(inventory, "pve1").write_text(render_facts("pve1", {"os": "Debian 13"}, "2026-10-06T10:00:00Z"))
    result = runner.invoke(app, ["show"])
    assert result.exit_code == 0, result.output
    assert "Debian 13" in result.output and "Debian 12" not in result.output


def test_show_one_includes_gathered_facts(runner, inventory):
    from bastet.core.factsnote import facts_path, render_facts

    facts_path(inventory, "pve1").parent.mkdir(parents=True, exist_ok=True)
    facts_path(inventory, "pve1").write_text(render_facts("pve1", {"os": "Debian GNU/Linux 13 (trixie)"}, "2026-10-06T10:00:00Z"))
    result = runner.invoke(app, ["show", "pve1"])
    assert result.exit_code == 0, result.output
    assert "Gathered facts (_bastet/facts/pve1 facts.md):" in result.output
    header = result.output.index("Gathered facts")
    assert "os: Debian GNU/Linux 13 (trixie)" in result.output[header:]


def test_show_one_not_gathered_yet(runner, inventory):
    result = runner.invoke(app, ["show", "pve1"])
    assert result.exit_code == 0, result.output
    assert "Gathered facts (_bastet/facts/pve1 facts.md): not gathered yet" in result.output


def test_show_one_hints_stale_fact_keys(runner, inventory):
    from bastet.core.factsnote import facts_path, render_facts

    (inventory / "hosts" / "pve1.md").write_text(
        "---\nbastet: host\ntype: proxmox\nip: 10.0.10.11\nos: Debian 12\n---\n# pve1\n"
    )
    facts_path(inventory, "pve1").parent.mkdir(parents=True, exist_ok=True)
    facts_path(inventory, "pve1").write_text(render_facts("pve1", {"os": "Debian 13"}, "2026-10-06T10:00:00Z"))
    result = runner.invoke(app, ["show", "pve1"])
    assert result.exit_code == 0, result.output
    assert "os are gathered facts" in result.output and "_bastet/facts/pve1 facts.md" in result.output


def test_show_one_with_links(runner, inventory):
    (inventory / "hardware").mkdir()
    (inventory / "hardware" / "d1.md").write_text(
        '---\nbastet: hardware\ncategory: drive\ninstalled_in: "[[pve1]]"\n---\n'
    )
    result = runner.invoke(app, ["show", "PVE1"])
    assert result.exit_code == 0, result.output
    assert "type: proxmox" in result.output
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


def test_show_does_not_list_run_notes_as_links(runner, inventory):
    folder = inventory / "_bastet" / "runs"
    folder.mkdir(parents=True)
    (folder / "2026-10-10 1218 check 22d326.md").write_text(
        '---\nbastet: run\ngenerated: true\nrun: 20261010-121800-22d326\nhosts:\n  - "[[pve1]]"\n---\n# check\n'
    )
    result = runner.invoke(app, ["show", "pve1"])
    assert result.exit_code == 0, result.output
    assert "22d326" not in result.output and "check" not in result.output.split("Linked from")[-1]
