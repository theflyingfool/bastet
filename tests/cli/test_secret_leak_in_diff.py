"""C2: a multi-line secret used inside a non-secret option (systemd.dropins content) must never
appear in check/apply output -- neither the old value on the host nor the new one from the note,
whole or split across lines by a diff."""

from pathlib import Path

import pytest

from bastet.cli.app import app
from bastet.core.remote import LocalRunner
from bastet.core.secrets import crypto
from bastet.core.secrets.notes import SecretNote, SecretPath
from conftest import git

OLD_VALUE = "[Service]\nEnvironment=DB_PASS=Hunter2-OLD\n"
NEW_VALUE = "[Service]\nEnvironment=DB_PASS=Hunter2-NEW\n"
DROPIN_REL = "etc/systemd/system/gitea.service.d/env.conf"


class SystemdUnderTmp(LocalRunner):
    """Runs locally as if root, and redirects the fixed /etc/systemd/system/ path this role writes
    under into a tmp dir, so the test never touches the real filesystem."""

    def __init__(self, tmp: Path) -> None:
        super().__init__()
        self.tmp = tmp

    def run(self, script, *, timeout=120):
        script = script.replace('if [ "$(id -u)" = 0 ]; then SUDO=""', 'if true; then SUDO=""')
        script = script.replace("/etc/systemd/system/", f"{self.tmp}/etc/systemd/system/")
        return super().run(script, timeout=timeout)


@pytest.fixture
def box_with_secret_dropin(inventory, secret_keys, monkeypatch, tmp_path) -> Path:
    (inventory / "hosts" / "box.md").write_text(
        "---\nbastet: host\ntype: laptop\nconnection: local\nhostname: box\n---\n# box\n"
    )
    roles = inventory / "_roles" / "hosts" / "box"
    roles.mkdir(parents=True)
    (roles / "systemd.md").write_text(
        '---\nbastet: role\nrole: systemd\napplies_to: "[[box]]"\n'
        "dropins:\n"
        "  - unit: gitea.service\n"
        "    name: env\n"
        '    content: "secret:gitea_env"\n'
        "---\n"
    )
    sp = SecretPath.parse("box/systemd/gitea_env")
    note = SecretNote.new(sp, source="chosen", created="2026-10-03T00:00", applies_to="box")
    note.body = crypto.seal(sp.text, NEW_VALUE, [secret_keys["pub"]])
    note.write(inventory)
    git(inventory, "add", ".")
    git(inventory, "commit", "-q", "-m", "box with a secret dropin")

    dropin_dir = tmp_path / "etc" / "systemd" / "system" / "gitea.service.d"
    dropin_dir.mkdir(parents=True)
    (dropin_dir / "env.conf").write_text(OLD_VALUE)

    import bastet.cli.run as run_mod

    monkeypatch.setattr(run_mod, "connect", lambda ctx, doc, tmp, yes: (SystemdUnderTmp(tmp_path), None))
    return tmp_path


def test_check_never_shows_old_or_new_multiline_secret_in_a_dropin(runner, box_with_secret_dropin):
    result = runner.invoke(app, ["run", "-c", "box"])
    assert result.exit_code == 0, result.output
    assert "Hunter2-OLD" not in result.output
    assert "Hunter2-NEW" not in result.output
    assert "DB_PASS" not in result.output
    assert "would-change" in result.output or "to change" in result.output or "(secret)" in result.output
