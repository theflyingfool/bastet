from pathlib import Path

from bastet.engine.command import Command
from bastet.engine.files import Block
from bastet.engine.packages import Package
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import check_value, check_values, load_roles, with_defaults
from bastet.roles.resolve import Applied

ROLES = load_roles()


def built(role, values):
    r = ROLES[role]
    applied = [Applied(r, with_defaults(r, check_values(r, values, role)))]
    host = HostInfo(name="media01", type="vm", data={"os": "Arch Linux", "hostname": "media01"},
                    root=Path("/nonexistent"), lab={})
    return [res for b in batches_for(applied, host) for res in b.resources]


def test_a_bare_comment_in_a_block_item_keeps_the_default_comment():
    out = built("files", {"blocks": [{"path": "/etc/x", "marker": "m", "block": "b", "comment": None}]})
    assert next(r for r in out if isinstance(r, Block)).comment == "#"


def test_a_bare_root_in_a_command_item_keeps_the_default_root():
    out = built("files", {"commands": [{"name": "n", "run": "true", "unless": "false", "root": None}]})
    assert next(r for r in out if isinstance(r, Command)).root is True


def test_a_bare_field_in_a_package_item_is_dropped():
    values = check_values(ROLES["packages"], {"install": [{"name": "nano", "manager": None}]}, "packages")
    assert values["install"] == [{"name": "nano"}]
    assert any(isinstance(r, Package) for r in built("packages", {"install": [{"name": "nano", "manager": None}]}))


def test_note_values_keep_nulls_in_maps_and_objects_but_not_in_list_items():
    files = ROLES["files"]
    block = {"path": "/x", "marker": "m", "block": "b", "comment": None}
    out = check_values(files, {"files": {"/etc/a": None}, "blocks": [block]}, "files")
    assert out["files"] == {"/etc/a": None}
    assert out["blocks"] == [{"path": "/x", "marker": "m", "block": "b"}]


def test_check_value_drops_nulls_unless_asked_to_keep_them():
    opt = ROLES["files"].options["files"]
    value = {"/etc/a": None, "/etc/b": {"content": "x", "mode": None}}
    assert check_value(opt, value, "files") == {"/etc/b": {"content": "x"}}
    assert check_value(opt, value, "files", keep_nulls=True) == value
