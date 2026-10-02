from bastet.cli.app import app
from conftest import git


def test_map_writes_both_maps_without_printing_them(runner, inventory):
    (inventory / "hosts" / "nas.md").write_text(
        '---\nbastet: host\ntype: server\nip: 10.0.20.30\nlinks:\n  - {port: eno1, to: "[[pve1]]", to_port: "3"}\n---\n# nas\n')
    git(inventory, "add", ".")
    git(inventory, "commit", "-q", "-m", "nas")
    result = runner.invoke(app, ["map"])
    assert result.exit_code == 0, result.output
    assert "```mermaid" not in result.output
    assert "_bastet/maps/Cabling.md" in result.output and "_bastet/maps/Networks.md" in result.output
    assert "eno1 ↔ 3" in (inventory / "_bastet" / "maps" / "Cabling.md").read_text()
    assert "servers · 10.0.20.0/24" in (inventory / "_bastet" / "maps" / "Networks.md").read_text()


def test_refresh_writes_maps_too(runner, inventory):
    (inventory / "hosts" / "nas.md").write_text(
        '---\nbastet: host\ntype: server\nip: 10.0.20.30\nlinks:\n  - {port: eno1, to: "[[pve1]]", to_port: "3"}\n---\n# nas\n')
    git(inventory, "add", ".")
    git(inventory, "commit", "-q", "-m", "nas")
    result = runner.invoke(app, ["refresh"])
    assert result.exit_code == 0 and "```mermaid" not in result.output
    assert (inventory / "_bastet" / "maps" / "Cabling.md").exists()
    assert (inventory / "_bastet" / "maps" / "Networks.md").exists()
