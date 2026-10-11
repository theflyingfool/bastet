from pathlib import Path

import pytest
import yaml

from bastet.core.errors import BastetError
from bastet.engine.command import Command
from bastet.engine.files import Settings
from bastet.roles.builtin import HostInfo
from bastet.roles.contract import parse_role
from bastet.roles.declarative import build

OPTIONS = {
    "color": {"type": "bool", "key": "Color", "section": "options", "as": "flag"},
    "cache_dir": {"type": "list", "items": {"type": "string"}, "key": "CacheDir", "section": "options", "as": "list"},
    "sig_level": {"type": "string", "key": "SigLevel", "section": "options", "single_line": True},
    "other": {"type": "string", "key": "Other", "section": "extra"},
}


def write_role(tmp_path, options, files):
    folder = tmp_path / "demo"
    folder.mkdir(exist_ok=True)
    data = {"bastet": "role-definition", "name": "demo", "version": "1.0.0", "api": 0, "description": "A demo role",
            "options": options, "files": files}
    path = folder / "demo role.md"
    path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\nNotes.\n", encoding="utf-8")
    return parse_role(path)


def ini_role(tmp_path, entry=None, options=None):
    return write_role(tmp_path, options or OPTIONS, [entry or {"path": "/etc/x.conf", "edit": "ini"}])


def apt_role(tmp_path):
    opts = {"acquire_languages": {"type": "list", "items": {"type": "string"}, "key": "Acquire::Languages"}}
    return write_role(tmp_path, opts, [{"path": "/etc/apt/apt.conf.d/50demo", "render": "apt"}])


def built(role, values):
    host = HostInfo(name="laptop1", type="laptop", data={"os": "Arch Linux"}, root=Path("/nonexistent"), lab={})
    [batch] = build(role, values, host)
    return batch.resources


def test_one_settings_per_section_with_keys_and_lines(tmp_path):
    options, extra = built(ini_role(tmp_path), {"color": True, "cache_dir": ["/a/", "/b/"], "sig_level": "Required", "other": "x"})
    assert isinstance(options, Settings) and options.section == "options"
    assert options.keys == ("Color", "CacheDir", "SigLevel")
    assert options.lines == ("Color", "CacheDir = /a/ /b/", "SigLevel = Required")
    assert extra.section == "extra" and extra.lines == ("Other = x",)


def test_off_and_empty_values_keep_the_key_but_write_no_line(tmp_path):
    [options] = built(ini_role(tmp_path), {"color": False, "cache_dir": []})
    assert options.keys == ("Color", "CacheDir") and options.lines == ()


def test_unset_options_are_not_managed(tmp_path):
    assert built(ini_role(tmp_path), {}) == []


def test_validate_reaches_the_resource(tmp_path):
    role = ini_role(tmp_path, entry={"path": "/etc/x.conf", "edit": "ini", "validate": "check %s"})
    [options] = built(role, {"color": True})
    assert options.validate == "check %s"


def test_an_option_without_a_section_is_refused(tmp_path):
    role = ini_role(tmp_path, options={"loose": {"type": "string", "key": "Loose"}})
    with pytest.raises(BastetError, match="edit: ini needs a section"):
        built(role, {"loose": "x"})


@pytest.mark.parametrize("values", [{"sig_level": "a\nSigLevel = Never"}, {"cache_dir": ["/a/", "/b/\nSigLevel = Never"]}])
def test_a_line_break_in_a_value_or_list_item_is_refused(tmp_path, values):
    with pytest.raises(BastetError, match="can't contain a line break"):
        built(ini_role(tmp_path), values)


def test_the_apt_renderer_refuses_line_breaks_too(tmp_path):
    with pytest.raises(BastetError, match="can't contain a line break"):
        built(apt_role(tmp_path), {"acquire_languages": ["en\nAcquire::x \"y\";"]})


@pytest.mark.parametrize("entry, message", [
    ({"edit": "ini", "mode": "0600"}, "don't apply to edit"),
    ({"edit": "ini", "owner": "root"}, "don't apply to edit"),
    ({"edit": "ini", "group": "root"}, "don't apply to edit"),
    ({"edit": "ini", "before": "packages", "after": "files"}, "before or after, not both"),
])
def test_unusable_file_entry_combinations_are_refused(tmp_path, entry, message):
    with pytest.raises(BastetError, match=message):
        ini_role(tmp_path, entry={"path": "/etc/x.conf", **entry})


def test_backup_command_runs_before_every_slot_once(tmp_path):
    role = ini_role(tmp_path, entry={"path": "/etc/x.conf", "edit": "ini", "backup": True})
    command, options = built(role, {"color": True})
    assert isinstance(command, Command) and command.run_before == "repositories"
    assert command.run == "cp -p /etc/x.conf /etc/x.conf.bastet-orig"
    for part in ("test -e '/etc/x.conf.bastet-orig'", "! test -f '/etc/x.conf'", "-e 'Bastet Managed'", "-e 'Managed by Bastet'"):
        assert part in command.unless
    assert isinstance(options, Settings)
