import os
from pathlib import Path

import pytest

import bastet.cli.run as run_mod
from bastet.cli.app import app
from bastet.core.errors import Unreachable
from bastet.core.remote import LocalRunner
from bastet.core.secrets import crypto
from bastet.core.secrets.notes import SecretNote, SecretPath
from conftest import STATIC_PRIVATE_KEY, STATIC_PUBLIC_KEY, git


class AsRootLocally(LocalRunner):
    """Runs scripts as the current user, as if it were root, so role files can target temp paths."""

    def run(self, script, *, timeout=120):
        return super().run(script.replace('if [ "$(id -u)" = 0 ]; then SUDO=""', 'if true; then SUDO=""'), timeout=timeout)


@pytest.fixture
def box(inventory, monkeypatch, tmp_path):
    out = tmp_path / "out"
    (inventory / "hosts" / "box.md").write_text("---\nbastet: host\ntype: laptop\nconnection: local\nhostname: box\n---\n# box\n")
    roles = inventory / "_roles" / "hosts" / "box"
    roles.mkdir(parents=True)
    (roles / "files.md").write_text(
        f'---\nbastet: role\nrole: files\napplies_to: "[[box]]"\nfiles:\n  {out}/motd:\n    content: "hi\\n"\n---\n')
    git(inventory, "add", ".")
    git(inventory, "commit", "-q", "-m", "box")
    monkeypatch.setattr(run_mod, "connect", lambda ctx, doc, tmp, yes: (AsRootLocally(), None))
    return out


def test_check_reports_and_changes_nothing(runner, box):
    result = runner.invoke(app, ["run", "-c", "box"])
    assert result.exit_code == 0, result.output
    assert "HOST: box" in result.output and "(absent) → create" in result.output and "1 to change" in result.output
    assert not (box / "motd").exists()


def test_apply_yes_then_check_is_clean(runner, box):
    result = runner.invoke(app, ["run", "box", "-y"])
    assert result.exit_code == 0, result.output
    assert (box / "motd").read_text() == "hi\n" and "1 changed" in result.output
    again = runner.invoke(app, ["run", "-c", "box"])
    assert "✓ compliant" in again.output and "0 to change" in again.output


def test_apply_asks_and_respects_no(runner, box):
    result = runner.invoke(app, ["run", "box"], input="n\n")
    assert result.exit_code == 0 and "nothing applied" in result.output and not (box / "motd").exists()


def test_unreachable_host_reported_and_others_continue(runner, box, inventory, monkeypatch):
    (inventory / "hosts" / "box2.md").write_text("---\nbastet: host\ntype: laptop\nconnection: local\n---\n# box2\n")
    other = inventory / "_roles" / "hosts" / "box2"
    other.mkdir(parents=True)
    (other / "files.md").write_text(f'---\nbastet: role\nrole: files\napplies_to: "[[box2]]"\nfiles:\n  {box}/two:\n    content: "2"\n---\n')

    def connect(ctx, doc, tmp, yes):
        if doc.name == "box":
            raise Unreachable("box: nothing answered on port 22")
        return AsRootLocally(), None

    monkeypatch.setattr(run_mod, "connect", connect)
    result = runner.invoke(app, ["run", "box", "box2", "-y"])
    assert result.exit_code == 1 and "nothing answered" in result.output and (box / "two").read_text() == "2"


@pytest.mark.parametrize(("host", "host_type", "managed_by"), [
    ("ap1", "unifi-ap", "the UniFi controller"),
    ("tv", "other", "nothing (shown on maps only)"),
])
def test_unmanaged_types_are_not_role_managed(runner, box, inventory, monkeypatch, host, host_type, managed_by):
    (inventory / "hosts" / f"{host}.md").write_text(f"---\nbastet: host\ntype: {host_type}\nip: 10.10.0.3\n---\n# {host}\n")
    lab = inventory / "_roles" / "lab"
    lab.mkdir(parents=True)
    (lab / "systemd.md").write_text('---\nbastet: role\nrole: systemd\napplies_to: "[[Homelab]]"\ntimezone: UTC\n---\n')

    def connect(ctx, doc, tmp, yes):
        assert doc.name != host, f"{host_type} hosts must not be connected to by check"
        return AsRootLocally(), None

    monkeypatch.setattr(run_mod, "connect", connect)
    result = runner.invoke(app, ["run", "-c", host, "box"])
    assert f"{host}: configured through {managed_by}; not managed by Bastet" in result.output


def test_role_error_exit_1(runner, box, inventory):
    (inventory / "_roles" / "hosts" / "box" / "files.md").write_text(
        '---\nbastet: role\nrole: files\napplies_to: "[[box]]"\nfile:\n  /x: {}\n---\n')
    result = runner.invoke(app, ["run", "-c", "box"])
    assert result.exit_code == 1 and "files has no option 'file'" in result.output


def test_secret_reference_is_resolved_and_redacted(runner, box, inventory):
    key_path = inventory.parent / "bastet_key"
    key_path.write_text(STATIC_PRIVATE_KEY)
    key_path.chmod(0o600)
    (inventory.parent / "bastet_key.pub").write_text(STATIC_PUBLIC_KEY + "\n")
    pub = STATIC_PUBLIC_KEY

    cfg_path = Path(os.environ["BASTET_CONFIG"])
    cfg_path.write_text(cfg_path.read_text() + f"ssh:\n  key: {key_path}\n")

    homelab = inventory / "Homelab.md"
    homelab.write_text(homelab.read_text().replace("networks:", f"secrets:\n  recipients:\n    - {pub}\nnetworks:"))

    for name in ("motd", "link_target"):
        sp = SecretPath.parse(f"box/files/{name}")
        note = SecretNote.new(sp, source="chosen", created="2026-10-03T00:00", applies_to="box")
        note.body = crypto.seal(sp.text, "SENTINEL-4242", [pub])
        note.write(inventory)
    git(inventory, "add", ".")
    git(inventory, "commit", "-q", "-m", "seed secret")

    (inventory / "_roles" / "hosts" / "box" / "files.md").write_text(
        f'---\nbastet: role\nrole: files\napplies_to: "[[box]]"\nfiles:\n  {box}/motd:\n    content: "secret:motd"\n'
        f'links:\n  {box}/motdlink: "secret:link_target"\n---\n')

    result = runner.invoke(app, ["run", "-c", "box"])
    assert result.exit_code == 0, result.output
    assert "SENTINEL-4242" not in result.output
    assert not (box / "motd").exists()

    applied = runner.invoke(app, ["run", "box", "-y"])
    assert applied.exit_code == 0, applied.output
    assert "SENTINEL-4242" not in applied.output
    assert (box / "motd").read_text() == "SENTINEL-4242"
    assert (box / "motdlink").is_symlink()

    log = git(inventory, "log", "-p")
    assert "SENTINEL-4242" not in log
