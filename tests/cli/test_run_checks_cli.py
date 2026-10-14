import yaml
from conftest import git

import bastet.cli.run as run_mod
from bastet.cli.app import app
from bastet.roles.contract import load_roles


def check(level="warning", message="look at this"):
    return {"when": "true", "level": level, "message": message}


def test_check_and_run_print_a_roles_notes_once_per_host(inventory, runner, tmp_path, monkeypatch):
    folder = tmp_path / "roles" / "noted"
    folder.mkdir(parents=True)
    data = {"bastet": "role-definition", "name": "noted", "version": "1.0.0", "api": 0, "description": "A noted role",
            "checks": [check(message="mind the gap"), check("info", "fyi"), check(message="mind the gap")]}
    (folder / "noted role.md").write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\nx\n", encoding="utf-8")
    merged = {**load_roles(), **load_roles(tmp_path / "roles")}
    monkeypatch.setattr(run_mod, "load_roles", lambda: merged)
    (inventory / "hosts" / "box.md").write_text("---\nbastet: host\ntype: computer\nconnection: local\nhostname: box\n---\n# box\n")
    roles = inventory / "_roles" / "hosts" / "box"
    roles.mkdir(parents=True)
    (roles / "noted.md").write_text('---\nbastet: role\nrole: noted\napplies_to: "[[box]]"\n---\n')
    git(inventory, "add", ".")
    git(inventory, "commit", "-q", "-m", "box")
    for args in (["run", "-c", "box"], ["run", "box"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output
        assert result.output.count("box: noted: mind the gap") == 1
        assert result.output.count("box: noted: fyi") == 1
