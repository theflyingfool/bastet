"""Contract tests: every resource converges on a throwaway Debian 13 systemd container, and a rerun changes nothing.

Opt-in: BASTET_CONTRACT=1 uv run pytest tests/contract   (needs podman; pulls debian:trixie once)
"""

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from bastet.core.remote import CommandResult

HERE = Path(__file__).parent
IMAGE = "localhost/bastet-contract:debian-13"


class PodmanRunner:
    """Runs scripts in the container as root, or as the `bastet` user through a login shell (its real PATH,
    root only through `sudo -n`), the way Bastet reaches real hosts."""

    def __init__(self, container: str, user: str = "root") -> None:
        self.container = container
        self.user = user
        self.name = f"podman:{container}:{user}"

    def run(self, script: str, *, timeout: int = 120) -> CommandResult:
        shell = ["sh", "-s"] if self.user == "root" else ["su", "-", self.user, "-c", "sh -s"]
        r = subprocess.run(["podman", "exec", "-i", self.container, *shell], input=script,
                           capture_output=True, text=True, timeout=timeout)
        return CommandResult(r.stdout, r.stderr, r.returncode)


@pytest.fixture(scope="session")
def contract_image() -> str:
    if os.environ.get("BASTET_CONTRACT") != "1":
        pytest.skip("contract tests run with BASTET_CONTRACT=1")
    if not shutil.which("podman"):
        pytest.skip("podman isn't installed")
    subprocess.run(["podman", "build", "-q", "-t", IMAGE, "-f", str(HERE / "Containerfile"), str(HERE)],
                   check=True, capture_output=True)
    return IMAGE


@pytest.fixture(params=["root", "bastet"])
def host(request, contract_image):
    name = f"bastet-ct-{uuid.uuid4().hex[:8]}"
    subprocess.run(["podman", "run", "-d", "--name", name, "--systemd=always", "--cap-add", "SYS_ADMIN",
                    "--no-hostname", contract_image], check=True, capture_output=True)
    try:
        subprocess.run(["podman", "exec", name, "systemctl", "is-system-running", "--wait"],
                       capture_output=True, timeout=90)
        yield PodmanRunner(name, request.param)
    finally:
        subprocess.run(["podman", "rm", "-f", "-t", "0", name], capture_output=True)


ARCH_IMAGE = "localhost/bastet-contract:arch"


@pytest.fixture(scope="session")
def arch_image(contract_image) -> str:
    subprocess.run(["podman", "build", "-q", "-t", ARCH_IMAGE, "-f", str(HERE / "Containerfile.arch"), str(HERE)],
                   check=True, capture_output=True)
    return ARCH_IMAGE


@pytest.fixture
def arch_host(arch_image):
    name = f"bastet-ct-arch-{uuid.uuid4().hex[:8]}"
    subprocess.run(["podman", "run", "-d", "--name", name, arch_image], check=True, capture_output=True)
    try:
        # The test setup syncs the package database once; the engine itself never runs pacman -Sy.
        subprocess.run(["podman", "exec", name, "pacman", "-Sy", "--noconfirm"], check=True, capture_output=True, timeout=300)
        yield PodmanRunner(name)
    finally:
        subprocess.run(["podman", "rm", "-f", "-t", "0", name], capture_output=True)
