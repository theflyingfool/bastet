import subprocess
from pathlib import Path

import pytest
import pyrage

from bastet.core.secrets import crypto
from bastet.core.secrets.crypto import PathMismatch, SecretError


@pytest.fixture
def keys(tmp_path):
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(tmp_path / "k")], check=True)
    age = pyrage.x25519.Identity.generate()
    (tmp_path / "age.txt").write_text(str(age) + "\n")
    return {"ssh_pub": (tmp_path / "k.pub").read_text().strip(), "ssh_key": tmp_path / "k",
            "age_pub": str(age.to_public()), "age_key": tmp_path / "age.txt"}


def test_seal_and_open_with_either_key(keys):
    armored = crypto.seal("git1/gitea/admin_password", "s3cret", [keys["ssh_pub"], keys["age_pub"]])
    assert armored.startswith("-----BEGIN AGE ENCRYPTED FILE-----") and "s3cret" not in armored
    for key in (keys["ssh_key"], keys["age_key"]):
        assert crypto.open_sealed(armored, "git1/gitea/admin_password", [crypto.identity(key)]).value == "s3cret"


def test_copied_into_another_note_fails(keys):
    armored = crypto.seal("git1/gitea/admin_password", "s3cret", [keys["ssh_pub"]])
    with pytest.raises(PathMismatch, match="sealed for git1/gitea/admin_password"):
        crypto.open_sealed(armored, "db1/postgres/gitea_password", [crypto.identity(keys["ssh_key"])])


def test_not_a_recipient(keys, tmp_path):
    armored = crypto.seal("lab/x", "v", [keys["age_pub"]])
    with pytest.raises(SecretError, match="can't decrypt"):
        crypto.open_sealed(armored, "lab/x", [crypto.identity(keys["ssh_key"])])


def test_next_value_round_trips(keys):
    armored = crypto.seal("lab/x", "old", [keys["age_pub"]], next_value="new")
    sealed = crypto.open_sealed(armored, "lab/x", [crypto.identity(keys["age_key"])])
    assert (sealed.value, sealed.next) == ("old", "new")
