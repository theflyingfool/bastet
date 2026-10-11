import subprocess
from pathlib import Path

from bastet.cli.app import app
from conftest import git


def _count(root: Path) -> int:
    return int(git(root, "rev-list", "--count", "HEAD").strip())


def test_doctor_lists_stale_keys_and_offers_no_fix_until_facts_exist(runner, inventory):
    pve1 = inventory / "hosts" / "pve1.md"
    pve1.write_text(pve1.read_text().replace("---\n# pve1", "os: Debian 12\n---\n# pve1\n\n![[pve1 facts]]\n"))
    git(inventory, "add", ".")
    git(inventory, "commit", "-q", "-m", "stale key")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "os are gathered facts" in result.output


def test_doctor_fix_removes_stale_key_already_in_facts_and_commits_once(runner, inventory):
    pve1 = inventory / "hosts" / "pve1.md"
    pve1.write_text(pve1.read_text().replace("---\n# pve1", "os: Debian 12\n---\n# pve1\n\n![[pve1 facts]]\n"))
    facts_dir = inventory / "_bastet" / "facts"
    facts_dir.mkdir(parents=True)
    (facts_dir / "pve1 facts.md").write_text('---\nbastet: facts\nhost: "[[pve1]]"\nos: Debian 12\n---\n')
    git(inventory, "add", ".")
    git(inventory, "commit", "-q", "-m", "stale key with facts")
    before = _count(inventory)
    result = runner.invoke(app, ["doctor", "--fix", "-y"])
    assert result.exit_code == 0, result.output
    assert "hosts/pve1.md: removed os (now in pve1 facts)" in result.output
    assert "os:" not in pve1.read_text()
    assert _count(inventory) - before == 1


def test_doctor_fix_declined_makes_no_commit(runner, inventory):
    pve1 = inventory / "hosts" / "pve1.md"
    pve1.write_text(pve1.read_text().replace("---\n# pve1", "os: Debian 12\n---\n# pve1\n\n![[pve1 facts]]\n"))
    facts_dir = inventory / "_bastet" / "facts"
    facts_dir.mkdir(parents=True)
    (facts_dir / "pve1 facts.md").write_text('---\nbastet: facts\nhost: "[[pve1]]"\nos: Debian 12\n---\n')
    git(inventory, "add", ".")
    git(inventory, "commit", "-q", "-m", "stale key with facts")
    before = _count(inventory)
    result = runner.invoke(app, ["doctor", "--fix"], input="n\n")
    assert result.exit_code == 0, result.output
    assert "removed os" not in result.output
    assert "os: Debian 12" in pve1.read_text()
    assert _count(inventory) == before


def test_doctor_fix_replaces_retired_embed(runner, inventory):
    pve1 = inventory / "hosts" / "pve1.md"
    pve1.write_text(pve1.read_text().replace("# pve1\n", "# pve1\n\n![[pve1 summary]]\n"))
    git(inventory, "add", ".")
    git(inventory, "commit", "-q", "-m", "legacy embed")
    result = runner.invoke(app, ["doctor", "--fix", "-y"])
    assert result.exit_code == 0, result.output
    assert "replaced the retired embed with ![[pve1 facts]]" in result.output
    text = pve1.read_text()
    assert "![[pve1 facts]]" in text and "pve1 summary" not in text


def test_doctor_clean_inventory_reports_nothing(runner, inventory):
    pve1 = inventory / "hosts" / "pve1.md"
    pve1.write_text(pve1.read_text().replace("10.0.10.11", "10.0.20.11"))
    git(inventory, "add", ".")
    git(inventory, "commit", "-q", "-m", "fix address")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "No problems found." in result.output


def test_doctor_role_dir_parses_ok(runner, tmp_path):
    role_dir = tmp_path / "roles" / "myrole"
    role_dir.mkdir(parents=True)
    (role_dir / "role.yml").write_text("description: a role\noptions: {}\n")
    result = runner.invoke(app, ["doctor", str(role_dir)])
    assert result.exit_code == 0, result.output
    assert "parses as a role definition" in result.output


def test_doctor_role_dir_missing_role_yml_errors(runner, tmp_path):
    role_dir = tmp_path / "roles" / "myrole"
    role_dir.mkdir(parents=True)
    result = runner.invoke(app, ["doctor", str(role_dir)])
    assert result.exit_code != 0
    assert "no role definition" in result.output


def test_doctor_role_dir_invalid_yaml_errors(runner, tmp_path):
    role_dir = tmp_path / "roles" / "myrole"
    role_dir.mkdir(parents=True)
    (role_dir / "role.yml").write_text("options:\n  bad:\n    type: nonsense\n")
    result = runner.invoke(app, ["doctor", str(role_dir)])
    assert result.exit_code != 0


def test_doctor_fix_rejected_with_a_role_dir(runner, tmp_path):
    role_dir = tmp_path / "roles" / "myrole"
    role_dir.mkdir(parents=True)
    (role_dir / "role.yml").write_text("description: a role\noptions: {}\n")
    result = runner.invoke(app, ["doctor", str(role_dir), "--fix"])
    assert result.exit_code != 0
    assert "--fix doesn't apply" in result.output


def test_doctor_lints_the_bundled_markdown_and_yaml_roles(runner):
    import bastet

    roles = Path(bastet.__file__).parent / "data" / "roles"
    for name in ("pacman", "ssh"):
        result = runner.invoke(app, ["doctor", str(roles / name)])
        assert result.exit_code == 0, result.output
        assert "parses as a role definition" in result.output


def test_doctor_empty_role_folder_names_both_formats(runner, tmp_path):
    role_dir = tmp_path / "roles" / "empty"
    role_dir.mkdir(parents=True)
    result = runner.invoke(app, ["doctor", str(role_dir)])
    assert result.exit_code != 0
    assert 'no role definition (role.yml or "empty role.md")' in result.output
