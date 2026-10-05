import os
import subprocess
from pathlib import Path

import pytest

import bastet.cli.run as run_mod
from bastet.cli.app import app
from bastet.core.errors import BastetError, Unreachable
from bastet.core.remote import LocalRunner
from bastet.core.secrets import crypto
from bastet.core.secrets.notes import SecretNote, SecretPath
from conftest import git


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
    result = runner.invoke(app, ["check", "box"])
    assert result.exit_code == 0, result.output
    assert "HOST: box" in result.output and "(absent) → create" in result.output and "1 to change" in result.output
    assert not (box / "motd").exists()


def test_apply_yes_then_check_is_clean(runner, box):
    result = runner.invoke(app, ["apply", "box", "-y"])
    assert result.exit_code == 0, result.output
    assert (box / "motd").read_text() == "hi\n" and "1 changed" in result.output
    again = runner.invoke(app, ["check", "box"])
    assert "✓ compliant" in again.output and "0 to change" in again.output


def test_apply_asks_and_respects_no(runner, box):
    result = runner.invoke(app, ["apply", "box"], input="n\n")
    assert result.exit_code == 0 and "nothing applied" in result.output and not (box / "motd").exists()


def test_role_error_exit_1(runner, box, inventory):
    (inventory / "_roles" / "hosts" / "box" / "files.md").write_text(
        '---\nbastet: role\nrole: files\napplies_to: "[[box]]"\nfile:\n  /x: {}\n---\n')
    result = runner.invoke(app, ["check", "box"])
    assert result.exit_code == 1 and "files has no option 'file'" in result.output


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
    result = runner.invoke(app, ["apply", "box", "box2", "-y"])
    assert result.exit_code == 1 and "nothing answered" in result.output and (box / "two").read_text() == "2"


def test_host_without_roles(runner, inventory, monkeypatch):
    (inventory / "hosts" / "plain.md").write_text("---\nbastet: host\ntype: laptop\nconnection: local\n---\n# plain\n")
    monkeypatch.setattr(run_mod, "connect", lambda ctx, doc, tmp, yes: (AsRootLocally(), None))
    result = runner.invoke(app, ["check", "plain"])
    assert result.exit_code == 0 and "plain: no roles" in result.output


def test_connect_requires_gathered_key(inventory):
    from bastet.cli.common import load_context
    ctx = load_context()
    doc = ctx.inventory.get("pve1")
    with pytest.raises(BastetError) as e:
        run_mod.connect(ctx, doc, inventory, yes=True)
    assert "gather" in str(e.value)


def test_roles_named_and_empty_role_explained(runner, box, inventory):
    result = runner.invoke(app, ["check", "box"])
    assert "roles: files (host box)" in result.output
    (inventory / "_roles" / "hosts" / "box" / "files.md").write_text(
        '---\nbastet: role\nrole: files\napplies_to: "[[box]]"\n---\n')
    result = runner.invoke(app, ["check", "box"])
    assert "box: files (host box): nothing to manage yet" in result.output and "no roles" not in result.output


def test_options_in_page_text_warned(runner, box, inventory):
    f = inventory / "_roles" / "hosts" / "box" / "files.md"
    f.write_text(f.read_text() + "# files for box\n\nlinks:\n  /a: /b\n")
    result = runner.invoke(app, ["check", "box"])
    assert "links:" in result.output and "page text" in result.output


def test_apply_updates_flag_reaches_roles(runner, box, monkeypatch):
    seen = {}
    real = run_mod.host_info

    def spy(ctx, doc, updates=False):
        seen["updates"] = updates
        return real(ctx, doc, updates=updates)

    monkeypatch.setattr(run_mod, "host_info", spy)
    runner.invoke(app, ["apply", "box", "--updates", "-y"])
    assert seen["updates"] is True


def test_role_file_pointing_nowhere_is_reported(runner, box, inventory):
    (inventory / "_roles" / "hosts" / "box" / "stray.md").write_text(
        '---\nbastet: role\nrole: packages\napplies_to: "[[web-servrs]]"\n---\n')
    result = runner.invoke(app, ["check", "box"])
    assert "web-servrs" in result.output and "stray.md" in result.output


def test_unifi_devices_are_not_role_managed(runner, box, inventory, monkeypatch):
    (inventory / "hosts" / "ap1.md").write_text("---\nbastet: host\ntype: unifi-ap\nip: 10.10.0.3\n---\n# ap1\n")
    lab = inventory / "_roles" / "lab"
    lab.mkdir(parents=True)
    (lab / "systemd.md").write_text('---\nbastet: role\nrole: systemd\napplies_to: "[[Homelab]]"\ntimezone: UTC\n---\n')

    def connect(ctx, doc, tmp, yes):
        assert doc.name != "ap1", "UniFi devices must not be connected to by check"
        return AsRootLocally(), None

    monkeypatch.setattr(run_mod, "connect", connect)
    result = runner.invoke(app, ["check", "ap1", "box"])
    assert "ap1: configured through the UniFi controller" in result.output


