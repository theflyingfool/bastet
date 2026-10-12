from pathlib import Path

from bastet.core.factsnote import facts_path, render_facts
from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from bastet.roles.contract import load_roles
from bastet.roles.resolve import resolve

TYPES = load_host_types()

FILES = {
    "Homelab.md": "---\nbastet: lab\n---\n# Homelab\n",
    "hosts/arch1.md": "---\nbastet: host\ntype: computer\ngroups:\n  - \"[[boxes]]\"\n---\n# arch1\n",
    "hosts/manj1.md": "---\nbastet: host\ntype: computer\n---\n# manj1\n",
    "hosts/deb1.md": "---\nbastet: host\ntype: computer\n---\n# deb1\n",
    "hosts/plain1.md": "---\nbastet: host\ntype: computer\n---\n# plain1\n",
    "groups/boxes.md": "---\nbastet: group\n---\n# boxes\n",
}

OSES = {"arch1": "Arch Linux", "manj1": "Manjaro Linux", "deb1": "Debian GNU/Linux 13 (trixie)"}


def lab(tmp_path: Path, extra: dict | None = None):
    for rel, text in {**FILES, **(extra or {})}.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    for host, os_name in OSES.items():
        facts_path(tmp_path, host).parent.mkdir(parents=True, exist_ok=True)
        facts_path(tmp_path, host).write_text(render_facts(host, {"os": os_name}, "2026-10-06T10:00:00Z"))
    return load_inventory(tmp_path, TYPES)


def systemd(inv, host):
    found = [a for a in resolve(inv, inv.get(host), TYPES, load_roles()) if a.role.name == "systemd"]
    return found[0] if found else None


def test_arch_host_gets_systemd_labelled_as_the_os_default(tmp_path):
    inv = lab(tmp_path)
    applied = systemd(inv, "arch1")
    assert applied is not None
    assert [s.label for s in applied.sources] == ["OS default (arch)"]
    assert systemd(inv, "deb1") is None and systemd(inv, "plain1") is None


def test_arch_like_host_gets_it_too(tmp_path):
    applied = systemd(lab(tmp_path), "manj1")
    assert applied is not None and applied.sources[0].label == "OS default (arch)"


def test_group_beats_the_os_default_and_host_beats_the_group(tmp_path):
    group = '---\nbastet: role\nrole: systemd\napplies_to: "[[boxes]]"\ntimezone: UTC\n---\n'
    inv = lab(tmp_path, {"_roles/groups/boxes/systemd.md": group})
    applied = systemd(inv, "arch1")
    assert applied.values["timezone"] == "UTC" and applied.origins["timezone"] == "group boxes"
    assert [s.label for s in applied.sources] == ["OS default (arch)", "group boxes"]
    host = '---\nbastet: role\nrole: systemd\napplies_to: "[[arch1]]"\ntimezone: America/Chicago\n---\n'
    inv = lab(tmp_path, {"_roles/hosts/arch1/systemd.md": host})
    assert systemd(inv, "arch1").values["timezone"] == "America/Chicago"
