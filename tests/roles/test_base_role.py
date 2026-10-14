from pathlib import Path

import pytest

from bastet.core.errors import BastetError
from bastet.engine.packages import Package
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import check_values, load_roles, with_defaults
from bastet.roles.resolve import Applied

BASE = load_roles()["base"]
TOOLS = ["vim", "zsh", "git", "htop", "tree", "gdu", "wget", "less"]
ARCH = ("server", "Arch Linux")
DEBIAN = ("server", "Debian GNU/Linux 13 (trixie)")
ARCH_VM = ("vm", "Arch Linux")
LXC = ("lxc", "Debian GNU/Linux 13 (trixie)")
ALPINE = ("server", "Alpine Linux v3.20")
INTEL = "Intel(R) Xeon(R) CPU E5-2650 v4 @ 2.20GHz"
AMD = "AMD Ryzen 9 5950X 16-Core Processor"


def build(values, system=ARCH, cpu=INTEL):
    """The package names and notes the role builds for one host, with only the base role applied."""
    data = {"os": system[1], **({"cpu": cpu} if cpu else {})}
    host = HostInfo(name="media01", type=system[0], data=data, root=Path("/nonexistent"), lab={},
                    physical=system[0] == "server")
    applied = Applied(BASE, with_defaults(BASE, check_values(BASE, values, "base")))
    batches = batches_for([applied], host)
    return [r.name for b in batches for r in b.resources if isinstance(r, Package)], [n for b in batches for n in b.notes]


def test_no_options_on_a_physical_arch_host_installs_the_default_tools_and_microcode():
    names, notes = build({})
    assert names == [*TOOLS, "intel-ucode"] and notes == []


def test_setting_tools_replaces_the_default_list_and_extra_tools_adds():
    assert build({"tools": ["jq"]})[0] == ["jq", "intel-ucode"]
    assert build({"extra_tools": ["jq"]})[0] == [*TOOLS, "jq", "intel-ucode"]
    assert build({"tools": ["jq", "git"], "extra_tools": ["git", "curl"]})[0] == ["jq", "git", "curl", "intel-ucode"]


@pytest.mark.parametrize("system,cpu,package", [
    (ARCH, INTEL, "intel-ucode"), (ARCH, AMD, "amd-ucode"),
    (DEBIAN, INTEL, "intel-microcode"), (DEBIAN, AMD, "amd64-microcode"),
])
def test_microcode_package_by_os_and_vendor(system, cpu, package):
    assert build({}, system, cpu)[0][-1] == package


def test_a_vm_or_container_gets_tools_only_and_an_info_note():
    for system in (ARCH_VM, LXC):
        names, notes = build({}, system, None)
        assert names == TOOLS
        assert [n.level for n in notes] == ["info"] and "microcode" in notes[0].message


def test_microcode_never_installs_no_microcode():
    names, notes = build({"microcode": "never"})
    assert names == TOOLS and notes == []
    assert build({"microcode": "never"}, ARCH, None)[0] == TOOLS  # and a missing CPU fact is no error then


def test_a_physical_host_without_a_cpu_fact_is_an_error_naming_run_g():
    with pytest.raises(BastetError, match="bastet run -g"):
        build({}, ARCH, None)


@pytest.mark.parametrize("system,cpu,words", [(ARCH, "Apple M1", "vendor"), (ALPINE, INTEL, "no microcode package")])
def test_an_unknown_vendor_and_an_os_without_a_package_are_errors(system, cpu, words):
    with pytest.raises(BastetError, match=words):
        build({}, system, cpu)


def test_baseline_is_accepted_and_changes_nothing():
    assert build({"baseline": "anything"}) == build({})
