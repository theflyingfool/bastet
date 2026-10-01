import pytest

from bastet.core.errors import BastetError
from bastet.core.hosttypes import load_host_types


def test_shipped_types():
    types = load_host_types()
    assert set(types) == {"proxmox-node", "server", "laptop", "vps", "lxc", "vm", "unknown"}
    assert types["vps"].minimal == ["provider", "ip"]
    assert types["lxc"].minimal == ["runs_on", "ip"]
    assert types["proxmox-node"].physical is True
    assert types["lxc"].fields["ram"] == "desired"
    assert types["proxmox-node"].fields["ram"] == "fact"


def test_bad_nature_names_file(tmp_path):
    bad = tmp_path / "x.yml"
    bad.write_text("name: x\nfields:\n  ram: maybe\n")
    with pytest.raises(BastetError) as e:
        load_host_types(tmp_path)
    assert e.value.file == bad
