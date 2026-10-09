import re
import subprocess
import threading
from pathlib import Path

import pytest

import bastet.cli.gather as gather_mod
from bastet.cli.app import app
from bastet.core.errors import AuthFailed
from bastet.core.hostkeys import parse_keyscan
from bastet.core.parallel import in_worker
from bastet.core.remote import CommandResult
from gather_fixtures import LAPTOP, RACK, stdout_for

KEYS = parse_keyscan("h ssh-ed25519 aGVsbG8=\n")
HOST_KEY = f"ssh-ed25519 {KEYS[0].fingerprint}"


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout


def facts(root: Path, name: str) -> str:
    from bastet.core.factsnote import facts_path

    path = facts_path(root, name)
    return path.read_text() if path.exists() else ""


def add_host(root: Path, name: str, text: str) -> None:
    (root / "hosts" / f"{name}.md").write_text(text)
    git(root, "add", f"hosts/{name}.md")
    git(root, "commit", "-q", "-m", f"add {name}")


def _vps_host(root: Path, name: str, ip: str) -> None:
    add_host(
        root, name,
        f"---\nbastet: host\ntype: vps\nprovider: linode\nip: {ip}\nssh_host_key: {HOST_KEY}\n---\n# {name}\n",
    )


class BlockingRunner:
    """A fake runner whose real collect script waits at a barrier; the cheap `true` probe never blocks."""

    def __init__(self, outputs, barrier, name="fake"):
        self.outputs = outputs
        self.barrier = barrier
        self.name = name

    def run(self, script, *, timeout=120):
        match = re.search(r"'(@@BASTET[^']*@@)'", script)
        if match is None:
            return CommandResult("", "", 0)  # the cheap probe: always succeeds, never blocks
        self.barrier.wait(timeout=1)
        return CommandResult(stdout_for(self.outputs, match.group(1)), "", 0)


@pytest.fixture
def three_hosts(inventory, monkeypatch):
    for i, name in enumerate(["h1", "h2", "h3"], start=1):
        _vps_host(inventory, name, f"203.0.113.{10 + i}")
    monkeypatch.setattr(gather_mod, "scan_keys", lambda address, recorded=None, port=22: KEYS)
    return inventory


def test_collect_runs_at_once_with_dash_j_3(runner, three_hosts, monkeypatch):
    barrier = threading.Barrier(3, timeout=1)
    monkeypatch.setattr(
        gather_mod, "ssh_runner", lambda target: BlockingRunner(dict(LAPTOP, hostname=target.address), barrier)
    )
    result = runner.invoke(app, ["run", "-g", "h1", "h2", "h3", "-y", "-j", "3"])
    assert result.exit_code == 0, result.output
    for name in ("h1", "h2", "h3"):
        assert "os: Arch Linux" in facts(three_hosts, name)


def test_collect_runs_serially_with_dash_j_1(runner, three_hosts, monkeypatch):
    # Only 1 host collects at a time under -j 1, so a 2-party barrier can never fill: the first
    # host to arrive times out waiting for a second, and that broken barrier then fails the rest.
    barrier = threading.Barrier(2, timeout=0.2)
    monkeypatch.setattr(
        gather_mod, "ssh_runner", lambda target: BlockingRunner(dict(LAPTOP, hostname=target.address), barrier)
    )
    result = runner.invoke(app, ["run", "-g", "h1", "h2", "h3", "-y", "-j", "1"])
    assert result.exit_code == 0, result.output
    assert result.output.count("unexpected error") == 3
    for name in ("h1", "h2", "h3"):
        assert "gathered:" not in facts(three_hosts, name)
        assert "os:" not in (three_hosts / "hosts" / f"{name}.md").read_text()


