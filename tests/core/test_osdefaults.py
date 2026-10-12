import pytest

from bastet.core.errors import BastetError
from bastet.core.osdefaults import defaults_for, load_os_defaults

ARCH_ACCOUNTS = ("bin", "daemon", "mail", "ftp", "http", "nobody", "dbus", "tss", "uuidd", "_talkd")


def test_shipped_arch_defaults():
    arch = load_os_defaults()["arch"]
    assert "systemd" in arch.roles
    assert arch.accounts == ARCH_ACCOUNTS


@pytest.mark.parametrize("ident", ["arch", "manjaro", "endeavouros", "cachyos"])
def test_arch_like_ids_get_arch(ident):
    assert defaults_for(ident) is not None
    assert defaults_for(ident).name == "arch"


@pytest.mark.parametrize("ident", [None, "", "debian", "fedora"])
def test_unknown_or_missing_os_is_none(ident):
    assert defaults_for(ident) is None


def test_empty_folder(tmp_path):
    assert load_os_defaults(tmp_path) == {}
    assert defaults_for("arch", tmp_path) is None


@pytest.mark.parametrize("text", [
    "name: arch\nbogus: 1\n",
    "name: arch\naccounts: [\"bad name\"]\n",
    "name: arch\naccounts: root\n",
    "name: [unclosed\n",
])
def test_invalid_file_names_the_file(tmp_path, text):
    path = tmp_path / "arch.yml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(BastetError) as err:
        load_os_defaults(tmp_path)
    assert err.value.file == path
    assert "invalid OS defaults" in err.value.message


def test_a_bad_accounts_entry_names_the_key(tmp_path):
    (tmp_path / "arch.yml").write_text('name: arch\naccounts: ["bad name"]\n', encoding="utf-8")
    with pytest.raises(BastetError) as err:
        load_os_defaults(tmp_path)
    assert err.value.key == "accounts" and err.value.file == tmp_path / "arch.yml"


def test_a_bad_role_value_in_an_os_file_names_the_file(tmp_path, monkeypatch):
    from bastet.core.factsnote import facts_path, render_facts
    from bastet.core.hosttypes import load_host_types
    from bastet.core.inventory import load_inventory
    from bastet.roles.contract import load_roles
    from bastet.roles import resolve as resolve_module
    from bastet.roles.resolve import resolve

    folder = tmp_path / "oses"
    folder.mkdir()
    path = folder / "arch.yml"
    path.write_text("name: arch\nroles:\n  systemd: {manage_hostname: maybe}\n", encoding="utf-8")
    monkeypatch.setattr(resolve_module, "defaults_for", lambda os_id, directory=None: defaults_for(os_id, folder))
    (tmp_path / "Homelab.md").write_text("---\nbastet: lab\n---\n# Homelab\n", encoding="utf-8")
    (tmp_path / "hosts").mkdir()
    (tmp_path / "hosts" / "arch1.md").write_text("---\nbastet: host\ntype: computer\n---\n# arch1\n", encoding="utf-8")
    facts_path(tmp_path, "arch1").parent.mkdir(parents=True, exist_ok=True)
    facts_path(tmp_path, "arch1").write_text(render_facts("arch1", {"os": "Arch Linux"}, "2026-10-06T10:00:00Z"))
    types = load_host_types()
    inv = load_inventory(tmp_path, types)
    with pytest.raises(BastetError) as err:
        resolve(inv, inv.get("arch1"), types, load_roles())
    assert err.value.file == path


def test_custom_folder_defaults(tmp_path):
    (tmp_path / "arch.yml").write_text("name: arch\naccounts: [alpha, alpha]\n", encoding="utf-8")
    assert defaults_for("manjaro", tmp_path).accounts == ("alpha",)
