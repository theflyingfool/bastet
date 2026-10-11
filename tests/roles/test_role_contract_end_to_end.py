from pathlib import Path

import yaml

from bastet.cli.doctor import _check_role_dir
from bastet.engine.slots import apply_order
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import parse_role
from bastet.roles.resolve import Applied


def demo(tmp_path, **extra):
    folder = tmp_path / "web"
    folder.mkdir()
    data = {"bastet": "role-definition", "name": "web", "version": "1.0.0", "api": 0, "description": "A demo web role",
            "options": {"domain": {"type": "string", "required": True},
                        "workers": {"type": "int", "key": "Workers", "section": "main"}},
            "packages": ["example-app"],
            "users": [{"kind": "user", "name": "web", "system": True}],
            "files": [{"path": "/etc/example-app/app.conf", "content": "{{ domain }} {\n}\n", "reload": ["example-app.service"]}],
            "systemd": [{"kind": "unit", "name": "example-app.service", "enabled": True, "state": "up"}], **extra}
    path = folder / "web role.md"
    path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\nNotes.\n", encoding="utf-8")
    return path, parse_role(path)


def run_order(role, values):
    host = HostInfo(name="vps1", type="vps", data={"os": "Arch Linux"}, root=Path("/nonexistent"), lab={})
    batches = batches_for([Applied(role=role, values=values)], host)
    planned = [(b.name, [type("Item", (), {"resource": r}) for r in b.resources]) for b in batches]
    return [type(i.resource).__name__ for i in apply_order(planned)]


def test_a_role_of_block_entries_runs_in_block_order(tmp_path):
    path, role = demo(tmp_path)
    assert run_order(role, {"domain": "example.net"}) == ["Package", "User", "File", "Unit"]
    _check_role_dir(path.parent)  # the lint `bastet doctor <folder>` runs; raises on a bad role


def test_an_ini_edit_and_a_command_in_the_same_role_still_build(tmp_path):
    files = [{"path": "/etc/example-app/app.conf", "content": "x\n"}, {"path": "/etc/example-app/more.conf", "edit": "ini"}]
    commands = [{"name": "init db", "run": "example-app migrate", "unless": "test -e /var/lib/example-app/done"}]
    path, role = demo(tmp_path, files=files, commands=commands)
    order = run_order(role, {"domain": "example.net", "workers": 4})
    assert order[:2] == ["Package", "User"]
    assert "Settings" in order and "File" in order and "Unit" in order and len(order) == 6
    _check_role_dir(path.parent)
