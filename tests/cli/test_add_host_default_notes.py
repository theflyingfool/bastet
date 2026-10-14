from bastet.cli.app import app
from bastet.roles import notes


def test_add_host_writes_the_host_default_notes(runner, inventory, monkeypatch):
    monkeypatch.setattr(notes, "HOST_ROLES", ("packages",))
    result = runner.invoke(app, ["add", "host", "edge1", "--type", "vps", "--provider", "linode", "--ip", "203.0.113.50", "-y"])
    assert result.exit_code == 0, result.output
    text = (inventory / "_roles" / "hosts" / "edge1" / "packages.md").read_text()
    assert 'applies_to: "[[edge1]]"' in text
