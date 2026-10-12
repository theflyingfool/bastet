from pathlib import Path

from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from bastet.engine.systemd import Hostname, TimeSettings, Unit
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import check_values, load_roles, with_defaults
from bastet.roles.resolve import Applied, resolve

ROLES = load_roles()
TYPES = load_host_types()


def arch():
    return HostInfo(name="vps1", type="vps", data={"os": "Arch Linux"}, root=Path("/nonexistent"), lab={})


def built(values):
    role = ROLES["systemd"]
    applied = Applied(role, with_defaults(role, check_values(role, values, "systemd")))
    return [r for b in batches_for([applied], arch()) for r in b.resources]


def test_the_role_with_no_options_builds_nothing():
    assert not [r for r in built({}) if isinstance(r, (Hostname, TimeSettings, Unit))]


def test_manage_hostname_true_manages_the_hostname():
    assert [type(r) for r in built({"manage_hostname": True})] == [Hostname]


def test_rtc_local_set_explicitly_builds_time_settings():
    (t,) = built({"rtc_local": False})
    assert isinstance(t, TimeSettings) and t.rtc_local is False


def test_a_timezone_alone_leaves_the_hardware_clock_alone():
    (t,) = built({"timezone": "UTC"})
    assert isinstance(t, TimeSettings) and t.timezone == "UTC" and t.rtc_local is None


def test_a_fresh_arch_host_resolves_the_systemd_role_changing_nothing(tmp_path):
    files = {
        "Homelab.md": "---\nbastet: lab\n---\n# Homelab\n",
        "hosts/archdev.md": "---\nbastet: host\ntype: computer\nconnection: local\n---\n# archdev\n",
        "_bastet/facts/archdev facts.md": (
            '---\nbastet: facts\nhost: "[[archdev]]"\ngathered: 2026-10-06T10:00:00Z\nos: Arch Linux\n---\n'),
    }
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    inv = load_inventory(tmp_path, TYPES)
    (applied,) = [a for a in resolve(inv, inv.get("archdev"), TYPES, ROLES) if a.role.name == "systemd"]
    assert applied.values["manage_hostname"] is False and applied.values["rtc_local"] is None
