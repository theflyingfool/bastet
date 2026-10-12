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


def with_value(monkeypatch):
    """Give the Arch OS default a real value, so an override can be told from the default."""
    from bastet.core import osdefaults
    from bastet.roles import resolve as resolve_module

    real = osdefaults.defaults_for

    def patched(os_id, directory=None):
        found = real(os_id, directory)
        return found.model_copy(update={"roles": {"systemd": {"timezone": "UTC"}}}) if found else None

    monkeypatch.setattr(resolve_module, "defaults_for", patched)


def note(applies_to, tz, folder):
    return {f"_roles/{folder}/systemd.md":
            f'---\nbastet: role\nrole: systemd\napplies_to: "[[{applies_to}]]"\ntimezone: {tz}\n---\n'}


def test_without_a_note_the_os_default_value_wins(tmp_path, monkeypatch):
    with_value(monkeypatch)
    applied = systemd(lab(tmp_path), "arch1")
    assert applied.values["timezone"] == "UTC" and applied.origins["timezone"] == "OS default (arch)"


def test_lab_group_and_host_notes_each_override_the_os_default(tmp_path, monkeypatch):
    with_value(monkeypatch)
    applied = systemd(lab(tmp_path, note("Homelab", "Europe/Paris", "lab")), "arch1")
    assert applied.values["timezone"] == "Europe/Paris" and applied.origins["timezone"] == "lab"
    assert [s.label for s in sorted(applied.sources, key=lambda s: s.rank)] == ["OS default (arch)", "lab"]
    applied = systemd(lab(tmp_path, note("boxes", "Asia/Tokyo", "groups/boxes")), "arch1")
    assert applied.values["timezone"] == "Asia/Tokyo" and applied.origins["timezone"] == "group boxes"
    applied = systemd(lab(tmp_path, note("arch1", "America/Chicago", "hosts/arch1")), "arch1")
    assert applied.values["timezone"] == "America/Chicago" and applied.origins["timezone"] == "host arch1"
