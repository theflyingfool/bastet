import pytest
import yaml

from bastet.core.errors import BastetError
from bastet.roles.contract import load_roles

BASE = {"bastet": "role-definition", "version": "1.0.0", "api": 0}
TARGET_OPTIONS = {"reboot": {"type": "string", "description": "when to reboot", "choices": ["never", "ask", "auto"]}}


def write(directory, name, options):
    folder = directory / name
    folder.mkdir(parents=True, exist_ok=True)
    data = {**BASE, "name": name, "description": f"The {name} role", "options": options}
    (folder / f"{name} role.md").write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\nNotes.\n")


def load(tmp_path, option):
    write(tmp_path, "target", TARGET_OPTIONS)
    write(tmp_path, "manager", {"reboot": option})
    return load_roles(tmp_path)


@pytest.mark.parametrize("target", ["target.rebot", "nosuchrole.reboot", "target", "target.reboot.x", "Target.reboot"])
def test_a_bad_supersedes_fails_the_load_naming_file_and_key(tmp_path, target):
    with pytest.raises(BastetError) as e:
        load(tmp_path, {"supersedes": target})
    assert "manager role.md" in str(e.value) and "supersedes" in str(e.value)


def test_supersedes_copies_type_description_and_choices_from_the_target(tmp_path):
    opt = load(tmp_path, {"supersedes": "target.reboot"})["manager"].options["reboot"]
    assert (opt.type, opt.description, opt.choices) == ("string", "when to reboot", ("never", "ask", "auto"))
    assert opt.supersedes == "target.reboot"


def test_a_description_of_its_own_is_kept(tmp_path):
    opt = load(tmp_path, {"supersedes": "target.reboot", "description": "mine"})["manager"].options["reboot"]
    assert opt.description == "mine" and opt.type == "string"


def test_a_matching_type_is_accepted_and_a_mismatch_is_refused(tmp_path):
    assert load(tmp_path, {"type": "string", "supersedes": "target.reboot"})["manager"].options["reboot"].type == "string"
    with pytest.raises(BastetError, match="not int"):
        load(tmp_path, {"type": "int", "supersedes": "target.reboot"})


def test_supersedes_on_a_nested_field_is_refused(tmp_path):
    write(tmp_path, "target", TARGET_OPTIONS)
    write(tmp_path, "manager", {"o": {"type": "object", "fields": {"x": {"supersedes": "target.reboot"}}}})
    with pytest.raises(BastetError, match="supersedes only applies to an option of the role itself"):
        load_roles(tmp_path)
