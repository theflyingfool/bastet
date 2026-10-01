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
    def __init__(self, container: str) -> None:
        self.container = container
        self.name = f"podman:{container}"

    def run(self, script: str, *, timeout: int = 120) -> CommandResult:
        r = subprocess.run(["podman", "exec", "-i", self.container, "sh", "-s"], input=script,
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


@pytest.fixture
def host(contract_image):
    name = f"bastet-ct-{uuid.uuid4().hex[:8]}"
    subprocess.run(["podman", "run", "-d", "--name", name, "--systemd=always", "--cap-add", "SYS_ADMIN",
                    "--no-hostname", contract_image], check=True, capture_output=True)
    try:
        subprocess.run(["podman", "exec", name, "systemctl", "is-system-running", "--wait"],
                       capture_output=True, timeout=90)
        yield PodmanRunner(name)
    finally:
        subprocess.run(["podman", "rm", "-f", "-t", "0", name], capture_output=True)
