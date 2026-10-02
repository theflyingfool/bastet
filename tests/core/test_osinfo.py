import pytest

from bastet.core.osinfo import os_id


@pytest.mark.parametrize("os,expected", [
    ("Arch Linux", "arch"),
    ("Debian GNU/Linux 13 (trixie)", "debian"),
    ("Ubuntu 24.04.1 LTS", "ubuntu"),
    ("Fedora Linux 42 (Server Edition)", "fedora"),
    ("Alpine Linux v3.20", "alpine"),
    ("openSUSE Tumbleweed", "opensuse"),
    ("Linux Mint 22", "mint"),
    ("EndeavourOS", "endeavouros"),
    ("Rocky Linux 9.4 (Blue Onyx)", "rocky"),
    ("", None),
    (None, None),
])
def test_os_id(os, expected):
    assert os_id({"os": os}) == expected
