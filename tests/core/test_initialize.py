import json
import subprocess
from pathlib import Path

import pytest

from bastet.core.config import load_config
from bastet.core.errors import BastetError
from bastet.core.initialize import (
    InitOptions, ProcResult, SUDOERS_LINE, existing_recipients, generate_recovery_key, initialize,
    local_user_setup, sshd_inactive_unit, sshd_ready,
)


def log(root):
    return subprocess.run(["git", "-C", str(root), "log", "--format=%an %s"], capture_output=True, text=True).stdout.splitlines()


def opts(tmp_path: Path, **kw) -> InitOptions:
    base = dict(
        inventory=tmp_path / "Homelab", remote=None, key=None, bootstrap_user="nick",
        lab_name="Homelab", domains={"public": "example.com"}, snippet=True,
    )
    base.update(kw)
    return InitOptions(**base)


def test_init_from_nothing(tmp_path):
    cfg = tmp_path / "cfg" / "bastet.yml"
    r = initialize(cfg, opts(tmp_path), keys_dir=tmp_path / "cfg" / "ssh")
    inv = tmp_path / "Homelab"
    loaded = load_config(cfg)
    assert loaded.inventory.path == inv
    assert loaded.ssh.key == tmp_path / "cfg" / "ssh" / "id_ed25519"
    assert loaded.ssh.bootstrap_user == "nick"
    lab = (inv / "Homelab.md").read_text()
    assert lab.startswith("---\nbastet: lab\n") and "name: Homelab\n" in lab and "public: example.com\n" in lab
    assert (inv / ".obsidian" / "snippets" / "bastet.css").exists()
    assert json.loads((inv / ".obsidian" / "appearance.json").read_text())["enabledCssSnippets"] == ["bastet"]
    assert r.public_key.read_text().startswith("ssh-ed25519 ")
    assert r.committed and log(inv)[0] == "Bastet bastet init"


def test_init_is_idempotent(tmp_path):
    cfg = tmp_path / "cfg" / "bastet.yml"
    initialize(cfg, opts(tmp_path), keys_dir=tmp_path / "ssh")
    before = log(tmp_path / "Homelab")
    r = initialize(cfg, opts(tmp_path), keys_dir=tmp_path / "ssh")
    assert not r.committed
    assert all(a.startswith("kept") for a in r.actions), r.actions
    assert log(tmp_path / "Homelab") == before


def test_existing_key_is_used_not_generated(tmp_path):
    key = tmp_path / "mykey"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
    cfg = tmp_path / "bastet.yml"
    r = initialize(cfg, opts(tmp_path, key=key), keys_dir=tmp_path / "ssh")
    assert load_config(cfg).ssh.key == key
    assert not (tmp_path / "ssh").exists()
    assert r.public_key == key.with_suffix(".pub")


def test_missing_existing_key_is_error(tmp_path):
    with pytest.raises(BastetError) as e:
        initialize(tmp_path / "bastet.yml", opts(tmp_path, key=tmp_path / "nope"), keys_dir=tmp_path / "ssh")
    assert e.value.file == tmp_path / "nope"


def test_no_snippet(tmp_path):
    initialize(tmp_path / "bastet.yml", opts(tmp_path, snippet=False), keys_dir=tmp_path / "ssh")
    assert not (tmp_path / "Homelab" / ".obsidian").exists()


def test_keeps_existing_repo_and_merges_appearance(tmp_path):
    inv = tmp_path / "Homelab"
    (inv / ".obsidian").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(inv)], check=True)
    (inv / ".gitignore").write_text("custom\n")
    (inv / ".obsidian" / "appearance.json").write_text('{"theme": "obsidian", "enabledCssSnippets": ["mine"]}')
    initialize(tmp_path / "bastet.yml", opts(tmp_path), keys_dir=tmp_path / "ssh")
    assert (inv / ".gitignore").read_text() == "custom\n"
    data = json.loads((inv / ".obsidian" / "appearance.json").read_text())
    assert data == {"theme": "obsidian", "enabledCssSnippets": ["mine", "bastet"]}


