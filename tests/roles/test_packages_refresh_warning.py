from pathlib import Path

from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import check_values, load_roles, with_defaults
from bastet.roles.resolve import Applied

ROLES = load_roles()


def notes(os, **values):
    role = ROLES["packages"]
    applied = Applied(role, with_defaults(role, check_values(role, values, "packages")))
    host = HostInfo(name="vps1", type="vps", data={"os": os}, root=Path("/x"), lab={})
    return [n for b in batches_for([applied], host) for n in b.notes]


def test_refresh_false_on_arch_warns_on_every_build():
    for _ in range(2):
        [note] = notes("Arch Linux", refresh=False)
        assert note.level == "warning" and note.role == "packages"
        assert "refresh: false" in note.message and "404" in note.message


def test_other_hosts_and_the_default_get_no_warning():
    assert notes("Debian GNU/Linux 13 (trixie)", refresh=False) == []
    assert notes("Arch Linux") == []
    assert notes("Arch Linux", refresh=True) == []
