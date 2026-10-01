import shlex
import subprocess

import pytest

from bastet.core.bootstrap import setup_command, setup_script
from bastet.core.errors import BastetError

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFakeFakeFakeFakeFakeFakeFakeFakeFakeFakeFake bastet@laptop"


def test_script_contents():
    s = setup_script(KEY)
    assert "useradd" in s and "usermod -p '*' bastet" in s
    assert KEY in s and "authorized_keys" in s
    assert "visudo -cf /etc/sudoers.d/bastet.new" in s and "NOPASSWD: ALL" in s


def test_script_is_valid_sh():
    subprocess.run(["sh", "-n"], input=setup_script(KEY), text=True, check=True)


def test_command_wraps_with_sudo():
    cmd = setup_command(KEY)
    parts = shlex.split(cmd)
    assert parts[:3] == ["sudo", "sh", "-c"] and parts[3] == setup_script(KEY)


@pytest.mark.parametrize("bad", ["", "not a key", "ssh-ed25519 AAA'x", "ssh-ed25519 AAA\nrm -rf /"])
def test_rejects_bad_keys(bad):
    with pytest.raises(BastetError):
        setup_script(bad)
