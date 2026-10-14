from bastet.cli.app import app


def test_add_host_writes_the_host_default_notes(runner, inventory):
    result = runner.invoke(app, ["add", "host", "edge1", "--type", "vps", "--provider", "linode", "--ip", "203.0.113.50", "-y"])
    assert result.exit_code == 0, result.output
    text = (inventory / "_roles" / "hosts" / "edge1" / "base.md").read_text()
    assert 'applies_to: "[[edge1]]"' in text
