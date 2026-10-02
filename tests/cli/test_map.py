from bastet.cli.app import app


def test_map_prints_without_writing(runner, inventory):
    (inventory / "hosts" / "nas.md").write_text(
        '---\nbastet: host\ntype: server\nlinks:\n  - {port: eno1, to: "[[pve1]]", to_port: "3"}\n---\n# nas\n')
    result = runner.invoke(app, ["map", "cabling"])
    assert result.exit_code == 0 and "```mermaid" in result.output and "eno1 ↔ 3" in result.output
    assert not (inventory / "_bastet" / "maps").exists()


def test_map_unknown_view(runner, inventory):
    result = runner.invoke(app, ["map", "nope"])
    assert result.exit_code != 0 and "cabling, networks" in result.output
