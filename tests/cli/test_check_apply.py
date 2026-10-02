import pytest

import bastet.cli.run as run_mod
from bastet.cli.app import app
from bastet.core.errors import BastetError, Unreachable
from bastet.core.remote import LocalRunner
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
