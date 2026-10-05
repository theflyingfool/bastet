import datetime as dt
import subprocess
from pathlib import Path

import pyrage
import pytest

from bastet.cli.common import Context
from bastet.core.config import Config, InventoryConfig, SshConfig
from bastet.core.gitrepo import GitRepo
from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from bastet.core.secrets import crypto, health
from bastet.core.secrets.notes import SecretNote, SecretPath
from bastet.roles.contract import load_roles

TYPES = load_host_types()


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def keys(tmp_path):
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(tmp_path / "k")], check=True)
    age = pyrage.x25519.Identity.generate()
    return {
        "ssh_pub": (tmp_path / "k.pub").read_text().strip(),
        "ssh_key": tmp_path / "k",
        "age_pub": str(age.to_public()),
    }


@pytest.fixture
def root(tmp_path, keys) -> Path:
    r = tmp_path / "inv"
    r.mkdir()
    (r / "Homelab.md").write_text(
        f"---\nbastet: lab\nsecrets:\n  recipients:\n    - {keys['ssh_pub']}\n    - {keys['age_pub']}\n---\n# Homelab\n"
    )
    (r / "hosts").mkdir()
    (r / "hosts" / "git1.md").write_text("---\nbastet: host\ntype: laptop\n---\n# git1\n")
    GitRepo(r).init()
    git(r, "config", "user.name", "Tester")
    git(r, "config", "user.email", "tester@example.com")
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "seed")
    return r


@pytest.fixture
def test_role(tmp_path, monkeypatch):
    """A role with a generatable secret and a non-generatable one, each with its own `rotate_every`."""
    roles_dir = tmp_path / "roles"
    (roles_dir / "svc").mkdir(parents=True)
    (roles_dir / "svc" / "role.yml").write_text(
        "description: a health-test role\n"
        "options:\n"
        "  admin_password:\n"
        "    type: string\n"
        "    secret: true\n"
        "    generate: {kind: password, length: 20}\n"
        "    rotate_every: {generated: 30d}\n"
        "  api_key:\n"
        "    type: string\n"
        "    secret: true\n"
    )
    merged = {**load_roles(), **load_roles(roles_dir)}
    import bastet.core.secrets.health as health_mod
    import bastet.roles.contract as contract_mod

    monkeypatch.setattr(contract_mod, "load_roles", lambda directory=None: merged if directory is None else load_roles(directory))
    return merged


def make_ctx(root: Path, keys: dict, *, ssh_key: bool = True) -> Context:
    config = Config(inventory=InventoryConfig(path=root), ssh=SshConfig(key=keys["ssh_key"] if ssh_key else None))
    repo = GitRepo(root)
    return Context(config=config, root=root, repo=repo, types=TYPES, inventory=load_inventory(root, TYPES))


def _seal(root: Path, sp: SecretPath, value: str, recipients: list[str], **kw) -> SecretNote:
    note = SecretNote.new(sp, source=kw.pop("source", "chosen"), created=kw.pop("created", "2026-10-03T10:00"),
                           applies_to=sp.host, **kw)
    note.body = crypto.seal(sp.text, value, recipients)
    note.data.update(kw)
    note.write(root)
    return note


def _add_role_file(root: Path, host: str, role: str, **values) -> None:
    folder = root / "_roles" / "hosts" / host
    folder.mkdir(parents=True, exist_ok=True)
    lines = [f'bastet: role', f"role: {role}", f'applies_to: "[[{host}]]"']
    for k, v in values.items():
        lines.append(f"{k}: {v}")
    (folder / f"{role}.md").write_text("---\n" + "\n".join(lines) + "\n---\n")


def test_healthy_with_no_secrets(root, keys):
    ctx = make_ctx(root, keys)
    assert health.findings(ctx) == []
    assert health.summary_lines(health.findings(ctx)) == ["Secrets: healthy."]
    assert health.relevant_secrets(ctx) is False


def test_missing_secret_generatable_is_not_blocking(root, keys, test_role):
    _add_role_file(root, "git1", "svc", admin_password="secret:admin_password", api_key="secret:api_key")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "role")
    ctx = make_ctx(root, keys)
    found = {f.kind: f for f in health.findings(ctx) if f.sp and f.sp.text in
             ("git1/svc/admin_password", "git1/svc/api_key")}
    missing = [f for f in health.findings(ctx) if f.kind == "missing"]
    by_path = {f.sp.text: f for f in missing}
    assert by_path["git1/svc/admin_password"].severity == "info"
    assert by_path["git1/svc/api_key"].severity == "block"
    assert health.relevant_secrets(ctx) is True


