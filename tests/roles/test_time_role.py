from pathlib import Path

import pytest

from bastet.core.errors import BastetError
from bastet.core.factsnote import render_facts
from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from bastet.engine.files import Settings
from bastet.engine.systemd import TimeSettings, Unit
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import check_relations, check_values, load_roles, with_defaults
from bastet.roles.resolve import Applied, resolve

ROLES = load_roles()
TIME = ROLES["time"]
TYPES = load_host_types()
DROP_IN = "/etc/systemd/timesyncd.conf.d/bastet.conf"
UNIT = "systemd-timesyncd.service"

ARCH = ("vps", "Arch Linux")
DEBIAN = ("vps", "Debian GNU/Linux 13 (trixie)")
LXC = ("lxc", "Debian GNU/Linux 13 (trixie)")


def build(values, system=ARCH, origins=None):
    """The resources and notes the role builds for one host, with only the time role applied."""
    host = HostInfo(name="media01", type=system[0], data={"os": system[1]}, root=Path("/nonexistent"), lab={})
    applied = Applied(TIME, with_defaults(TIME, check_values(TIME, values, "time")), origins=origins or {})
    batches = batches_for([applied], host)
    return [r for b in batches for r in b.resources], [n for b in batches for n in b.notes]


def test_no_options_emit_nothing_on_any_system():
    for system in (ARCH, DEBIAN, LXC):
        assert build({}, system) == ([], [])


def test_a_timezone_alone_gives_one_time_setting_and_no_sync():
    for system in (ARCH, DEBIAN, LXC):
        resources, notes = build({"timezone": "Europe/Berlin"}, system)
        assert resources == [TimeSettings(timezone="Europe/Berlin")] and notes == []
        assert resources[0].ntp is None and resources[0].rtc_local is None


def test_only_known_time_zones_are_accepted():
    with pytest.raises(BastetError, match="Mars/Base"):
        build({"timezone": "Mars/Base"})
    assert build({"timezone": "Europe/Berlin"})[0]


def test_ntp_true_writes_the_drop_in_restarts_the_service_and_enables_it():
    resources, notes = build({"ntp": True, "ntp_servers": ["10.1.1.1"], "poll_interval_min_sec": "1d",
                              "save_interval_sec": "infinity"})
    drop_in, unit = resources
    assert isinstance(drop_in, Settings) and drop_in.path == DROP_IN and drop_in.section == "Time"
    assert drop_in.keys == ("NTP", "PollIntervalMinSec", "SaveIntervalSec")
    assert drop_in.lines == ("NTP = 10.1.1.1", "PollIntervalMinSec = 1d", "SaveIntervalSec = infinity")
    assert [t.command for t in drop_in.on_change] == [f"systemctl restart {UNIT}"]  # and no daemon-reload
    assert unit == Unit(name=UNIT, enabled=True, state="up") and notes == []


def test_the_fallback_servers_are_a_space_separated_list():
    (drop_in, _), _ = build({"ntp": True, "ntp_servers": ["10.1.1.1", "10.1.1.2"], "ntp_fallback_servers": ["10.1.1.3"]})
    assert drop_in.lines == ("NTP = 10.1.1.1 10.1.1.2", "FallbackNTP = 10.1.1.3")


def test_ntp_true_without_settings_only_enables_the_unit():
    resources, _ = build({"ntp": True})
    assert resources == [Unit(name=UNIT, enabled=True, state="up")]


def test_ntp_false_only_stops_and_disables_the_unit():
    resources, notes = build({"ntp": False})
    assert resources == [Unit(name=UNIT, enabled=False, state="down")] and notes == []


@pytest.mark.parametrize("key", ["ntp_servers", "ntp_fallback_servers", "root_distance_max_sec", "poll_interval_min_sec",
                                 "poll_interval_max_sec", "connection_retry_sec", "save_interval_sec"])
def test_a_timesyncd_setting_needs_ntp_true(key):
    value = ["10.1.1.1"] if key.endswith("servers") else "5s"
    for ntp in ({}, {"ntp": False}):
        with pytest.raises(BastetError, match="ntp"):
            check_relations(TIME, {key: value, **ntp}, "time")


def test_debian_with_ntp_true_is_an_error():
    with pytest.raises(BastetError, match="Arch only"):
        build({"ntp": True, "timezone": "UTC"}, DEBIAN)


