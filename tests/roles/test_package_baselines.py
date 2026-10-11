from pathlib import Path

from bastet.core.shell import ProbeResult
from bastet.engine.packages import Unaccounted
from bastet.roles.baselines import baseline_for
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import check_values, load_roles, with_defaults
from bastet.roles.resolve import Applied

ROLES = load_roles()


def host(os="Arch Linux", **data):
    return HostInfo(name="vps1", type="vps", data={"os": os, **data}, root=Path("/nonexistent"), lab={})


def ok(text):
    return ProbeResult(0, text)


def test_a_linode_arch_host_gets_the_shipped_baseline():
    names = baseline_for(host(provider="linode"))
    assert {"base", "cloud-init", "grub", "linux", "openssh", "sudo", "vim"} <= set(names) and len(names) == 20


def test_provider_matching_is_case_insensitive():
    assert baseline_for(host(provider="Linode")) == baseline_for(host(provider="linode"))


def test_other_providers_other_oses_and_no_provider_get_nothing():
    assert baseline_for(host(provider="hetzner")) == ()
    assert baseline_for(host(os="Debian GNU/Linux 13 (trixie)", provider="linode")) == ()
    assert baseline_for(host()) == ()


def test_a_provider_value_cannot_escape_the_baselines_folder():
    assert baseline_for(host(provider="../roles/packages/role")) == ()
    assert baseline_for(host(provider="a/b")) == ()


def test_the_unaccounted_report_allows_the_baseline_and_the_users_own_allowed_list():
    role = ROLES["packages"]
    applied = Applied(role, with_defaults(role, check_values(role, {"allowed": ["htop", "grub"]}, "packages")))
    batches = batches_for([applied], host(provider="linode"))
    report = [r for b in batches for r in b.resources if isinstance(r, Unaccounted)][0]
    assert {"cloud-init", "grub", "htop"} <= set(report.allowed)
    assert report.allowed.count("htop") == 1 and report.allowed.count("grub") == 1


def test_a_baseline_package_is_not_reported_but_others_are():
    unaccounted = Unaccounted(tracked=(), allowed=baseline_for(host(provider="linode")))
    cur = unaccounted.current({"manager": ok("pacman"), "explicit": ok("cloud-init\nhtop\nvim\n"),
                               "system": ok("base\nbase-devel\n")})
    assert cur["unaccounted"] == ("htop",)