def test_plaintext_finding(root, keys):
    sp = SecretPath.parse("lab/x")
    note = SecretNote.new(sp, source="chosen", created="2026-10-03T10:00", applies_to="lab")
    note.data["locked"] = False
    note.body = "plain-value"
    note.write(root)
    ctx = make_ctx(root, keys)
    kinds = {f.kind for f in health.findings(ctx)}
    assert "plaintext" in kinds


def test_path_mismatch_and_undecryptable(root, keys):
    good = SecretPath.parse("lab/good")
    wrong_key = SecretPath.parse("lab/wrongkey")
    copied = SecretPath.parse("lab/copied")
    _seal(root, good, "v", [keys["ssh_pub"], keys["age_pub"]])
    # sealed for a different path entirely, so path_mismatch fires when opened under `copied`'s path
    armored = crypto.seal(good.text, "v", [keys["ssh_pub"], keys["age_pub"]])
    note = SecretNote.new(copied, source="chosen", created="2026-10-03T10:00", applies_to="lab")
    note.body = armored
    note.write(root)
    # sealed for a recipient Bastet's key isn't one of
    other_age = pyrage.x25519.Identity.generate()
    note2 = SecretNote.new(wrong_key, source="chosen", created="2026-10-03T10:00", applies_to="lab")
    note2.body = crypto.seal(wrong_key.text, "v", [str(other_age.to_public())])
    note2.write(root)
    ctx = make_ctx(root, keys)
    by_path = {f.sp.text: f.kind for f in health.findings(ctx) if f.sp}
    assert by_path["lab/copied"] == "path_mismatch"
    assert by_path["lab/wrongkey"] == "undecryptable"
    assert "lab/good" not in by_path or by_path["lab/good"] not in ("path_mismatch", "undecryptable")


def test_malformed_note_is_a_finding_not_a_crash(root, keys):
    bad = root / "_secrets" / "lab" / "broken.md"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("---\nbastet: secret\n  broken: [yaml\n---\n")
    ctx = make_ctx(root, keys)
    found = health.findings(ctx)
    assert any(f.kind == "undecryptable" and "broken.md" in f.text for f in found)


def test_rotation_policy_precedence_and_due(root, keys, test_role, monkeypatch):
    monkeypatch.setattr(health, "_now", lambda: dt.datetime(2026, 10, 3, 12, 0))
    _add_role_file(root, "git1", "svc", admin_password="secret:admin_password", api_key="secret:api_key",
                    rotate_every="{generated: 10d}")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "role")
    sp = SecretPath.parse("git1/svc/admin_password")
    _seal(root, sp, "v", [keys["ssh_pub"], keys["age_pub"]], source="generated", created="2026-09-01T00:00")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "secret")
    ctx = make_ctx(root, keys)
    note = SecretNote.load(root, sp)
    # the role file's rotate_every (10d) overrides the option contract's (30d): 32 days since creation is overdue
    assert health.effective_rotate_every(ctx, note) == "10d"
    kinds = {f.kind for f in health.findings(ctx) if f.sp and f.sp.text == sp.text}
    assert "rotation_due" in kinds


def test_expiring_and_expired(root, keys, monkeypatch):
    monkeypatch.setattr(health, "_now", lambda: dt.datetime(2026, 10, 3, 12, 0))
    soon = SecretPath.parse("lab/soon")
    gone = SecretPath.parse("lab/gone")
    _seal(root, soon, "v", [keys["ssh_pub"], keys["age_pub"]], expires="2026-10-10T00:00")
    _seal(root, gone, "v", [keys["ssh_pub"], keys["age_pub"]], expires="2026-01-01T00:00")
    ctx = make_ctx(root, keys)
    kinds_by_path: dict[str, set[str]] = {}
    for f in health.findings(ctx):
        if f.sp:
            kinds_by_path.setdefault(f.sp.text, set()).add(f.kind)
    assert "expiring" in kinds_by_path["lab/soon"]
    assert "expired" in kinds_by_path["lab/gone"]


