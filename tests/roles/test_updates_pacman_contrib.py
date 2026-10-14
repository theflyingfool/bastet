from pathlib import Path

import pytest

from bastet.core.shell import ProbeResult
from bastet.engine.model import Unsupported
from bastet.engine.packages import Package, Unaccounted, Updates
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import check_values, load_roles, with_defaults
from bastet.roles.resolve import Applied

ROLES = load_roles()


def host(os="Arch Linux"):
    return HostInfo(name="vps1", type="vps", data={"os": os}, root=Path("/nonexistent"), lab={})


def resources(values, os="Arch Linux"):
    role = ROLES["packages"]
    applied = Applied(role, with_defaults(role, check_values(role, values, "packages")))
    return [r for b in batches_for([applied], host(os)) for r in b.resources]


def contrib(values, os="Arch Linux"):
    return [r for r in resources(values, os) if isinstance(r, Package) and r.name == "pacman-contrib"]


def fakeroot(values, os="Arch Linux"):
    return [r for r in resources(values, os) if isinstance(r, Package) and r.name == "fakeroot"]


@pytest.mark.parametrize("policy", ["auto", "security"])
def test_auto_and_security_add_pacman_contrib_on_arch(policy):
    [p] = contrib({"updates": policy})
    assert p.state == "present"


@pytest.mark.parametrize("policy", ["auto", "security"])
def test_checkupdates_runs_pacman_under_fakeroot_so_it_is_installed_too(policy):
    [p] = fakeroot({"updates": policy})
    assert p.state == "present"
    [report] = [r for r in resources({"updates": policy}) if isinstance(r, Unaccounted)]
    assert "fakeroot" in report.tracked


def test_fakeroot_is_installed_as_a_dependency_in_a_command_of_its_own():
    [p] = fakeroot({"updates": "auto"})
    [c] = contrib({"updates": "auto"})
    assert p.extra_args == ("--asdeps",) and c.extra_args == ()
    assert p.group_key != c.group_key  # so --asdeps never reaches the other packages of the install


def test_fakeroot_follows_the_same_rules_as_pacman_contrib():
    assert fakeroot({"updates": "manual"}) == [] and fakeroot({}) == []
    assert fakeroot({"updates": "auto"}, os="Debian GNU/Linux 13 (trixie)") == []
    assert len(fakeroot({"updates": "auto", "install": [{"name": "fakeroot"}]})) == 1  # not duplicated
    [p] = fakeroot({"updates": "auto", "remove": [{"name": "fakeroot"}]})  # the role's own removal stands
    assert p.state == "absent"
    assert len(contrib({"updates": "auto", "install": [{"name": "fakeroot"}]})) == 1  # each is decided on its own


def test_manual_does_not_add_it():
    assert contrib({"updates": "manual"}) == []
    assert contrib({}) == []


def test_a_debian_host_does_not_get_it():
    assert contrib({"updates": "auto"}, os="Debian GNU/Linux 13 (trixie)") == []


def test_a_name_already_in_install_is_not_duplicated():
    assert len(contrib({"updates": "auto", "install": [{"name": "pacman-contrib"}]})) == 1


def test_a_role_that_removes_it_is_not_given_a_second_opposite_package():
    [p] = contrib({"updates": "auto", "remove": [{"name": "pacman-contrib"}]})
    assert p.state == "absent"
    [report] = [r for r in resources({"updates": "auto", "remove": [{"name": "pacman-contrib"}]}) if isinstance(r, Unaccounted)]
    assert "pacman-contrib" not in report.tracked


def test_it_is_tracked_as_bastet_managed():
    [report] = [r for r in resources({"updates": "auto"}) if isinstance(r, Unaccounted)]
    assert "pacman-contrib" in report.tracked
    [report] = [r for r in resources({"updates": "manual"}) if isinstance(r, Unaccounted)]
    assert "pacman-contrib" not in report.tracked


def test_security_still_adds_it_though_pacman_has_no_security_channel():
    assert len(contrib({"updates": "security"})) == 1
    with pytest.raises(Unsupported):
        Updates(policy="security").current({"manager": ProbeResult(0, "pacman"), "pending": ProbeResult(0, ""),
                                            "security": ProbeResult(0, "")})


def test_the_manual_skip_says_what_to_install():
    with pytest.raises(Unsupported) as e:
        Updates().current({"manager": ProbeResult(0, "pacman"), "pending": ProbeResult(127, ""),
                           "security": ProbeResult(0, "")})
    assert str(e.value) == ("checking for updates on Arch needs checkupdates; "
                            "install pacman-contrib if you'd like an update count")
