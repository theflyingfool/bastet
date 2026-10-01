from bastet.cli.app import app
from conftest import git


def test_add_role_to_host_writes_file_and_section(runner, inventory):
    result = runner.invoke(app, ["add", "role", "packages", "pve1", "-y"])
    assert result.exit_code == 0, result.output
    text = (inventory / "_roles" / "hosts" / "pve1" / "packages.md").read_text()
    assert text.startswith('---\nbastet: role\nrole: packages\napplies_to: "[[pve1]]"\n---\n# packages for pve1')
    assert "![[roles-here.base]]" in (inventory / "hosts" / "pve1.md").read_text()
    again = runner.invoke(app, ["add", "role", "packages", "pve1", "-y"])
    assert again.exit_code != 0 and "already exists" in again.output


def test_add_role_to_lab_and_unknown(runner, inventory):
    assert runner.invoke(app, ["add", "role", "systemd", "lab", "-y"]).exit_code == 0
    assert 'applies_to: "[[Homelab]]"' in (inventory / "_roles" / "lab" / "systemd.md").read_text()
    bad = runner.invoke(app, ["add", "role", "nope", "pve1", "-y"])
    assert bad.exit_code != 0 and "unknown role" in bad.output


def test_refresh_writes_role_pages_view_and_card(runner, inventory):
    runner.invoke(app, ["add", "role", "packages", "pve1", "-y"])
    runner.invoke(app, ["refresh"])
    assert "# packages role" in (inventory / "_bastet" / "roles" / "packages role.md").read_text()
    assert "applies_to == this" in (inventory / "_bastet" / "roles-here.base").read_text()
    summary = (inventory / "_bastet" / "summary" / "pve1 summary.md").read_text()
    assert "[!stat] Roles" in summary and "[[packages role|packages]]" in summary
