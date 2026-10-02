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


def test_new_role_file_explains_itself(runner, inventory):
    runner.invoke(app, ["add", "role", "packages", "pve1", "-y"])
    body = (inventory / "_roles" / "hosts" / "pve1" / "packages.md").read_text().split("---\n", 2)[2]
    assert "properties" in body and "![[packages role#Examples]]" in body and "![[packages role#Options]]" in body


def test_add_role_offers_roles_and_targets(runner, inventory):
    result = runner.invoke(app, ["add", "role"], input="base\nlab\ny\n")
    assert result.exit_code == 0, result.output
    assert "Roles:" in result.output and "Add to:" in result.output and "every host" in result.output
    assert (inventory / "_roles" / "lab" / "base.md").exists()


def test_add_several_roles_at_once(runner, inventory):
    result = runner.invoke(app, ["add", "role", "base", "harden", "--to", "pve1", "-y"])
    assert result.exit_code == 0, result.output
    folder = inventory / "_roles" / "hosts" / "pve1"
    assert (folder / "base.md").exists() and (folder / "harden.md").exists()


def test_numbers_pick_roles(runner, inventory):
    from bastet.roles.contract import load_roles
    names = sorted(load_roles())
    pick = f"{names.index('base') + 1},{names.index('pacman') + 1}"
    result = runner.invoke(app, ["add", "role", "--to", "lab"], input=f"{pick}\ny\n")
    assert result.exit_code == 0, result.output
    assert (inventory / "_roles" / "lab" / "base.md").exists() and (inventory / "_roles" / "lab" / "pacman.md").exists()


def test_old_two_word_form_still_works(runner, inventory):
    assert runner.invoke(app, ["add", "role", "packages", "pve1", "-y"]).exit_code == 0
    assert (inventory / "_roles" / "hosts" / "pve1" / "packages.md").exists()


def test_yes_needs_roles_and_target(runner, inventory):
    result = runner.invoke(app, ["add", "role", "-y"])
    assert result.exit_code != 0 and "--to" in result.output


def test_existing_role_skipped_others_written(runner, inventory):
    runner.invoke(app, ["add", "role", "base", "--to", "pve1", "-y"])
    result = runner.invoke(app, ["add", "role", "base", "harden", "--to", "pve1", "-y"])
    assert result.exit_code == 0 and "already" in result.output
    assert (inventory / "_roles" / "hosts" / "pve1" / "harden.md").exists()
