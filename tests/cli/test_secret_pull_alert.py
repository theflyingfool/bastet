import subprocess
from pathlib import Path

import pytest

import bastet.cli.run as run_mod
from bastet.cli.app import app
from bastet.core.remote import LocalRunner
from bastet.core.secrets import crypto
from bastet.core.secrets.notes import SecretNote, SecretPath
from conftest import git


class AsRootLocally(LocalRunner):
    def run(self, script, *, timeout=120):
        return super().run(script.replace('if [ "$(id -u)" = 0 ]; then SUDO=""', 'if true; then SUDO=""'), timeout=timeout)


@pytest.fixture
def box(inventory, monkeypatch, tmp_path) -> Path:
    out = tmp_path / "out"
    (inventory / "hosts" / "box.md").write_text(
        "---\nbastet: host\ntype: laptop\nconnection: local\nhostname: box\n---\n# box\n"
    )
    roles = inventory / "_roles" / "hosts" / "box"
    roles.mkdir(parents=True)
    (roles / "files.md").write_text(
        f'---\nbastet: role\nrole: files\napplies_to: "[[box]]"\nfiles:\n  {out}/motd:\n    content: "hi\\n"\n---\n')
    git(inventory, "add", ".")
    git(inventory, "commit", "-q", "-m", "box")
    monkeypatch.setattr(run_mod, "connect", lambda ctx, doc, tmp, yes: (AsRootLocally(), None))
    return out


@pytest.fixture
def remote(inventory, secret_keys, tmp_path) -> Path:
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    git(inventory, "remote", "add", "origin", str(bare))
    git(inventory, "push", "-q", "-u", "origin", "main")
    return bare


def _push_secret_change(remote: Path, tmp_path: Path, pub: str, *, author: str = "Alice", email: str = "admin@laptop") -> None:
    other = tmp_path / "other-clone"
    subprocess.run(["git", "clone", "-q", str(remote), str(other)], check=True)
    git(other, "config", "user.name", author)
    git(other, "config", "user.email", email)
    sp = SecretPath.parse("lab/dns_token")
    note = SecretNote.new(sp, source="chosen", created="2026-10-03T00:00", applies_to="lab")
    note.body = crypto.seal(sp.text, "v", [pub])
    note.write(other)
    git(other, "add", ".")
    git(other, "commit", "-q", "-m", "secret: set lab/dns_token")
    git(other, "push", "-q")


def test_check_prints_pull_alert_for_changed_secrets(runner, inventory, secret_keys, remote, tmp_path):
    _push_secret_change(remote, tmp_path, secret_keys["pub"])
    result = runner.invoke(app, ["run", "-c"])
    assert "ALERT" in result.output
    assert "_secrets/lab/dns_token.md" in result.output
    assert "Alice" in result.output and "laptop" in result.output


def test_apply_yes_with_changed_secret_and_no_terminal_stops_everything(
    runner, box, inventory, secret_keys, test_role, remote, tmp_path, monkeypatch
):
    def boom(*a, **k):
        raise AssertionError("run_host must not be called when the run is stopped")

    monkeypatch.setattr(run_mod, "run_host", boom)
    _push_secret_change(remote, tmp_path, secret_keys["pub"])

    result = runner.invoke(app, ["run", "box", "-y"])
    assert result.exit_code == 1
    assert "ALERT" in result.output
    assert not (box / "motd").exists()
    assert "secret: generate" not in git(inventory, "log", "--format=%s")


def test_apply_with_changed_secret_interactive_yes_proceeds(
    runner, box, inventory, secret_keys, remote, tmp_path, interactive, monkeypatch
):
    monkeypatch.setattr(run_mod, "_wait_answer", lambda prompt, timeout: "y\n")
    _push_secret_change(remote, tmp_path, secret_keys["pub"])

    result = runner.invoke(app, ["run", "box", "-y"])
    assert result.exit_code == 0, result.output
    assert (box / "motd").read_text() == "hi\n"