def _no_updates(real):
    from bastet.engine.packages import Reboot, Updates

    def run(runner, host, batches, **kw):
        for b in batches:
            b.resources = [r for r in b.resources if not isinstance(r, (Updates, Reboot))]
        return real(runner, host, batches, **kw)
    return run


def test_apply_reports_reboot_on_local_host(runner, box, inventory, monkeypatch):
    import bastet.cli.reboot as reboot_mod
    (inventory / "_roles" / "hosts" / "box" / "packages.md").write_text(
        '---\nbastet: role\nrole: packages\napplies_to: "[[box]]"\nreboot: auto\nreport_unaccounted: false\n---\n')
    monkeypatch.setattr(reboot_mod, "reboot_needed", lambda runner, host, reboots: (True, "kernel"))
    monkeypatch.setattr(run_mod, "run_host", _no_updates(run_mod.run_host))
    result = runner.invoke(app, ["apply", "box", "-y"])
    assert "box: reboot needed (kernel); reboot this machine yourself" in result.output


def test_check_never_reboots(runner, box, inventory, monkeypatch):
    import bastet.cli.run as rm

    def boom(*a, **k):
        raise AssertionError("check must not reach the reboot step")
    monkeypatch.setattr(rm, "handle_reboot", boom)
    (inventory / "_roles" / "hosts" / "box" / "packages.md").write_text(
        '---\nbastet: role\nrole: packages\napplies_to: "[[box]]"\nreboot: auto\nreport_unaccounted: false\n---\n')
    monkeypatch.setattr(run_mod, "run_host", _no_updates(run_mod.run_host))
    assert runner.invoke(app, ["check", "box"]).exit_code == 0


def test_failed_apply_tells_reboot_step(runner, box, inventory, monkeypatch):
    import bastet.cli.run as rm
    seen = {}

    def spy(runner_, target, doc, reboots, *, yes, connect_again, apply_failed=False):
        seen["failed"] = apply_failed
        return None
    monkeypatch.setattr(rm, "handle_reboot", spy)
    (inventory / "_roles" / "hosts" / "box" / "files.md").write_text(
        '---\nbastet: role\nrole: files\napplies_to: "[[box]]"\nfiles:\n  /proc/bastet-cannot-write:\n    content: "x"\n---\n')
    (inventory / "_roles" / "hosts" / "box" / "packages.md").write_text(
        '---\nbastet: role\nrole: packages\napplies_to: "[[box]]"\nreboot: auto\nreport_unaccounted: false\n---\n')
    monkeypatch.setattr(run_mod, "run_host", _no_updates(run_mod.run_host))
    runner.invoke(app, ["apply", "box", "-y"])
    assert seen == {"failed": True}


def test_apply_runs_lynis_check_does_not(runner, box, inventory, monkeypatch):
    from bastet.engine.run import HostRun
    calls = []
    monkeypatch.setattr(run_mod, "run_audit", lambda runner_, doc: calls.append(doc.name) or None)
    monkeypatch.setattr(run_mod, "run_host", lambda runner_, host, batches, **kw: HostRun(host, kw.get("apply", False), []))
    (inventory / "_roles" / "hosts" / "box" / "harden.md").write_text(
        '---\nbastet: role\nrole: harden\napplies_to: "[[box]]"\nlynis: true\nvulnerable_packages: false\n'
        'service_exposure: false\nlistening_ports: false\napparmor_status: false\nsysctl_defaults: false\n---\n')
    assert runner.invoke(app, ["check", "box"]).exit_code == 0 and calls == []
    result = runner.invoke(app, ["apply", "box", "-y"])
    assert result.exit_code == 0, result.output
    assert calls == ["box"]


def test_failed_audit_is_a_warning_not_a_failure(runner, box, inventory, monkeypatch):
    from bastet.core.remote import CommandResult
    from bastet.engine.run import HostRun

    class Fails:
        def run(self, script, *, timeout=120):
            return CommandResult("", "lynis: command not found", 127)
    monkeypatch.setattr(run_mod, "connect", lambda ctx, doc, tmp, yes: (Fails(), None))
    monkeypatch.setattr(run_mod, "run_host", lambda runner_, host, batches, **kw: HostRun(host, kw.get("apply", False), []))
    (inventory / "_roles" / "hosts" / "box" / "harden.md").write_text(
        '---\nbastet: role\nrole: harden\napplies_to: "[[box]]"\nlynis: true\nvulnerable_packages: false\n'
        'service_exposure: false\nlistening_ports: false\napparmor_status: false\nsysctl_defaults: false\n---\n')
    result = runner.invoke(app, ["apply", "box", "-y"])
    assert result.exit_code == 0 and "lynis audit failed" in result.output