def test_unused_and_standalone_but_used(root, keys, test_role):
    unused = SecretPath.parse("lab/unused")
    _seal(root, unused, "v", [keys["ssh_pub"], keys["age_pub"]])
    used_standalone = SecretPath.parse("git1/svc/admin_password")
    _seal(root, used_standalone, "v", [keys["ssh_pub"], keys["age_pub"]], source="generated", standalone=True)
    _add_role_file(root, "git1", "svc", admin_password="secret:admin_password", api_key="x")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "setup")
    ctx = make_ctx(root, keys)
    by_path = {f.sp.text: f.kind for f in health.findings(ctx) if f.sp}
    assert by_path["lab/unused"] == "unused"
    assert by_path["git1/svc/admin_password"] == "standalone_but_used"


def test_needs_reencryption(root, keys):
    sp = SecretPath.parse("lab/old")
    # sealed for only the ssh key, while Homelab.md's recipients list also includes the age key
    _seal(root, sp, "v", [keys["ssh_pub"]])
    ctx = make_ctx(root, keys)
    by_path = {f.sp.text: f.kind for f in health.findings(ctx) if f.sp}
    assert by_path.get("lab/old") == "needs_reencryption" or any(
        f.kind == "needs_reencryption" and f.sp.text == "lab/old" for f in health.findings(ctx))


def test_weak_only_flagged_in_audit_mode(root, keys):
    sp = SecretPath.parse("lab/weak")
    _seal(root, sp, "password", [keys["ssh_pub"], keys["age_pub"]])
    ctx = make_ctx(root, keys)
    assert not any(f.kind == "weak" for f in health.findings(ctx, audit=False))
    assert any(f.kind == "weak" and f.sp.text == "lab/weak" for f in health.findings(ctx, audit=True))


def test_not_by_bastet(root, keys):
    sp = SecretPath.parse("lab/x")
    _seal(root, sp, "v", [keys["ssh_pub"], keys["age_pub"]])
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "a human edit")  # Tester, not Bastet
    ctx = make_ctx(root, keys)
    assert any(f.kind == "not_by_bastet" and f.sp.text == "lab/x" for f in health.findings(ctx))


def test_placeholder_literal_value_in_role_file(root, keys, test_role):
    _add_role_file(root, "git1", "svc", admin_password="secret:admin_password", api_key="literal-value-not-a-ref")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "role")
    ctx = make_ctx(root, keys)
    placeholders = [f for f in health.findings(ctx) if f.kind == "placeholder"]
    assert placeholders and "literal-value-not-a-ref" not in placeholders[0].text


def test_few_recipients(root, keys):
    # Homelab.md here has two distinct recipients already; a lab with only one should warn
    homelab = root / "Homelab.md"
    homelab.write_text(f"---\nbastet: lab\nsecrets:\n  recipients:\n    - {keys['ssh_pub']}\n---\n# Homelab\n")
    ctx = make_ctx(root, keys)
    sp = SecretPath.parse("lab/x")
    _seal(root, sp, "v", [keys["ssh_pub"]])
    assert any(f.kind == "few_recipients" for f in health.findings(ctx))


def test_scope_includes_hosts_and_lab_secrets_they_use_only(root, keys, test_role):
    (root / "hosts" / "git2.md").write_text("---\nbastet: host\ntype: laptop\n---\n# git2\n")
    _add_role_file(root, "git1", "svc", admin_password="secret:admin_password", api_key="secret:lab/shared")
    _add_role_file(root, "git2", "svc", admin_password="secret:admin_password", api_key="secret:git2/svc/api_key")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "roles")
    ctx = make_ctx(root, keys)
    scoped = {f.sp.text for f in health.findings(ctx, scope_hosts=["git1"]) if f.sp}
    assert "git1/svc/admin_password" in scoped
    assert "lab/shared" in scoped  # a lab secret used by an in-scope host
    assert "git2/svc/admin_password" not in scoped
    assert "git2/svc/api_key" not in scoped


def test_summary_lines_one_healthy_line_and_blocking_plus_audit_count(root, keys, test_role):
    _add_role_file(root, "git1", "svc", admin_password="secret:admin_password", api_key="secret:api_key")
    unused = SecretPath.parse("lab/unused")
    _seal(root, unused, "v", [keys["ssh_pub"], keys["age_pub"]])
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "roles")
    ctx = make_ctx(root, keys)
    lines = health.summary_lines(health.findings(ctx))
    assert any("missing" in line for line in lines)
    assert any("audit finding" in line for line in lines)
