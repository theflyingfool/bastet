from pathlib import Path

import pytest
import yaml

from bastet.core.errors import BastetError
from bastet.engine.files import File
from bastet.engine.systemd import Hostname, Locale, TimeSettings, Unit
from bastet.roles.builtin import HostInfo
from bastet.roles.contract import parse_role
from bastet.roles.declarative import build


def role(tmp_path, systemd, options=None):
    folder = tmp_path / "demo"
    folder.mkdir(exist_ok=True)
    data = {"bastet": "role-definition", "name": "demo", "version": "1.0.0", "api": 0, "description": "A demo role",
            "options": options or {"tz": {"type": "string"}, "ntp": {"type": "bool"}}, "systemd": systemd}
    path = folder / "demo role.md"
    path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\nNotes.\n", encoding="utf-8")
    return parse_role(path)


def built(r, values=None, type="vps", data=None):
    host = HostInfo(name="vps1", type=type, data={"os": "Arch Linux", **(data or {})}, root=Path("/x"), lab={})
    [batch] = build(r, values or {}, host)
    return batch.resources


def test_unit(tmp_path):
    [u] = built(role(tmp_path, [{"kind": "unit", "name": "example-app.service", "enabled": True, "state": "up"}]))
    assert isinstance(u, Unit) and (u.name, u.enabled, u.state) == ("example-app.service", True, "up")


def test_time_takes_option_values_and_drops_unset_ones(tmp_path):
    r = role(tmp_path, [{"kind": "time", "timezone": "{{ tz }}", "ntp": "{{ ntp }}"}])
    [t] = built(r, {"tz": "UTC", "ntp": True})
    assert isinstance(t, TimeSettings) and (t.timezone, t.ntp, t.rtc_local) == ("UTC", True, None)
    assert built(r, {}) == []


def test_time_on_a_container_keeps_only_the_timezone(tmp_path):
    r = role(tmp_path, [{"kind": "time", "timezone": "{{ tz }}", "ntp": "{{ ntp }}", "rtc_local": False}])
    [t] = built(r, {"tz": "UTC", "ntp": True}, type="lxc")
    assert isinstance(t, TimeSettings) and (t.timezone, t.ntp, t.rtc_local) == ("UTC", None, None)
    assert built(r, {"ntp": True}, type="lxc") == []


def test_hostname_uses_the_hosts_name_and_skips_containers(tmp_path):
    r = role(tmp_path, [{"kind": "hostname"}])
    [h] = built(r)
    assert isinstance(h, Hostname) and h.name == "vps1"
    [h] = built(r, data={"hostname": "vps1.example.com"})
    assert h.name == "vps1.example.com"
    assert built(r, type="lxc") == []


def test_locale(tmp_path):
    [loc] = built(role(tmp_path, [{"kind": "locale", "lang": "en_US.UTF-8"}]))
    assert isinstance(loc, Locale) and (loc.lang, loc.keymap) == ("en_US.UTF-8", None)


def test_dropin(tmp_path):
    [f] = built(role(tmp_path, [{"kind": "dropin", "unit": "example-app.service", "name": "bastet", "content": "[Service]\nX=1\n"}]))
    assert isinstance(f, File) and f.path == "/etc/systemd/system/example-app.service.d/bastet.conf"
    assert [t.label for t in f.on_change] == ["daemon-reload", "restart example-app.service"]
    [f] = built(role(tmp_path, [{"kind": "dropin", "unit": "u.service", "name": "n", "content": "x", "restart": False}]))
    assert [t.label for t in f.on_change] == ["daemon-reload"]


def test_when_and_ordering(tmp_path):
    r = role(tmp_path, [{"kind": "unit", "name": "a.service", "when": "ntp", "after": "files"}])
    assert built(r, {"ntp": False}) == []
    [u] = built(r, {"ntp": True})
    assert u.run_after == "files"


@pytest.mark.parametrize("entry, message", [
    ({"name": "x"}, "systemd\\[0\\]: needs a kind"),
    ({"kind": "timer", "name": "x"}, "kind must be one of"),
    ({"kind": "unit"}, "unit: needs name"),
    ({"kind": "unit", "name": "x", "state": "running"}, "state must be up or down"),
    ({"kind": "unit", "name": "x", "enabled": "{{ nope }}"}, "names no option or fact: nope"),
    ({"kind": "unit", "name": "x", "zzz": 1}, "zzz"),
    ({"kind": "dropin", "unit": "u", "name": "n"}, "dropin: needs content"),
])
def test_systemd_entry_errors(tmp_path, entry, message):
    with pytest.raises(BastetError, match=message):
        role(tmp_path, [entry])


def test_a_required_field_that_resolves_to_nothing_is_a_clear_error(tmp_path):
    opts = {"app": {"type": "string"}}
    with pytest.raises(BastetError, match="systemd\\[0\\]: unit: name resolved to nothing"):
        built(role(tmp_path, [{"kind": "unit", "name": "{{ app }}"}], options=opts))
    with pytest.raises(BastetError, match="systemd\\[0\\]: dropin: content resolved to nothing"):
        built(role(tmp_path, [{"kind": "dropin", "unit": "u.service", "name": "n", "content": "{{ app }}"}], options=opts))


def test_a_unit_state_or_enabled_is_checked_after_resolving(tmp_path):
    opts = {"s": {"type": "string"}, "e": {"type": "string"}}
    with pytest.raises(BastetError, match="state resolved to 'bogus'"):
        built(role(tmp_path, [{"kind": "unit", "name": "a.service", "state": "{{ s }}"}], options=opts), {"s": "bogus"})
    with pytest.raises(BastetError, match="enabled resolved to 'yes please'"):
        built(role(tmp_path, [{"kind": "unit", "name": "a.service", "enabled": "{{ e }}"}], options=opts), {"e": "yes please"})
    [u] = built(role(tmp_path, [{"kind": "unit", "name": "a.service", "state": "{{ s }}"}], options=opts), {"s": "up"})
    assert u.state == "up"


def test_a_dropin_restart_that_resolves_to_nothing_means_the_default(tmp_path):
    r = role(tmp_path, [{"kind": "dropin", "unit": "u.service", "name": "n", "content": "x", "restart": "{{ again }}"}],
             options={"again": {"type": "bool"}})
    assert [t.label for t in built(r, {})[0].on_change] == ["daemon-reload", "restart u.service"]
    assert [t.label for t in built(r, {"again": False})[0].on_change] == ["daemon-reload"]
