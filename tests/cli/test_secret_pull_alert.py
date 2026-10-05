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


def _push_secret_change(remote: Path, tmp_path: Path, pub: str, *, author: str = "Nick", email: str = "nick@laptop") -> None:
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
    result = runner.invoke(app, ["check"])
    assert "ALERT" in result.output
    assert "_secrets/lab/dns_token.md" in result.output
    assert "Nick" in result.output and "laptop" in result.output


def test_apply_yes_with_changed_secret_and_no_terminal_stops_everything(
    runner, box, inventory, secret_keys, test_role, remote, tmp_path, monkeypatch
):
    def boom(*a, **k):
        raise AssertionError("run_host must not be called when the run is stopped")

    monkeypatch.setattr(run_mod, "run_host", boom)
    _push_secret_change(remote, tmp_path, secret_keys["pub"])

    result = runner.invoke(app, ["apply", "box", "-y"])
    assert result.exit_code == 1
    assert "ALERT" in result.output
    assert not (box / "motd").exists()
    assert "Generated" not in result.output  # _prepare_secrets never ran either
    assert "secret: generate" not in git(inventory, "log", "--format=%s")


def test_apply_with_changed_secret_interactive_yes_proceeds(
    runner, box, inventory, secret_keys, remote, tmp_path, interactive, monkeypatch
):
    monkeypatch.setattr(run_mod, "_wait_answer", lambda prompt, timeout: "y\n")
    _push_secret_change(remote, tmp_path, secret_keys["pub"])

    result = runner.invoke(app, ["apply", "box", "-y"])
    assert result.exit_code == 0, result.output
    assert (box / "motd").read_text() == "hi\n"


def test_apply_with_changed_secret_no_answer_stops(
    runner, box, inventory, secret_keys, remote, tmp_path, interactive, monkeypatch
):
    monkeypatch.setattr(run_mod, "_wait_answer", lambda prompt, timeout: None)
    _push_secret_change(remote, tmp_path, secret_keys["pub"])

    result = runner.invoke(app, ["apply", "box", "-y"])
    assert result.exit_code == 1
    assert not (box / "motd").exists()


def test_check_alert_then_carries_on(runner, box, inventory, secret_keys, remote, tmp_path):
    _push_secret_change(remote, tmp_path, secret_keys["pub"])
    result = runner.invoke(app, ["check", "box"])
    assert result.exit_code == 0, result.output
    assert "ALERT" in result.output
    assert "HOST: box" in result.output  # the check still ran


def test_change_pulled_by_check_still_stops_a_later_apply(
    runner, box, inventory, secret_keys, test_role, remote, tmp_path, monkeypatch
):
    def boom(*a, **k):
        raise AssertionError("run_host must not be called before the change is confirmed")

    _push_secret_change(remote, tmp_path, secret_keys["pub"])
    first = runner.invoke(app, ["check", "box"])
    assert "ALERT" in first.output
    monkeypatch.setattr(run_mod, "run_host", boom)
    result = runner.invoke(app, ["apply", "box", "-y"])  # nothing new to pull now; the change is still unconfirmed
    assert result.exit_code == 1 and "ALERT" in result.output


def test_confirmed_change_stops_alerting(
    runner, box, inventory, secret_keys, remote, tmp_path, interactive, monkeypatch
):
    monkeypatch.setattr(run_mod, "_wait_answer", lambda prompt, timeout: "y\n")
    _push_secret_change(remote, tmp_path, secret_keys["pub"])
    assert runner.invoke(app, ["apply", "box", "-y"]).exit_code == 0
    again = runner.invoke(app, ["check", "box"])
    assert "ALERT" not in again.output


# --- C3: the gate must catch a secret change however it reached this machine, not just a pull one
# of Bastet's own commands just did ---


def test_secret_set_walk_squash_does_not_swallow_a_pending_upstream_change(
    runner, box, inventory, secret_keys, test_role, remote, tmp_path, interactive
):
    """`secret set`'s walk mode can make several commits and squash them into one. The squash must
    not advance the confirmed baseline past an upstream change that was already pending before the
    walk started (even though every commit the walk itself made is Bastet's own)."""
    from bastet.core.gitrepo import GitRepo
    from bastet.core.secrets import confirm

    assert runner.invoke(app, ["check", "box"]).exit_code == 0  # establish the baseline
    _push_secret_change(remote, tmp_path, secret_keys["pub"])

    result = runner.invoke(app, ["secret", "set"], input="0\n\n\n")  # all, generate both -> 2 commits, squashed
    assert result.exit_code == 0, result.output
    assert "secret: set 2 secrets" in git(inventory, "log", "-1", "--format=%s")

    gr = GitRepo(inventory)
    assert "_secrets/lab/dns_token.md" in confirm.changed_since_confirmed(gr, inventory)


def test_a_secret_change_pulled_by_a_plain_git_pull_still_gates_the_next_apply(
    runner, box, inventory, secret_keys, test_role, remote, tmp_path, monkeypatch
):
    """A secret change that arrives via a manual `git pull` (not `bastet check`/`apply`, not
    `secret set`'s quiet pull, not `bastet refresh`) must still stop the next `apply -y` with no
    terminal attached -- no host run -- exactly as if Bastet's own pull had seen it."""
    calls: list[str] = []
    real_run_host = run_mod.run_host

    def tracking_run_host(*a, **k):
        calls.append("called")
        return real_run_host(*a, **k)

    monkeypatch.setattr(run_mod, "run_host", tracking_run_host)

    # Establish a confirmed baseline the way a real inventory would: some Bastet command ran here
    # before the upstream change ever existed.
    assert runner.invoke(app, ["check", "box"]).exit_code == 0

    _push_secret_change(remote, tmp_path, secret_keys["pub"])
    git(inventory, "pull", "-q", "--ff-only")  # not through Bastet at all

    result = runner.invoke(app, ["apply", "box", "-y"])

    assert result.exit_code == 1
    assert "ALERT" in result.output
    assert calls == []
    assert not (box / "motd").exists()
