from pathlib import Path

import pytest

from bastet.core.errors import BastetError
from bastet.engine.packages import Package
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import check_values, load_roles, with_defaults
from bastet.roles.resolve import Applied

ROLES = load_roles()


def ap(role, values):
    r = ROLES[role]
    return Applied(r, with_defaults(r, check_values(r, values, role)))


def host(os="Debian GNU/Linux 13 (trixie)", physical=False, **data):
    return HostInfo(name="h", type="server" if physical else "vm", data={"os": os, **data}, root=Path("/x"),
                    lab={}, physical=physical)


def names(applied, h):
    return [r.name for b in batches_for([applied], h) for r in b.resources if isinstance(r, Package)]


def test_base_tools_default_and_extra():
    assert names(ap("base", {"extra_tools": ["jq"]}), host()) == ["vim", "zsh", "git", "htop", "tree", "gdu", "wget", "less", "jq"]


def test_microcode_only_on_physical_hosts():
    assert not any("code" in n for n in names(ap("base", {}), host()))
    assert names(ap("base", {}), host(os="Arch Linux", physical=True, cpu="AMD Ryzen 9 5950X 16-Core Processor"))[-1] == "amd-ucode"
    assert names(ap("base", {}), host(physical=True, cpu="Intel(R) Xeon(R) CPU E5-2650 v4"))[-1] == "intel-microcode"
    assert not any("code" in n for n in names(ap("base", {"microcode": "never"}), host(physical=True, cpu="Intel")))


def test_microcode_needs_cpu_fact():
    with pytest.raises(BastetError, match="run bastet gather"):
        batches_for([ap("base", {})], host(physical=True))
