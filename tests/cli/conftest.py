import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

import bastet.cli.add as add_mod
import bastet.cli.run as run_mod
import bastet.cli.secret as secret_mod
import bastet.roles.builtin as builtin_mod
from bastet.roles.contract import load_roles


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def inventory(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "Homelab"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Tester")
    git(root, "config", "user.email", "tester@example.com")
    (root / "Homelab.md").write_text(
        "---\nbastet: lab\nnetworks:\n  servers:\n    cidr: 10.0.20.0/24\n    reserved: .1-.9\n---\n# Homelab\n"
    )
    (root / "hosts").mkdir()
    (root / "hosts" / "pve1.md").write_text("---\nbastet: host\ntype: proxmox-node\nip: 10.0.10.11\n---\n# pve1\n")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "seed")
    cfg = tmp_path / "bastet.yml"
    cfg.write_text(f"inventory:\n  path: {root}\n")
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    # `connect()` creates its SSH control-socket directory for real (core/remote.py:control_path);
    # keep it under tmp_path instead of the real $XDG_RUNTIME_DIR or ~/.cache.
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    return root


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def secret_keys(inventory: Path) -> dict:
    """Throwaway Bastet key, set as `ssh.key` and as a `secrets.recipients` line in Homelab.md."""
    key_path = inventory.parent / "bastet_key"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key_path)], check=True)
    pub = (inventory.parent / "bastet_key.pub").read_text().strip()
    cfg_path = Path(os.environ["BASTET_CONFIG"])
    cfg_path.write_text(cfg_path.read_text() + f"ssh:\n  key: {key_path}\n")
    homelab = inventory / "Homelab.md"
    homelab.write_text(homelab.read_text().replace("networks:", f"secrets:\n  recipients:\n    - {pub}\nnetworks:"))
    git(inventory, "add", ".")
    git(inventory, "commit", "-q", "-m", "secrets recipients")
    return {"pub": pub, "key_path": key_path}


@pytest.fixture
def interactive(monkeypatch):
    """Pretend stdin/stdout are terminals, so prompts behave as they would for a person."""
    monkeypatch.setattr(secret_mod, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr(secret_mod, "_stdout_is_tty", lambda: True)


@pytest.fixture
def test_role(inventory, tmp_path, monkeypatch):
    """A test-only role with two secret options (one generatable, one not), used by a host's role file.

    Shared across test_secret.py, test_check_apply.py and test_add_role.py, so `load_roles` is patched in
    every module that imports its own copy of it (secret.py, run.py, add.py each bind their own name).
    """
    roles_dir = tmp_path / "roles"
    (roles_dir / "testsecret").mkdir(parents=True)
    (roles_dir / "testsecret" / "role.yml").write_text(
        "description: a role for secrets tests\n"
        "options:\n"
        "  admin_password:\n"
        "    type: string\n"
        "    secret: true\n"
        "    generate:\n"
        "      kind: password\n"
        "      length: 20\n"
        "  db_password:\n"
        "    type: string\n"
        "    secret: true\n"
        "    generate:\n"
        "      kind: password\n"
        "      length: 16\n"
    )
    # A second role, deliberately never applied to any host: used only to exercise the
    # "no generate: Enter asks again" prompt directly (`secret set box othersecret plain_token`),
    # without it also showing up as a needed secret via resolve().
    (roles_dir / "othersecret").mkdir(parents=True)
    (roles_dir / "othersecret" / "role.yml").write_text(
        "description: a role for secrets tests\noptions:\n  plain_token:\n    type: string\n    secret: true\n"
    )
    # A third role, applied to a host but with its secret option left unset in the role file: needed
    # implicitly, by the contract alone (no `secret:` reference written anywhere), and not generatable
    # (used to exercise the "ask" / "add role offers to set" flows for a non-generatable secret).
    (roles_dir / "impliedsecret").mkdir(parents=True)
    (roles_dir / "impliedsecret" / "role.yml").write_text(
        "description: a role for secrets tests\noptions:\n  api_key:\n    type: string\n    secret: true\n"
    )
    merged = {**load_roles(), **load_roles(roles_dir)}
    monkeypatch.setattr(secret_mod, "load_roles", lambda: merged)
    monkeypatch.setattr(run_mod, "load_roles", lambda: merged)
    monkeypatch.setattr(add_mod, "load_roles", lambda: merged)
    # health.py (and anything else calling the contract module directly, e.g. for Secrets.md) imports
    # `load_roles` fresh each call, so it needs the original patched too, not just the three bound copies above.
    import bastet.roles.contract as contract_mod
    monkeypatch.setattr(contract_mod, "load_roles", lambda directory=None: merged if directory is None else load_roles(directory))
    # these roles carry no engine resources; a no-op builder lets check/apply resolve and resolve_refs
    # them (which is all the secrets tests care about) without `batches_for` refusing an unimplemented role.
    no_op_builders = {name: (lambda values, host: []) for name in ("testsecret", "othersecret", "impliedsecret")}
    monkeypatch.setattr(builtin_mod, "BUILDERS", {**builtin_mod.BUILDERS, **no_op_builders})

    box_path = inventory / "hosts" / "box.md"
    if not box_path.exists():
        box_path.write_text("---\nbastet: host\ntype: laptop\n---\n# box\n")
    roles = inventory / "_roles" / "hosts" / "box"
    roles.mkdir(parents=True, exist_ok=True)
    (roles / "testsecret.md").write_text(
        '---\nbastet: role\nrole: testsecret\napplies_to: "[[box]]"\n'
        'admin_password: "secret:admin_password"\ndb_password: "secret:db_password"\n---\n'
    )
    git(inventory, "add", ".")
    git(inventory, "commit", "-q", "-m", "test role")
    return {"host": "box", "role": "testsecret"}


@pytest.fixture(autouse=True)
def _no_real_local_setup(monkeypatch):
    """Setting up this machine as a Bastet host runs sudo; no CLI test may reach the real system.
    Tests that exercise it patch in a fake machine of their own."""
    import bastet.cli.init as init_mod
    monkeypatch.setattr(init_mod, "_sudo_validate", lambda: False)
