from bastet.cli.app import app
from bastet.core.secrets import crypto
from bastet.core.secrets.notes import SecretNote, SecretPath
from conftest import git


def _seed_unused_secret(inventory, pub) -> None:
    sp = SecretPath.parse("lab/unused_token")
    note = SecretNote.new(sp, source="chosen", created="2026-10-03T00:00", applies_to="lab")
    note.body = crypto.seal(sp.text, "short", [pub])
    note.write(inventory)
    git(inventory, "add", ".")
    git(inventory, "commit", "-q", "-m", "seed unused secret")


def test_audit_prints_grouped_findings_and_never_a_value(runner, secret_keys, inventory):
    _seed_unused_secret(inventory, secret_keys["pub"])
    result = runner.invoke(app, ["secret", "audit"])
    assert result.exit_code == 0, result.output
    assert "unused:" in result.output
    assert "lab/unused_token" in result.output
    assert "short" not in result.output


def test_audit_writes_dashboard_section_with_date(runner, secret_keys, inventory):
    _seed_unused_secret(inventory, secret_keys["pub"])
    result = runner.invoke(app, ["secret", "audit"])
    assert result.exit_code == 0, result.output
    note = (inventory / "_bastet" / "secret-audit.md").read_text()
    assert "checked:" in note and "## unused" in note and "lab/unused_token" in note
    dashboard = (inventory / "_bastet" / "bastet dashboard.md").read_text()
    assert "secret-audit" in dashboard


def test_audit_not_recommitted_when_only_the_date_changes(runner, secret_keys, inventory):
    _seed_unused_secret(inventory, secret_keys["pub"])
    runner.invoke(app, ["secret", "audit"])
    first = git(inventory, "log", "--format=%s").count("refresh: secret audit")
    runner.invoke(app, ["secret", "audit"])
    second = git(inventory, "log", "--format=%s").count("refresh: secret audit")
    assert first == 1 and second == 1


def test_secrets_md_lists_a_used_by_entry_for_a_shared_credential(runner, secret_keys, inventory, test_role):
    (inventory / "hosts" / "box2.md").write_text("---\nbastet: host\ntype: laptop\n---\n# box2\n")
    folder2 = inventory / "_roles" / "hosts" / "box2"
    folder2.mkdir(parents=True)
    (folder2 / "testsecret.md").write_text(
        '---\nbastet: role\nrole: testsecret\napplies_to: "[[box2]]"\n'
        'admin_password: "secret:lab/shared_cred"\ndb_password: "secret:db_password"\n---\n'
    )
    git(inventory, "add", ".")
    git(inventory, "commit", "-q", "-m", "box2 shares a secret")

    sp = SecretPath.parse("lab/shared_cred")
    note = SecretNote.new(sp, source="chosen", created="2026-10-03T00:00", applies_to="lab")
    note.body = crypto.seal(sp.text, "shared-value", [secret_keys["pub"]])
    note.write(inventory)
    git(inventory, "add", ".")
    git(inventory, "commit", "-q", "-m", "seed shared secret")

    # the box role file in `test_role` doesn't reference lab/shared_cred, so point it there too
    box_role = inventory / "_roles" / "hosts" / "box" / "testsecret.md"
    box_role.write_text(
        '---\nbastet: role\nrole: testsecret\napplies_to: "[[box]]"\n'
        'admin_password: "secret:lab/shared_cred"\ndb_password: "secret:db_password"\n---\n'
    )
    git(inventory, "add", ".")
    git(inventory, "commit", "-q", "-m", "box shares it too")

    result = runner.invoke(app, ["refresh"])
    assert result.exit_code == 0, result.output
    text = (inventory / "_bastet" / "Secrets.md").read_text()
    line = next(l for l in text.splitlines() if "shared_cred" in l)
    assert "box" in line and "box2" in line
