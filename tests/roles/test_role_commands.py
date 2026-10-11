from pathlib import Path

import pytest
import yaml

from bastet.core.errors import BastetError
from bastet.engine.command import Command
from bastet.roles.builtin import HostInfo
from bastet.roles.contract import parse_role
from bastet.roles.declarative import build


def cmd_role(tmp_path, commands, options=None):
    folder = tmp_path / "demo"
    folder.mkdir(exist_ok=True)
    data = {"bastet": "role-definition", "name": "demo", "version": "1.0.0", "api": 0, "description": "A demo role",
            "options": options or {"on": {"type": "bool", "default": False}}, "commands": commands}
    path = folder / "demo role.md"
    path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\nNotes.\n", encoding="utf-8")
    return parse_role(path)


def built(role, values):
    host = HostInfo(name="laptop1", type="laptop", data={"os": "Arch Linux"}, root=Path("/nonexistent"), lab={})
    [batch] = build(role, values, host)
    return batch.resources


ENTRY = {"name": "say hi", "run": "echo hi", "unless": "test -e /tmp/x"}


def test_a_command_entry_becomes_a_command_resource(tmp_path):
    [command] = built(cmd_role(tmp_path, [{**ENTRY, "before": "packages"}]), {})
    assert isinstance(command, Command)
    assert (command.name, command.run, command.unless, command.run_before) == ("say hi", "echo hi", "test -e /tmp/x", "packages")


def test_when_switches_the_command_on_the_option(tmp_path):
    role = cmd_role(tmp_path, [{**ENTRY, "when": "on"}])
    assert built(role, {"on": True}) and not built(role, {"on": False}) and not built(role, {})


@pytest.mark.parametrize("entry, message", [
    ({"run": "x", "unless": "y"}, "name"),
    ({"name": "n", "unless": "y"}, "run"),
    ({"name": "n", "run": "x"}, "unless"),
    ({**ENTRY, "when": "nope"}, "when names no option: nope"),
    ({**ENTRY, "before": "packages", "after": "files"}, "before or after, not both"),
    ({**ENTRY, "zzz": 1}, "zzz"),
])
def test_command_entry_errors(tmp_path, entry, message):
    with pytest.raises(BastetError, match=message):
        cmd_role(tmp_path, [entry])
