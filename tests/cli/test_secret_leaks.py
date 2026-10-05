from pathlib import Path

import pytest

import bastet.cli.run as run_mod
from bastet.cli.app import app
from bastet.core.remote import LocalRunner
from bastet.core.secrets.redact import ACTIVE
from conftest import git


def test_tracebacks_never_show_locals():
    assert app.pretty_exceptions_show_locals is False


def test_top_level_errors_are_masked(capsys):
    import typer
    from bastet.cli.common import handles_errors
    from bastet.core.errors import BastetError

    ACTIVE.add("SENTINEL-9999")

    @handles_errors
    def boom():
        raise BastetError("command failed: echo SENTINEL-9999")

    with pytest.raises(typer.Exit):
        boom()
    err = capsys.readouterr().err
    assert "SENTINEL-9999" not in err and "‹secret›" in err


# --- m3: a few other places that print a message built from arbitrary text must mask it too ---


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


def test_security_note_write_failure_is_masked(runner, box, inventory, monkeypatch):
    SENTINEL = "SENTINEL-NOTE-7777"
    ACTIVE.add(SENTINEL)

    def boom(*a, **k):
        raise RuntimeError(f"disk full near {SENTINEL}")

    monkeypatch.setattr(run_mod, "security_note", boom)
    monkeypatch.setattr(run_mod, "security_items", lambda items: True)

    result = runner.invoke(app, ["check", "box"])

    assert result.exit_code == 0, result.output
    assert SENTINEL not in result.output
    assert "security note not written" in result.output
    assert "‹secret›" in result.output


def test_run_audit_warning_is_masked(runner, box, inventory, monkeypatch, secret_keys):
    from bastet.engine.run import HostRun

    SENTINEL = "SENTINEL-AUDIT-7777"
    ACTIVE.add(SENTINEL)

    def fake_run_audit(runner_, doc):
        return f"{doc.name}: lynis audit failed: token {SENTINEL}; the security note keeps the previous report"

    monkeypatch.setattr(run_mod, "run_audit", fake_run_audit)
    monkeypatch.setattr(run_mod, "run_host", lambda runner_, host, batches, **kw: HostRun(host, kw.get("apply", False), []))
    (inventory / "_roles" / "hosts" / "box" / "harden.md").write_text(
        '---\nbastet: role\nrole: harden\napplies_to: "[[box]]"\nlynis: true\nvulnerable_packages: false\n'
        'service_exposure: false\nlistening_ports: false\napparmor_status: false\nsysctl_defaults: false\n---\n')
    git(inventory, "add", ".")
    git(inventory, "commit", "-q", "-m", "harden")

    result = runner.invoke(app, ["apply", "box", "-y"])

    assert result.exit_code == 0, result.output
    assert SENTINEL not in result.output
    assert "‹secret›" in result.output


def test_handle_reboot_note_is_masked(runner, box, inventory, monkeypatch):
    SENTINEL = "SENTINEL-REBOOT-7777"
    ACTIVE.add(SENTINEL)
    monkeypatch.setattr(run_mod, "handle_reboot", lambda *a, **k: f"box: rebooted with token {SENTINEL}")

    result = runner.invoke(app, ["apply", "box", "-y"])

    assert result.exit_code == 0, result.output
    assert SENTINEL not in result.output
    assert "‹secret›" in result.output