def test_check_writes_security_note(runner, box, inventory, monkeypatch):
    from bastet.engine.run import HostRun, Item
    from bastet.engine.security import AppArmorStatus

    def fake(runner_, host, batches, **kw):
        res = next(r for b in batches for r in b.resources if isinstance(r, AppArmorStatus))
        return HostRun(host, False, [Item(res, ["harden"], [], current={"enabled": False, "enforce": 0, "complain": 0})])
    monkeypatch.setattr(run_mod, "run_host", fake)
    (inventory / "_roles" / "hosts" / "box" / "harden.md").write_text(
        '---\nbastet: role\nrole: harden\napplies_to: "[[box]]"\nvulnerable_packages: false\n'
        'service_exposure: false\nlistening_ports: false\nsysctl_defaults: false\n---\n')
    result = runner.invoke(app, ["check", "box"])
    assert result.exit_code == 0, result.output
    note = inventory / "_bastet" / "security" / "box security.md"
    assert note.exists() and "## AppArmor\n\nnot enabled" in note.read_text()
    assert "refresh: security note box" in git(inventory, "log", "--format=%s")


def test_security_note_not_recommitted_when_only_time_changes(runner, box, inventory, monkeypatch):
    from bastet.engine.run import HostRun, Item
    from bastet.engine.security import AppArmorStatus

    def fake(runner_, host, batches, **kw):
        res = next(r for b in batches for r in b.resources if isinstance(r, AppArmorStatus))
        return HostRun(host, False, [Item(res, ["harden"], [], current={"enabled": False, "enforce": None, "complain": None})])
    monkeypatch.setattr(run_mod, "run_host", fake)
    (inventory / "_roles" / "hosts" / "box" / "harden.md").write_text(
        '---\nbastet: role\nrole: harden\napplies_to: "[[box]]"\nvulnerable_packages: false\n'
        'service_exposure: false\nlistening_ports: false\nsysctl_defaults: false\n---\n')
    import datetime as real_dt
    import types
    times = iter([real_dt.datetime(2026, 10, 2, 10, 0), real_dt.datetime(2026, 10, 2, 11, 30)])
    monkeypatch.setattr(run_mod, "dt", types.SimpleNamespace(datetime=types.SimpleNamespace(now=lambda: next(times))))
    runner.invoke(app, ["check", "box"])
    first = git(inventory, "log", "--format=%s").count("security note box")
    runner.invoke(app, ["check", "box"])
    assert first == 1 and git(inventory, "log", "--format=%s").count("security note box") == 1


def test_security_note_failure_never_stops_the_check(runner, box, inventory, monkeypatch):
    from bastet.engine.run import HostRun, Item
    from bastet.engine.security import AppArmorStatus
    import bastet.cli.run as rm

    def fake(runner_, host, batches, **kw):
        res = next(r for b in batches for r in b.resources if isinstance(r, AppArmorStatus))
        return HostRun(host, False, [Item(res, ["harden"], [], current={"enabled": False, "enforce": None, "complain": None})])
    monkeypatch.setattr(run_mod, "run_host", fake)
    monkeypatch.setattr(rm, "security_note", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    (inventory / "_roles" / "hosts" / "box" / "harden.md").write_text(
        '---\nbastet: role\nrole: harden\napplies_to: "[[box]]"\nvulnerable_packages: false\n'
        'service_exposure: false\nlistening_ports: false\nsysctl_defaults: false\n---\n')
    result = runner.invoke(app, ["check", "box"])
    assert result.exit_code == 0 and "security note not written" in result.output


def test_secret_reference_is_resolved_and_redacted(runner, box, inventory):
    key_path = inventory.parent / "bastet_key"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key_path)], check=True)
    pub = (inventory.parent / "bastet_key.pub").read_text().strip()

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

    # `content:` is marked secret automatically (engine/model.py hides it); `links:` has no such field at
    # all, so a plaintext target can only be kept out of the report by the redactor backstop.
    (inventory / "_roles" / "hosts" / "box" / "files.md").write_text(
        f'---\nbastet: role\nrole: files\napplies_to: "[[box]]"\nfiles:\n  {box}/motd:\n    content: "secret:motd"\n'
        f'links:\n  {box}/motdlink: "secret:link_target"\n---\n')

    result = runner.invoke(app, ["check", "box"])
    assert result.exit_code == 0, result.output
    assert "SENTINEL-4242" not in result.output
    assert not (box / "motd").exists()

    applied = runner.invoke(app, ["apply", "box", "-y"])
    assert applied.exit_code == 0, applied.output
    assert "SENTINEL-4242" not in applied.output
    assert (box / "motd").read_text() == "SENTINEL-4242"
    assert (box / "motdlink").is_symlink()

    log = git(inventory, "log", "-p")
    assert "SENTINEL-4242" not in log