def test_remote_written_and_added(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_SSH_COMMAND", "false")
    cfg = tmp_path / "bastet.yml"
    initialize(cfg, opts(tmp_path, remote="git@example.com:me/inv.git"), keys_dir=tmp_path / "ssh")
    assert load_config(cfg).inventory.remote == "git@example.com:me/inv.git"
    remotes = subprocess.run(["git", "-C", str(tmp_path / "Homelab"), "remote", "-v"], capture_output=True, text=True).stdout
    assert "git@example.com:me/inv.git" in remotes


def test_bad_appearance_json_is_located_error(tmp_path):
    inv = tmp_path / "Homelab"
    (inv / ".obsidian").mkdir(parents=True)
    (inv / ".obsidian" / "appearance.json").write_text("{not json")
    with pytest.raises(BastetError) as e:
        initialize(tmp_path / "bastet.yml", opts(tmp_path), keys_dir=tmp_path / "ssh")
    assert e.value.file == inv / ".obsidian" / "appearance.json"


def test_existing_key_with_extension(tmp_path):
    key = tmp_path / "bastet.key"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
    r = initialize(tmp_path / "bastet.yml", opts(tmp_path, key=key), keys_dir=tmp_path / "ssh")
    assert r.public_key == tmp_path / "bastet.key.pub"


def test_ssh_keygen_failure_is_bastet_error(tmp_path, monkeypatch):
    import bastet.core.initialize as init_mod

    def boom(*a, **k):
        raise subprocess.CalledProcessError(1, a[0], stderr="nope")

    monkeypatch.setattr(init_mod.subprocess, "run", boom)
    with pytest.raises(BastetError):
        initialize(tmp_path / "bastet.yml", opts(tmp_path), keys_dir=tmp_path / "ssh")


def _bare_with_commit(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", "-q", str(bare), str(seed)], check=True, capture_output=True)
    (seed / "hosts").mkdir()
    (seed / "hosts" / "pve1.md").write_text("---\nbastet: host\ntype: proxmox-node\nip: 10.0.10.11\n---\n")
    for args in (["add", "."], ["-c", "user.name=T", "-c", "user.email=t@example.com", "commit", "-q", "-m", "seed"], ["push", "-q"]):
        subprocess.run(["git", "-C", str(seed), *args], check=True, capture_output=True)
    return bare


def test_init_clones_remote_with_history(tmp_path):
    bare = _bare_with_commit(tmp_path)
    r = initialize(tmp_path / "bastet.yml", opts(tmp_path, remote=str(bare)), keys_dir=tmp_path / "ssh")
    inv = tmp_path / "Homelab"
    assert (inv / "hosts" / "pve1.md").exists()
    assert any(a.startswith("cloned") for a in r.actions)
    remote_log = subprocess.run(["git", "--git-dir", str(bare), "log", "--format=%s"], capture_output=True, text=True).stdout
    assert "bastet init" in remote_log


def test_generate_recovery_key_returns_private_and_public():
    private, public = generate_recovery_key()
    assert private.startswith("AGE-SECRET-KEY-1")
    assert public.startswith("age1")
    private2, public2 = generate_recovery_key()
    assert private2 != private and public2 != public  # a fresh identity every call


def test_initialize_writes_recipients_into_new_homelab(tmp_path):
    cfg = tmp_path / "cfg" / "bastet.yml"
    _, recovery_pub = generate_recovery_key()
    recipients = [recovery_pub, "ssh-ed25519 AAAAyours nick@laptop"]
    r = initialize(cfg, opts(tmp_path, recipients=recipients), keys_dir=tmp_path / "cfg" / "ssh")
    assert r.committed
    lab = (tmp_path / "Homelab" / "Homelab.md").read_text()
    assert recovery_pub in lab and "ssh-ed25519 AAAAyours nick@laptop" in lab
    assert existing_recipients(tmp_path / "Homelab" / "Homelab.md") == recipients


def test_initialize_adds_recipients_to_existing_homelab(tmp_path):
    cfg = tmp_path / "cfg" / "bastet.yml"
    initialize(cfg, opts(tmp_path), keys_dir=tmp_path / "cfg" / "ssh")  # no recipients yet
    inv = tmp_path / "Homelab"
    assert existing_recipients(inv / "Homelab.md") == []
    _, recovery_pub = generate_recovery_key()
    r = initialize(cfg, opts(tmp_path, recipients=[recovery_pub]), keys_dir=tmp_path / "cfg" / "ssh")
    assert any(a == "added secrets.recipients to Homelab.md" for a in r.actions)
    assert existing_recipients(inv / "Homelab.md") == [recovery_pub]
    assert r.committed


def test_initialize_recipients_are_idempotent(tmp_path):
    cfg = tmp_path / "cfg" / "bastet.yml"
    _, recovery_pub = generate_recovery_key()
    initialize(cfg, opts(tmp_path, recipients=[recovery_pub]), keys_dir=tmp_path / "cfg" / "ssh")
    inv = tmp_path / "Homelab"
    before = (inv / "Homelab.md").read_text()
    before_log = log(inv)
    # a second run, even asked to add the same (or a different) recipients list, never changes what's there
    _, other_pub = generate_recovery_key()
    r = initialize(cfg, opts(tmp_path, recipients=[other_pub]), keys_dir=tmp_path / "cfg" / "ssh")
    assert not r.committed
    assert (inv / "Homelab.md").read_text() == before
    assert log(inv) == before_log
    assert existing_recipients(inv / "Homelab.md") == [recovery_pub]


def test_init_pushes_to_empty_remote(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    initialize(tmp_path / "bastet.yml", opts(tmp_path, remote=str(bare)), keys_dir=tmp_path / "ssh")
    remote_log = subprocess.run(["git", "--git-dir", str(bare), "log", "--format=%s"], capture_output=True, text=True).stdout
    assert "bastet init" in remote_log


# --- local machine setup (`bastet init` sets up this computer as a Bastet host): a fake system,
# never the real one, so these tests run no sudo, useradd or visudo for real ---

PUBKEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAfake nick@laptop"


class FakeSystem:
    """Tracks just enough state (a user, a sudoers drop-in, authorized_keys) for `local_user_setup`
    to see a fresh machine on the first call and an already-set-up one on the next."""

    def __init__(self):
        self.user_exists = False
        self.sudoers: str | None = None
        self.authorized_keys: str | None = None
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> ProcResult:
        self.calls.append(argv)
        if argv == ["id", "bastet"]:
            return ProcResult(0 if self.user_exists else 1)
        if argv[:3] == ["sudo", "-n", "useradd"]:
            self.user_exists = True
            return ProcResult(0)
        if argv[:3] == ["sudo", "-n", "usermod"]:
            return ProcResult(0)
        if argv == ["getent", "passwd", "bastet"]:
            if not self.user_exists:
                return ProcResult(2)
            return ProcResult(0, "bastet:x:1001:1001::/home/bastet:/bin/sh\n")
        if argv == ["getent", "group", "1001"]:
            return ProcResult(0, "bastet:x:1001:\n")
        if argv == ["sudo", "-n", "cat", "/etc/sudoers.d/bastet"]:
            return ProcResult(0, self.sudoers) if self.sudoers is not None else ProcResult(1)
        if argv[:3] == ["sudo", "-n", "visudo"]:
            text = Path(argv[4]).read_text(encoding="utf-8")
            return ProcResult(0) if text == SUDOERS_LINE else ProcResult(1, "", "syntax error")
        if argv[:3] == ["sudo", "-n", "install"] and argv[-1] == "/etc/sudoers.d/bastet":
            self.sudoers = Path(argv[-2]).read_text(encoding="utf-8")
            return ProcResult(0)
        if argv == ["sudo", "-n", "cat", "/home/bastet/.ssh/authorized_keys"]:
            return ProcResult(0, self.authorized_keys) if self.authorized_keys is not None else ProcResult(1)
        if argv[:3] == ["sudo", "-n", "install"] and argv[-1] == "/home/bastet/.ssh":
            return ProcResult(0)
        if argv[:3] == ["sudo", "-n", "install"] and argv[-1] == "/home/bastet/.ssh/authorized_keys":
            self.authorized_keys = Path(argv[-2]).read_text(encoding="utf-8")
            return ProcResult(0)
        raise AssertionError(f"unexpected command: {argv}")


def test_local_user_setup_on_a_fresh_machine(tmp_path):
    fake = FakeSystem()
    actions = local_user_setup(fake, tmp_path, PUBKEY)
    assert any("created" in a and "bastet" in a for a in actions)
    assert any("sudo" in a for a in actions)
    assert any("authorized_keys" in a for a in actions)
    assert fake.sudoers == SUDOERS_LINE
    assert fake.authorized_keys == PUBKEY + "\n"
    useradd_calls = [c for c in fake.calls if c[:3] == ["sudo", "-n", "useradd"]]
    assert useradd_calls == [["sudo", "-n", "useradd", "--create-home", "--shell", "/bin/sh", "bastet"]]
    assert ["sudo", "-n", "usermod", "-p", "*", "bastet"] in fake.calls


def test_local_user_setup_validates_sudoers_before_installing(tmp_path):
    fake = FakeSystem()
    local_user_setup(fake, tmp_path, PUBKEY)
    install_index = next(i for i, c in enumerate(fake.calls) if c[:3] == ["sudo", "-n", "install"] and c[-1] == "/etc/sudoers.d/bastet")
    visudo_index = next(i for i, c in enumerate(fake.calls) if c[:3] == ["sudo", "-n", "visudo"])
    assert visudo_index < install_index


def test_local_user_setup_second_run_issues_no_changes(tmp_path):
    fake = FakeSystem()
    local_user_setup(fake, tmp_path, PUBKEY)
    fake.calls.clear()
    actions = local_user_setup(fake, tmp_path, PUBKEY)
    assert all(a.startswith("kept") for a in actions), actions
    mutating = [c for c in fake.calls if c[0] not in ("id", "getent") and c[:3] != ["sudo", "-n", "cat"]]
    assert mutating == []


def test_local_user_setup_rejects_a_bad_public_key(tmp_path):
    with pytest.raises(BastetError):
        local_user_setup(FakeSystem(), tmp_path, "not a key")


class FlakySudoersInstall(FakeSystem):
    """Like `FakeSystem`, but installing the sudoers drop-in always fails (e.g. a stale `sudo -n`)."""

    def __call__(self, argv: list[str]) -> ProcResult:
        if argv[:3] == ["sudo", "-n", "install"] and argv[-1] == "/etc/sudoers.d/bastet":
            self.calls.append(argv)
            return ProcResult(1, "", "sudo: a password is required")
        return super().__call__(argv)


def test_local_user_setup_raises_when_sudoers_install_fails(tmp_path):
    fake = FlakySudoersInstall()
    with pytest.raises(BastetError):
        local_user_setup(fake, tmp_path, PUBKEY)
    assert fake.sudoers is None


def test_sshd_ready_when_scan_succeeds_even_if_systemctl_says_inactive():
    """The scan is authoritative: a socket-activated unit, or one systemd doesn't recognise, still
    counts as ready as long as something answers on 127.0.0.1."""
    def run(argv):
        raise AssertionError(f"systemctl should not be consulted when the scan succeeds: {argv}")

    ok, hint = sshd_ready(run, lambda address, port=22: None)
    assert ok and hint is None


def test_sshd_ready_reports_enable_hint_when_scan_fails_and_unit_inactive():
    def scan(address, port=22):
        raise BastetError("nothing answered")

    ok, hint = sshd_ready(lambda argv: ProcResult(3, "inactive\n"), scan)
    assert not ok and "sshd isn't active" in hint


def test_sshd_ready_reports_listenaddress_hint_when_scan_fails_and_unit_active():
    def scan(address, port=22):
        raise BastetError("nothing answered")

    ok, hint = sshd_ready(lambda argv: ProcResult(0, "active\n"), scan)
    assert not ok and "127.0.0.1" in hint and "ListenAddress" in hint


def test_sshd_ready_checks_the_debian_ssh_unit_name_too():
    def scan(address, port=22):
        raise BastetError("nothing answered")

    def run(argv):
        if argv == ["systemctl", "is-active", "sshd"]:
            return ProcResult(4, "", "Unit sshd.service could not be found.")
        if argv == ["systemctl", "is-active", "ssh"]:
            return ProcResult(0, "active\n")
        raise AssertionError(argv)

    ok, hint = sshd_ready(run, scan)
    assert not ok and "127.0.0.1" in hint and "ListenAddress" in hint


def test_sshd_inactive_unit_none_when_already_active():
    assert sshd_inactive_unit(lambda argv: ProcResult(0, "active\n")) is None


def test_sshd_inactive_unit_returns_sshd_when_inactive():
    def run(argv):
        assert argv == ["systemctl", "is-active", "sshd"]
        return ProcResult(3, "inactive\n")

    assert sshd_inactive_unit(run) == "sshd"


def test_sshd_inactive_unit_falls_back_to_ssh_when_sshd_is_unknown():
    def run(argv):
        if argv == ["systemctl", "is-active", "sshd"]:
            return ProcResult(4, "", "Unit sshd.service could not be found.")
        if argv == ["systemctl", "is-active", "ssh"]:
            return ProcResult(3, "inactive\n")
        raise AssertionError(argv)

    assert sshd_inactive_unit(run) == "ssh"


def test_sshd_inactive_unit_none_when_neither_name_is_recognised():
    assert sshd_inactive_unit(lambda argv: ProcResult(4, "", "could not be found")) is None