def test_prompts_all_asked_on_main_thread(runner, inventory, secret_keys, monkeypatch):
    add_host(inventory, "first", "---\nbastet: host\ntype: vps\nprovider: linode\nip: 203.0.113.21\n---\n# first\n")
    add_host(
        inventory, "setup",
        f"---\nbastet: host\ntype: vps\nprovider: linode\nip: 203.0.113.22\nssh_host_key: {HOST_KEY}\n---\n# setup\n",
    )
    add_host(
        inventory, "tools",
        f"---\nbastet: host\ntype: proxmox\nip: 203.0.113.23\nssh_host_key: {HOST_KEY}\n---\n# tools\n",
    )
    monkeypatch.setattr(gather_mod, "scan_keys", lambda address, recorded=None, port=22: KEYS)

    class FakeRunner:
        def __init__(self, outputs, name):
            self.outputs, self.name = outputs, name

        def run(self, script, *, timeout=120):
            match = re.search(r"'(@@BASTET[^']*@@)'", script)
            if match is None:
                return CommandResult("", "", 0)
            return CommandResult(stdout_for(self.outputs, match.group(1)), "", 0)

    class InstallingRunner:
        def __init__(self, before, after):
            self.before, self.after, self.installs, self.name = before, after, [], "tools-runner"

        def run(self, script, *, timeout=120):
            if "BASTET-INSTALL" in script:
                self.installs.append(script)
                return CommandResult("", "", 0)
            match = re.search(r"'(@@BASTET[^']*@@)'", script)
            if match is None:
                return CommandResult("", "", 0)
            return CommandResult(stdout_for(self.after if self.installs else self.before, match.group(1)), "", 0)

    tools_runner = InstallingRunner(dict(RACK, pkg_mgr="apt-get"), dict(RACK, pkg_mgr="apt-get"))

    def ssh_runner(target):
        if target.address == "203.0.113.23":
            return tools_runner
        if target.user == "bastet" and target.address == "203.0.113.22":
            class Refuse:
                name = "bastet@x"

                def run(self, script, *, timeout=120):
                    raise AuthFailed("login refused")
            return Refuse()
        return FakeRunner(dict(LAPTOP, hostname=target.address), f"{target.user}@{target.address}")

    monkeypatch.setattr(gather_mod, "ssh_runner", ssh_runner)
    monkeypatch.setattr(gather_mod, "interactive", lambda target, command: 1)  # setup fails; fall back

    real_confirm = __import__("typer").confirm

    def spy_confirm(*args, **kwargs):
        assert not in_worker(), "a prompt ran off the main thread"
        return real_confirm(*args, **kwargs)

    monkeypatch.setattr(__import__("typer"), "confirm", spy_confirm)

    result = runner.invoke(app, ["run", "-g", "first", "setup", "tools"], input="y\ny\ny\ny\n")
    assert result.exit_code == 0, result.output
    assert "first contact" in result.output
    assert "not set up" in result.output
    assert "Set up the bastet user on setup" in result.output
    assert "install ipmitool" in result.output
    assert len(tools_runner.installs) == 1


def test_one_host_unexpected_error_does_not_stop_others(runner, three_hosts, monkeypatch):
    class BoomRunner:
        name = "boom"

        def run(self, script, *, timeout=120):
            match = re.search(r"'(@@BASTET[^']*@@)'", script)
            if match is None:
                return CommandResult("", "", 0)
            raise ValueError("disk on fire")

    class OkRunner:
        def __init__(self, name):
            self.name = name

        def run(self, script, *, timeout=120):
            match = re.search(r"'(@@BASTET[^']*@@)'", script)
            if match is None:
                return CommandResult("", "", 0)
            return CommandResult(stdout_for(dict(LAPTOP, hostname=self.name), match.group(1)), "", 0)

    def ssh_runner(target):
        if target.address == "203.0.113.11":
            return BoomRunner()
        return OkRunner(target.address)

    monkeypatch.setattr(gather_mod, "ssh_runner", ssh_runner)
    result = runner.invoke(app, ["run", "-g", "h1", "h2", "h3", "-y"])
    assert result.exit_code == 0, result.output
    assert "unexpected error: ValueError: disk on fire" in result.output
    assert "gathered:" not in facts(three_hosts, "h1")
    assert "os: Arch Linux" in facts(three_hosts, "h2")
    assert "os: Arch Linux" in facts(three_hosts, "h3")


def _seed(root: Path, suffix: str, monkeypatch, tmp_path) -> None:
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Tester")
    git(root, "config", "user.email", "tester@example.com")
    (root / "Homelab.md").write_text("---\nbastet: lab\n---\n# Homelab\n")
    (root / "hosts").mkdir()
    for i, name in enumerate(["h1", "h2", "h3"], start=1):
        (root / "hosts" / f"{name}.md").write_text(
            f"---\nbastet: host\ntype: vps\nprovider: linode\nip: 203.0.113.{10 + i}\n"
            f"ssh_host_key: {HOST_KEY}\n---\n# {name}\n"
        )
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "seed")
    cfg = root.parent / f"bastet{suffix}.yml"
    cfg.write_text(f"inventory:\n  path: {root}\n")
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / f"data{suffix}"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / f"run{suffix}"))


def _tree(root: Path) -> dict:
    """Every .md file under `root` (outside .git), keyed by its path relative to root."""
    return {
        str(p.relative_to(root)): p.read_text()
        for p in root.rglob("*.md")
        if ".git" not in p.relative_to(root).parts
    }