def test_missing_secret_fails_that_host_and_continues(runner, box, inventory):
    (inventory / "_roles" / "hosts" / "box" / "files.md").write_text(
        f'---\nbastet: role\nrole: files\napplies_to: "[[box]]"\nfiles:\n  {box}/motd:\n    content: "secret:motd"\n---\n')
    result = runner.invoke(app, ["check", "box"])
    assert result.exit_code == 1
    assert "missing secret box/files/motd (bastet secret set box files motd)" in result.output


# --- generation at apply, and asking for non-generatable ones (spec 15.3, 15.5; plan task 5) ---


def test_check_reports_would_generate_missing_secret(runner, secret_keys, inventory, box, test_role):
    result = runner.invoke(app, ["check", "box"])
    assert result.exit_code == 0, result.output
    assert "would generate box/testsecret/" in result.output
    assert not (inventory / "_secrets" / "box" / "testsecret" / "admin_password.md").exists()
    assert not (inventory / "_secrets" / "box" / "testsecret" / "db_password.md").exists()


def test_apply_generates_all_missing_before_any_run_host(runner, secret_keys, inventory, box, test_role, monkeypatch):
    real_run_host = run_mod.run_host
    log_at_first_call = []

    def recording(runner_, host, batches, **kw):
        if not log_at_first_call:
            log_at_first_call.append(git(inventory, "log", "-1", "--format=%s"))
        return real_run_host(runner_, host, batches, **kw)

    monkeypatch.setattr(run_mod, "run_host", recording)
    before = git(inventory, "log", "--format=%H").strip().splitlines()

    result = runner.invoke(app, ["apply", "box", "-y"])
    assert result.exit_code == 0, result.output

    after = git(inventory, "log", "--format=%H").strip().splitlines()
    assert len(after) > len(before)  # at least the one generation commit (plus `refresh_generated`'s own)
    commit_messages = git(inventory, "log", "--format=%s", f"{before[0]}..HEAD")
    assert "secret: generate 2 secrets" in commit_messages
    assert "box/testsecret/admin_password" in commit_messages
    assert "box/testsecret/db_password" in commit_messages

    admin = SecretNote.load(inventory, SecretPath.parse("box/testsecret/admin_password"))
    db = SecretNote.load(inventory, SecretPath.parse("box/testsecret/db_password"))
    assert admin.is_sealed and db.is_sealed

    # generation and its single commit happened before run_host ever touched a host
    assert log_at_first_call and "secret: generate" in log_at_first_call[0]


def test_apply_asks_for_nongenerated_missing_secret_when_interactive(runner, secret_keys, inventory, box, test_role, interactive):
    roles = inventory / "_roles" / "hosts" / "box"
    (roles / "impliedsecret.md").write_text('---\nbastet: role\nrole: impliedsecret\napplies_to: "[[box]]"\n---\n')
    git(inventory, "add", ".")
    git(inventory, "commit", "-q", "-m", "implied")

    result = runner.invoke(app, ["apply", "box"], input="SENTINEL-API\nSENTINEL-API\ny\n")
    assert result.exit_code == 0, result.output
    assert "SENTINEL-API" not in result.output
    assert "Enter value, or e to fill it in yourself" in result.output

    note = SecretNote.load(inventory, SecretPath.parse("box/impliedsecret/api_key"))
    assert note.is_sealed
    assert (box / "motd").read_text() == "hi\n"


def test_apply_yes_fails_host_for_nongenerated_missing_secret(runner, secret_keys, inventory, box, test_role):
    roles = inventory / "_roles" / "hosts" / "box"
    (roles / "impliedsecret.md").write_text('---\nbastet: role\nrole: impliedsecret\napplies_to: "[[box]]"\n---\n')
    git(inventory, "add", ".")
    git(inventory, "commit", "-q", "-m", "implied")

    result = runner.invoke(app, ["apply", "box", "-y"])
    assert result.exit_code == 1
    assert "missing secret box/impliedsecret/api_key (bastet secret set box impliedsecret api_key)" in result.output

    # the generatable secrets were still generated, even though this host ultimately failed
    admin = SecretNote.load(inventory, SecretPath.parse("box/testsecret/admin_password"))
    assert admin.is_sealed
