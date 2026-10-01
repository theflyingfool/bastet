import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner


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
    return root


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()