def test_dash_j_1_and_dash_j_3_give_identical_results(runner, tmp_path, monkeypatch):
    class FakeRunner:
        """Plain, non-blocking: used for the -j 1 run (chained waits would deadlock serially)."""

        def __init__(self, outputs, name):
            self.outputs, self.name = outputs, name

        def run(self, script, *, timeout=120):
            match = re.search(r"'(@@BASTET[^']*@@)'", script)
            if match is None:
                return CommandResult("", "", 0)
            return CommandResult(stdout_for(self.outputs, match.group(1)), "", 0)

    class ChainedRunner:
        """For -j 3: h3 finishes first and signals h2, h2 finishes and signals h1 -- completion
        order is the reverse of inventory order, so the equivalence only holds if phase 4 walks
        the inventory, not the completion order."""

        done3 = threading.Event()
        done2 = threading.Event()

        def __init__(self, outputs, name, address):
            self.outputs, self.name, self.address = outputs, name, address

        def run(self, script, *, timeout=120):
            match = re.search(r"'(@@BASTET[^']*@@)'", script)
            if match is None:
                return CommandResult("", "", 0)
            if self.address.endswith(".13"):
                result = CommandResult(stdout_for(self.outputs, match.group(1)), "", 0)
                ChainedRunner.done3.set()
                return result
            if self.address.endswith(".12"):
                assert ChainedRunner.done3.wait(timeout=1)
                result = CommandResult(stdout_for(self.outputs, match.group(1)), "", 0)
                ChainedRunner.done2.set()
                return result
            assert ChainedRunner.done2.wait(timeout=1)
            return CommandResult(stdout_for(self.outputs, match.group(1)), "", 0)

    monkeypatch.setattr(gather_mod, "scan_keys", lambda address, recorded=None, port=22: KEYS)
    monkeypatch.setattr(gather_mod, "_now", lambda: "2026-10-06T00:00:00Z")  # the facts note's `gathered:` stamp

    root_a = tmp_path / "A"
    _seed(root_a, "a", monkeypatch, tmp_path)
    monkeypatch.setattr(
        gather_mod, "ssh_runner",
        lambda target: FakeRunner(dict(LAPTOP, hostname=target.address), f"{target.user}@{target.address}"),
    )
    result_a = runner.invoke(app, ["run", "-g", "-y", "-j", "1"])
    assert result_a.exit_code == 0, result_a.output
    refresh_a = runner.invoke(app, ["refresh"])
    assert refresh_a.exit_code == 0, refresh_a.output

    root_b = tmp_path / "B"
    _seed(root_b, "b", monkeypatch, tmp_path)
    monkeypatch.setattr(
        gather_mod, "ssh_runner",
        lambda target: ChainedRunner(
            dict(LAPTOP, hostname=target.address), f"{target.user}@{target.address}", target.address
        ),
    )
    result_b = runner.invoke(app, ["run", "-g", "-y", "-j", "3"])
    assert result_b.exit_code == 0, result_b.output
    refresh_b = runner.invoke(app, ["refresh"])
    assert refresh_b.exit_code == 0, refresh_b.output

    assert _tree(root_a) == _tree(root_b)

    subject_a = git(root_a, "log", "-1", "--grep=^gather", "--format=%s").strip()
    subject_b = git(root_b, "log", "-1", "--grep=^gather", "--format=%s").strip()
    assert subject_a == subject_b and subject_a

    files_a = sorted(git(root_a, "log", "-1", "--grep=^gather", "--name-only", "--format=").split())
    files_b = sorted(git(root_b, "log", "-1", "--grep=^gather", "--name-only", "--format=").split())
    assert files_a == files_b and files_a


def test_ctrl_c_prints_interrupted_nothing_written_and_exits_nonzero(runner, three_hosts, monkeypatch):
    """A KeyboardInterrupt raised while gathering (e.g. the user hits Ctrl-C) must not escape as a
    bare traceback -- the command prints a message and exits non-zero, and nothing is written."""
    barrier = threading.Barrier(1, timeout=1)
    monkeypatch.setattr(
        gather_mod, "ssh_runner", lambda target: BlockingRunner(dict(LAPTOP, hostname=target.address), barrier)
    )

    count = {"n": 0}
    real_echo_outcome = gather_mod._echo_outcome

    def flaky_echo_outcome(outcome, done):
        count["n"] += 1
        if count["n"] == 1:
            raise KeyboardInterrupt
        return real_echo_outcome(outcome, done)

    monkeypatch.setattr(gather_mod, "_echo_outcome", flaky_echo_outcome)

    result = runner.invoke(app, ["run", "-g", "h1", "h2", "h3", "-y", "-j", "1"])

    assert result.exit_code == 1
    assert "interrupted; nothing written" in result.output
    for name in ("h1", "h2", "h3"):
        assert "os:" not in (three_hosts / "hosts" / f"{name}.md").read_text()
