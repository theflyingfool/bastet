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


def test_custom_folder_defaults(tmp_path):
    (tmp_path / "arch.yml").write_text("name: arch\naccounts: [alpha, alpha]\n", encoding="utf-8")
    assert defaults_for("manjaro", tmp_path).accounts == ("alpha",)
