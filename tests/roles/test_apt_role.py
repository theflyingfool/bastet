from pathlib import Path

import pytest

from bastet.core.errors import BastetError
from bastet.engine.files import File
from bastet.engine.packages import Package, Repository
from bastet.engine.run import collect_items
from bastet.engine.slots import apply_order
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import check_values, load_roles, with_defaults
from bastet.roles.resolve import Applied

ROLES = load_roles()
PATH = "/etc/apt/apt.conf.d/90-bastet"
HEADER = "# Managed by Bastet (apt role). Edit the role file, not this file.\n"


def ap(name, values):
    r = ROLES[name]
    return Applied(r, with_defaults(r, check_values(r, values, name)))


def host(os="Debian GNU/Linux 13 (trixie)"):
    return HostInfo(name="srv1", type="vm", data={"os": os}, root=Path("/nonexistent"), lab={})


def built(values, h=None):
    [batch] = batches_for([ap("apt", values)], h or host())
    return batch.resources


def test_one_file_resource_with_path_mode_and_validate():
    [f] = built({})
    assert f == File(path=PATH, content=HEADER, mode="0644", validate="apt-config -c %s dump >/dev/null", provides=("package-manager",))


def test_unset_options_leave_no_lines():
    [f] = built({})
    assert f.content == HEADER and "Install-Recommends" not in f.content


def test_golden_proxy_and_timeouts():
    [f] = built({"acquire_http_proxy": "http://proxy.example.net:3128", "acquire_http_timeout": 30, "acquire_retries": 3})
    assert f.content == (HEADER + 'Acquire::Retries "3";\nAcquire::http::Timeout "30";\n'
                         'Acquire::http::Proxy "http://proxy.example.net:3128";\n')


def test_golden_bools_and_lists():
    [f] = built({"install_recommends": False, "install_suggests": False, "acquire_languages": ["en", "none"],
                 "dpkg_options": ["--force-confdef", "--force-confold"], "default_release": "trixie-backports"})
    assert f.content == (HEADER + 'APT::Install-Recommends "false";\nAPT::Install-Suggests "false";\n'
                         'APT::Default-Release "trixie-backports";\nAcquire::Languages { "en"; "none"; };\n'
                         'Dpkg::Options { "--force-confdef"; "--force-confold"; };\n')


def test_every_option_maps_to_its_apt_key():
    values = {"install_recommends": True, "install_suggests": True, "default_release": "r", "keep_downloaded_packages": True,
              "autoremove_suggests_important": False, "acquire_retries": 0, "acquire_http_timeout": 1, "acquire_https_timeout": 2,
              "acquire_http_proxy": "p", "acquire_https_proxy": "q", "acquire_languages": [], "dpkg_options": ["--x"]}
    [f] = built(values)
    assert f.content.splitlines()[1:] == [
        'APT::Install-Recommends "true";', 'APT::Install-Suggests "true";', 'APT::Default-Release "r";',
        'APT::Keep-Downloaded-Packages "true";', 'APT::AutoRemove::SuggestsImportant "false";', 'Acquire::Retries "0";',
        'Acquire::http::Timeout "1";', 'Acquire::https::Timeout "2";', 'Acquire::http::Proxy "p";', 'Acquire::https::Proxy "q";',
        "Acquire::Languages { };", 'Dpkg::Options { "--x"; };']


def test_a_host_that_is_not_debian_based_is_refused_with_the_group_to_aim_at():
    with pytest.raises(BastetError, match=r"apt role: srv1 isn't Debian-based \(Arch Linux\); aim it at \[\[debian\]\]"):
        built({}, host("Arch Linux"))


@pytest.mark.parametrize("values,message", [
    ({"acquire_retries": -1}, "acquire_retries"),
    ({"acquire_http_timeout": 0}, "acquire_http_timeout"),
    ({"acquire_https_timeout": 0}, "acquire_https_timeout"),
    ({"default_release": "a\nb"}, "default_release"),
    ({"acquire_http_proxy": "a\nb"}, "acquire_http_proxy"),
    ({"acquire_https_proxy": "a\nb"}, "acquire_https_proxy"),
])
def test_min_and_single_line_errors_name_the_option(values, message):
    with pytest.raises(BastetError, match=message):
        check_values(ROLES["apt"], values, "apt")


def test_the_config_file_is_applied_before_repositories_and_packages():
    apt = ap("apt", {"install_recommends": False, "repositories": [{"name": "extra", "uris": ["https://deb.example.net/debian"],
                                                                    "suites": ["trixie"], "components": ["main"]}]})
    batches = batches_for([apt, ap("packages", {"install": ["tree"]})], host())
    order = [i.resource for i in apply_order(collect_items(batches))]
    apt_at = next(n for n, r in enumerate(order) if isinstance(r, File) and r.path == PATH)
    later = [n for n, r in enumerate(order) if isinstance(r, Package) or (isinstance(r, File) and r.path.endswith(".sources"))]
    assert later and all(apt_at < n for n in later)
