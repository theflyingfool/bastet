from pathlib import Path

import pytest
import yaml

from bastet.core.errors import BastetError
from bastet.engine.files import Block, File
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import check_values, load_roles, parse_role, with_defaults
from bastet.roles.resolve import Applied

ROLES = load_roles()


def _host(os):
    return HostInfo(name="srv1", type="vm", data={"os": os}, root=Path("/nonexistent"), lab={})


def debian_host():
    return _host("Debian GNU/Linux 13 (trixie)")


def arch_host():
    return _host("Arch Linux")


def built(role_name, values, host):
    role = ROLES[role_name]
    return [r for b in batches_for([Applied(role, with_defaults(role, values))], host) for r in b.resources]


def bad_role(tmp_path, option):
    folder = tmp_path / "demo"
    folder.mkdir(exist_ok=True)
    data = {"bastet": "role-definition", "name": "demo", "version": "1.0.0", "api": 0, "description": "A demo role",
            "options": {"repos": option}}
    path = folder / "demo role.md"
    path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\nNotes.\n", encoding="utf-8")
    return parse_role(path)


def apt_file(out, name):
    [file] = [r for r in out if isinstance(r, File) and r.path == f"/etc/apt/sources.list.d/{name}.sources"]
    return file


def test_apt_repository_is_a_sources_file_before_packages():
    out = built("apt", {"repositories": [{"name": "backports", "uris": ["http://deb.example.net/debian"],
                                          "suites": ["trixie-backports"], "components": ["main"]}]}, debian_host())
    file = apt_file(out, "backports")
    assert file.mode == "0644" and file.run_before == "packages"
    assert file.content == ("Types: deb\nURIs: http://deb.example.net/debian\nSuites: trixie-backports\nComponents: main\n")


def test_apt_flags_and_multiline_keys_are_written_in_deb822_style():
    key = "-----BEGIN PGP PUBLIC KEY BLOCK-----\n\nAAAA\n-----END PGP PUBLIC KEY BLOCK-----"
    out = built("apt", {"repositories": [{"name": "k", "uris": ["http://x.example.net/"], "suites": ["s"],
                                          "enabled": False, "trusted": True, "signed_by": key}]}, debian_host())
    assert apt_file(out, "k").content == (
        "Types: deb\nURIs: http://x.example.net/\nSuites: s\nEnabled: no\nTrusted: yes\n"
        "Signed-By:\n -----BEGIN PGP PUBLIC KEY BLOCK-----\n .\n AAAA\n -----END PGP PUBLIC KEY BLOCK-----\n")
    path_form = built("apt", {"repositories": [{"name": "p", "uris": ["http://x/"], "suites": ["s"], "signed_by": "/usr/share/keyrings/x.gpg"}]}, debian_host())
    assert "Signed-By: /usr/share/keyrings/x.gpg\n" in apt_file(path_form, "p").content


def test_pacman_repository_is_a_marked_block_before_packages():
    out = built("pacman", {"repositories": [{"name": "custom", "servers": ["https://example.net/$repo/os/$arch"], "sig_level": "Optional"}]}, arch_host())
    [block] = [r for r in out if isinstance(r, Block)]
    assert block.path == "/etc/pacman.conf" and block.marker == "bastet repo custom" and block.run_before == "packages"
    assert block.block == "[custom]\nServer = https://example.net/$repo/os/$arch\nSigLevel = Optional"


def test_pacman_repository_with_several_servers_and_an_include():
    out = built("pacman", {"repositories": [{"name": "r", "servers": ["https://a/", "https://b/"], "include": "/etc/pacman.d/mirrorlist"}]}, arch_host())
    [block] = [r for r in out if isinstance(r, Block)]
    assert block.block == "[r]\nServer = https://a/\nServer = https://b/\nInclude = /etc/pacman.d/mirrorlist"


def test_a_disabled_pacman_repository_is_commented_out():
    out = built("pacman", {"repositories": [{"name": "off", "servers": ["https://x.example.net/"], "enabled": False}]}, arch_host())
    [block] = [r for r in out if isinstance(r, Block)]
    assert block.block == "#[off]\n#Server = https://x.example.net/"


@pytest.mark.parametrize("role_name, host_kind", [("apt", "debian"), ("pacman", "arch")])
def test_bad_names_and_line_breaks_are_refused(role_name, host_kind):
    host = debian_host() if host_kind == "debian" else arch_host()
    with pytest.raises(BastetError, match="isn't a usable name"):
        built(role_name, {"repositories": [{"name": "a b", "uris": ["http://x/"], "servers": ["http://x/"]}]}, host)
    field = "suites" if role_name == "apt" else "servers"
    with pytest.raises(BastetError, match="can't contain a line break"):
        built(role_name, {"repositories": [{"name": "ok", "uris": ["http://x/"], field: ["a\nUsage = All"]}]}, host)


def test_no_repositories_means_no_extra_resources():
    assert not [r for r in built("apt", {}, debian_host()) if isinstance(r, File) and "sources.list.d" in r.path]


def test_the_packages_role_has_no_repositories_option():
    with pytest.raises(BastetError, match="packages has no option 'repositories'"):
        check_values(ROLES["packages"], {"repositories": [{"name": "x", "uris": ["http://x"]}]}, "f")


_ITEMS = {"type": "object", "fields": {"name": {"type": "string"}}}


@pytest.mark.parametrize("option, message", [
    ({"type": "string", "as": "entries", "format": "ini_section", "path": "/x", "key": "X"}, "as: entries needs a list of objects"),
    ({"type": "list", "items": _ITEMS, "as": "entries", "path": "/x"}, "needs format"),
    ({"type": "list", "items": _ITEMS, "as": "entries", "format": "zzz", "path": "/x"}, "needs format"),
    ({"type": "list", "items": _ITEMS, "as": "entries", "format": "deb822"}, "needs a path"),
    ({"type": "string", "format": "deb822"}, "format only applies to as: entries"),
    ({"type": "list", "items": _ITEMS, "as": "entries", "format": "deb822", "path": "/x/{name}", "marker": "m"}, "marker only applies to ini_section"),
])
def test_entries_option_contract(tmp_path, option, message):
    with pytest.raises(BastetError, match=message):
        bad_role(tmp_path, option)