def test_debian_with_ntp_false_applies_the_zone_and_only_says_info():
    resources, notes = build({"ntp": False, "timezone": "UTC"}, DEBIAN)
    assert resources == [TimeSettings(timezone="UTC")]
    assert [n.level for n in notes] == ["info"] and "nothing changed" in notes[0].message


def test_a_container_gets_the_zone_and_an_info_note_about_the_node():
    for ntp in (True, False):
        resources, notes = build({"ntp": ntp, "timezone": "UTC"}, LXC)
        assert resources == [TimeSettings(timezone="UTC")]
        assert [n.level for n in notes] == ["info"] and "provided by its host" in notes[0].message


def test_the_lab_wide_warning_names_the_way_out():
    _, notes = build({"ntp": True}, origins={"ntp": "lab"})
    assert [n.level for n in notes] == ["warning"] and "overrides" in notes[0].message
    _, notes = build({"ntp": True}, origins={"ntp": "lab (override)"})
    assert [n.level for n in notes] == ["warning"]


def test_the_warning_is_not_shown_for_a_host_note_or_when_ntp_is_off():
    assert build({"ntp": True}, origins={"ntp": "host media01"})[1] == []
    assert build({"ntp": True}, origins={"ntp": "group arch-vms"})[1] == []
    assert build({"ntp": False}, origins={"ntp": "lab"})[1] == []


# the whole path: notes on disk, resolve, build

LAB = "timezone: Europe/Berlin\nntp: true\noverrides:\n  - when: not host.arch_like\n    ntp: null\n"


def resolved(tmp_path, hosts, notes):
    """hosts: name -> (os text, groups); notes: relative path under _roles -> body."""
    files = {"Homelab.md": "---\nbastet: lab\n---\n# Homelab\n", "groups/debian-vms.md": "---\nbastet: group\n---\n# debian-vms\n"}
    for name, (os_text, groups) in hosts.items():
        listed = "".join(f'  - "[[{g}]]"\n' for g in groups)
        files[f"hosts/{name}.md"] = (f"---\nbastet: host\ntype: computer\nconnection: local\n"
                                     f"{'groups:' + chr(10) + listed if groups else ''}---\n# {name}\n")
        files[f"_bastet/facts/{name} facts.md"] = render_facts(name, {"os": os_text}, "2026-10-06T10:00:00Z")
    for rel, body in notes.items():
        applies = "Homelab" if rel.startswith("lab") else rel.split("/")[1].removesuffix(".md")
        files[f"_roles/{rel}"] = f'---\nbastet: role\nrole: time\napplies_to: "[[{applies}]]"\n{body}---\n'
    for rel, text in files.items():
        p = tmp_path / "inv" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    inv = load_inventory(tmp_path / "inv", TYPES)
    out = {}
    for name in hosts:
        host = inv.get(name)
        info = HostInfo(name=name, type="vps", data={"os": hosts[name][0]}, root=tmp_path, lab={})
        applied = [a for a in resolve(inv, host, TYPES, ROLES) if a.role.name == "time"]
        out[name] = (applied, info)
    return out


def test_a_lab_note_with_an_override_syncs_arch_hosts_and_leaves_debian_with_the_zone_only(tmp_path):
    hosts = {"arch1": ("Arch Linux", []), "pve1": ("Debian GNU/Linux 13 (trixie)", []),
             "deb1": ("Debian GNU/Linux 13 (trixie)", ["debian-vms"])}
    notes = {"lab/time.md": LAB, "groups/debian-vms/time.md": "ntp:\n"}
    out = resolved(tmp_path, hosts, notes)

    (arch,), info = out["arch1"]
    assert arch.values["ntp"] is True
    resources = [r for b in batches_for([arch], info) for r in b.resources]
    assert resources == [TimeSettings(timezone="Europe/Berlin"), Unit(name=UNIT, enabled=True, state="up")]
    assert [n.level for b in batches_for([arch], info) for n in b.notes] == ["warning"]  # set lab-wide

    for name in ("pve1", "deb1"):  # one by the lab override, one by the group's own null
        (applied,), info = out[name]
        assert applied.values["ntp"] is None
        batches = batches_for([applied], info)
        assert [r for b in batches for r in b.resources] == [TimeSettings(timezone="Europe/Berlin")]
        assert [n for b in batches for n in b.notes] == []
