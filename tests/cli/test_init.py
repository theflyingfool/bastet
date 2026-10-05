import base64
import re
from pathlib import Path

import pytest

import bastet.cli.init as init_mod
from bastet.cli.app import app
from bastet.core.config import load_config
from bastet.core.hostkeys import parse_keyscan
from bastet.core.initialize import ProcResult, SUDOERS_LINE

RECOVERY_RE = re.compile(r"AGE-SECRET-KEY-1[A-Z0-9]+")
FAKE_HOST_KEYS = parse_keyscan(f"h ssh-ed25519 {base64.b64encode(b'local-host-key').decode()}\n")


@pytest.fixture(autouse=True)
def _no_real_home(tmp_path, monkeypatch):
    """Every test here touches `~/.ssh` through `bastet init`; keep it pointed at a throwaway HOME,
    never the real one."""
    monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))


class FakeLocalSystem:
    """A fake machine for `_setup_this_machine`'s commands: a user, a sudoers drop-in and
    authorized_keys, none of it real. Persists across repeated calls in one test, so a second
    `bastet init` sees an already-set-up machine."""

    def __init__(self):
        self.user_exists = False
        self.password = ""  # shadow field 2; "" means never explicitly locked
        self.sudoers: str | None = None
        self.authorized_keys: str | None = None
        self.calls: list[list[str]] = []
        self.sshd_active = True
        self.sshd_installed = True  # `systemctl cat sshd`; real systemd distinguishes this from "inactive"
        self.reachable = True  # whether a scan of 127.0.0.1 answers (independent of sshd_active)
        self.enable_fails = False  # `sudo systemctl enable --now <unit>` fails, e.g. no unit file

    def scan(self, address: str = "127.0.0.1", port: int = 22):
        if not self.reachable:
            from bastet.core.errors import Unreachable
            raise Unreachable(f"{address}: nothing answered in tests")
        return FAKE_HOST_KEYS

    def __call__(self, argv: list[str]) -> ProcResult:
        self.calls.append(argv)
        if argv in (["systemctl", "cat", "sshd"], ["systemctl", "cat", "ssh"]):
            return ProcResult(0) if self.sshd_installed else ProcResult(1, "", f"No files found for {argv[-1]}.")
        if argv in (["systemctl", "is-active", "sshd"], ["systemctl", "is-active", "ssh"]):
            if not self.sshd_installed:
                return ProcResult(4, "inactive\n")
            return ProcResult(0, "active\n") if self.sshd_active else ProcResult(3, "inactive\n")
        if argv[:4] == ["sudo", "-n", "systemctl", "enable"] and argv[-1] in ("sshd", "ssh"):
            if self.enable_fails:
                return ProcResult(1, "", f"Failed to enable unit: Unit file {argv[-1]}.service does not exist.")
            self.sshd_active = True
            self.reachable = True
            return ProcResult(0)
        if argv == ["id", "bastet"]:
            return ProcResult(0 if self.user_exists else 1)
        if argv[:3] == ["sudo", "-n", "useradd"]:
            self.user_exists = True
            return ProcResult(0)
        if argv[:4] == ["sudo", "-n", "getent", "shadow"]:
            if not self.user_exists:
                return ProcResult(2)
            return ProcResult(0, f"bastet:{self.password}:19000:0:99999:7:::\n")
        if argv[:3] == ["sudo", "-n", "usermod"]:
            self.password = "*"
            return ProcResult(0)
        if argv == ["getent", "passwd", "bastet"]:
            return ProcResult(0, "bastet:x:1001:1001::/home/bastet:/bin/sh\n") if self.user_exists else ProcResult(2)
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


@pytest.fixture(autouse=True)
def _fake_local_machine(monkeypatch):
    """`bastet init` can set up this machine as a Bastet host (sudo, useradd, visudo, ssh-keyscan);
    every test here gets a fake system instead, so none of that ever touches the real one."""
    fake = FakeLocalSystem()
    monkeypatch.setattr(init_mod, "_runner", fake)
    monkeypatch.setattr(init_mod, "_sudo_validate", lambda: True)
    monkeypatch.setattr(init_mod, "_scan_local", fake.scan)
    return fake


@pytest.fixture
def interactive(monkeypatch):
    """Pretend stdout is a terminal, so `init` creates the recovery key and recipients -- a
    CliRunner's captured stdout never is one, by design (m2)."""
    monkeypatch.setattr(init_mod, "_stdout_is_tty", lambda: True)


def test_cli_init_yes_uses_defaults_and_flags(runner, tmp_path, monkeypatch):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    result = runner.invoke(app, ["init", "--inventory", str(tmp_path / "Homelab"), "--public-domain", "example.com", "-y"])
    assert result.exit_code == 0, result.output
    assert "created" in result.output and "ssh-ed25519" in result.output
    lab = (tmp_path / "Homelab" / "Homelab.md").read_text()
    assert "public: example.com" in lab and "internal: example.com" in lab


def test_cli_init_interactive(runner, tmp_path, monkeypatch, interactive):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    answers = "\n".join([
        str(tmp_path / "Lab"),   # inventory
        "",                      # remote: none
        "new",                   # key
        "nick",                  # bootstrap user
        "My Lab",                # lab name
        "example.com",           # public domain
        "-",                     # internal domain: none
        "y",                     # stylesheet
        "",                      # your SSH public key: skip
        "y",                     # go ahead
    ]) + "\n"
    result = runner.invoke(app, ["init"], input=answers)
    assert result.exit_code == 0, result.output
    assert load_config(cfg).inventory.path == tmp_path / "Lab"
    assert "name: My Lab" in (tmp_path / "Lab" / "Homelab.md").read_text()


def test_cli_init_declined_writes_nothing(runner, tmp_path, monkeypatch, interactive):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    answers = "\n".join([str(tmp_path / "Lab"), "", "new", "nick", "Homelab", "", "-", "y", "", "n"]) + "\n"
    result = runner.invoke(app, ["init"], input=answers)
    assert result.exit_code == 0
    assert not cfg.exists() and not (tmp_path / "Lab").exists()


def test_cli_init_builds_dashboard(runner, tmp_path, monkeypatch):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    result = runner.invoke(app, ["init", "--inventory", str(tmp_path / "Homelab"), "-y"])
    assert result.exit_code == 0, result.output
    assert "![[bastet dashboard]]" in (tmp_path / "Homelab" / "Homelab.md").read_text()
    assert (tmp_path / "Homelab" / "_bastet" / "bastet dashboard.md").exists()


def _recovery_key(output: str) -> str:
    m = RECOVERY_RE.search(output)
    assert m, output
    return m.group(0)


def test_cli_init_prints_recovery_key_once_and_never_writes_it(runner, tmp_path, monkeypatch, interactive):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    result = runner.invoke(app, ["init", "--inventory", str(tmp_path / "Homelab"), "-y"])
    assert result.exit_code == 0, result.output
    assert "Recovery key: keep this offline" in result.output
    key = _recovery_key(result.output)
    assert result.output.count(key) == 1
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert key not in path.read_text(encoding="utf-8", errors="ignore"), path


def test_cli_init_adds_recipients_to_homelab(runner, tmp_path, monkeypatch, interactive):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    home = tmp_path / "fakehome"
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "id_ed25519.pub").write_text("ssh-ed25519 AAAAyourkey nick@laptop\n")
    result = runner.invoke(app, ["init", "--inventory", str(tmp_path / "Homelab"), "-y"])
    assert result.exit_code == 0, result.output
    lab = (tmp_path / "Homelab" / "Homelab.md").read_text()
    assert "secrets:" in lab and "recipients:" in lab
    assert "ssh-ed25519 AAAAyourkey nick@laptop" in lab
    assert "age1" in lab


def test_cli_init_recipients_are_idempotent(runner, tmp_path, monkeypatch, interactive):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    inv = tmp_path / "Homelab"
    first = runner.invoke(app, ["init", "--inventory", str(inv), "-y"])
    assert first.exit_code == 0, first.output
    lab_before = (inv / "Homelab.md").read_text()

    second = runner.invoke(app, ["init", "-y"])
    assert second.exit_code == 0, second.output
    assert "Recovery key" not in second.output
    lab_after = (inv / "Homelab.md").read_text()
    assert lab_after == lab_before


def _strip_secrets_key(lab: Path) -> None:
    """Drop the `secrets:` block `-y` adds by default, to simulate an inventory from before secrets
    existed."""
    text = lab.read_text()
    assert "secrets:" in text
    lines = text.splitlines()
    start = lines.index("secrets:")
    end = start + 1
    while end < len(lines) and lines[end].startswith((" ", "\t")):
        end += 1
    del lines[start:end]
    lab.write_text("\n".join(lines) + "\n")
    assert "secrets:" not in lab.read_text()


def test_cli_init_offers_recipients_for_existing_inventory(runner, tmp_path, monkeypatch, interactive):
    """An inventory from before secrets existed: `bastet init` offers to add recipients, as a diff."""
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    inv = tmp_path / "Homelab"
    first = runner.invoke(app, ["init", "--inventory", str(inv), "-y"])
    assert first.exit_code == 0, first.output
    lab = inv / "Homelab.md"
    _strip_secrets_key(lab)

    result = runner.invoke(
        app,
        ["init", "--lab-name", "Homelab", "--public-domain", "", "--internal-domain", "", "--snippet"],
        input="\ny\ny\n",  # your SSH key: skip; add recipients: yes; go ahead: yes
    )
    assert result.exit_code == 0, result.output
    assert "Bastet will add to Homelab.md" in result.output
    assert "Recovery key: keep this offline" in result.output
    assert "secrets:" in lab.read_text() and "recipients:" in lab.read_text()


# --- m2: the recovery key is the only copy of that identity; never print it, or create recipients
# that depend on it, anywhere other than an actual terminal ---


def test_cli_init_without_a_terminal_does_not_create_a_recovery_key(runner, tmp_path, monkeypatch):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    result = runner.invoke(app, ["init", "--inventory", str(tmp_path / "Homelab"), "-y"])
    assert result.exit_code == 0, result.output
    assert "Recovery key" not in result.output
    assert not RECOVERY_RE.search(result.output)
    assert "run `bastet init` in a terminal" in result.output
    lab = (tmp_path / "Homelab" / "Homelab.md").read_text()
    assert "secrets:" not in lab


def test_cli_init_without_a_terminal_for_an_existing_inventory_does_not_offer_recipients(
    runner, tmp_path, monkeypatch, interactive
):
    """Same scenario as test_cli_init_offers_recipients_for_existing_inventory (an inventory from
    before secrets existed, so no recipients yet) but the second run isn't at a terminal: it must not
    create recipients or print a recovery key, same as a brand new inventory."""
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    inv = tmp_path / "Homelab"
    first = runner.invoke(app, ["init", "--inventory", str(inv), "-y"])
    assert first.exit_code == 0, first.output
    lab = inv / "Homelab.md"
    _strip_secrets_key(lab)

    monkeypatch.setattr(init_mod, "_stdout_is_tty", lambda: False)
    second = runner.invoke(app, ["init", "-y"])
    assert second.exit_code == 0, second.output
    assert "Recovery key" not in second.output
    assert not RECOVERY_RE.search(second.output)
    assert "secrets:" not in lab.read_text()


# --- `bastet init` sets up this machine as a Bastet host: the local `bastet` user, passwordless
# sudo, its authorized_keys, an sshd check, and (once confirmed) its host key ---


def test_cli_init_sets_up_this_machine_on_a_fresh_run(runner, tmp_path, monkeypatch, interactive, _fake_local_machine):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    result = runner.invoke(app, ["init", "--inventory", str(tmp_path / "Homelab"), "-y"])
    assert result.exit_code == 0, result.output
    assert "created the local bastet user" in result.output
    assert "set up bastet's passwordless sudo" in result.output
    assert "installed Bastet's key in bastet's authorized_keys" in result.output

    install_index = next(
        i for i, c in enumerate(_fake_local_machine.calls)
        if c[:3] == ["sudo", "-n", "install"] and c[-1] == "/etc/sudoers.d/bastet"
    )
    visudo_index = next(i for i, c in enumerate(_fake_local_machine.calls) if c[:3] == ["sudo", "-n", "visudo"])
    assert visudo_index < install_index


def test_cli_init_second_run_sets_up_nothing_more(runner, tmp_path, monkeypatch, interactive, _fake_local_machine):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    first = runner.invoke(app, ["init", "--inventory", str(tmp_path / "Homelab"), "-y"])
    assert first.exit_code == 0, first.output
    _fake_local_machine.calls.clear()

    second = runner.invoke(app, ["init", "-y"])
    assert second.exit_code == 0, second.output
    assert "kept the local bastet user" in second.output
    assert "kept bastet's passwordless sudo" in second.output
    assert "kept Bastet's key in bastet's authorized_keys" in second.output
    mutating = [
        c for c in _fake_local_machine.calls
        if c[0] not in ("id", "getent", "systemctl") and c[:3] != ["sudo", "-n", "cat"]
        and c[:4] != ["sudo", "-n", "getent", "shadow"]
    ]
    assert mutating == []


def test_cli_init_sshd_inactive_prints_enable_hint_and_edits_no_sshd_config(
    runner, tmp_path, monkeypatch, interactive, _fake_local_machine
):
    # Not active, and so (realistically) not answering either.
    _fake_local_machine.sshd_active = False
    _fake_local_machine.reachable = False
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    result = runner.invoke(app, ["init", "--inventory", str(tmp_path / "Homelab"), "-y"])
    assert result.exit_code == 0, result.output
    assert "sshd isn't active" in result.output
    assert "host key" not in result.output
    assert not any("sshd_config" in " ".join(c) for c in _fake_local_machine.calls)


def test_cli_init_sshd_not_answering_on_127_prints_listenaddress_hint(
    runner, tmp_path, monkeypatch, interactive, _fake_local_machine
):
    # Active (per systemd), but nothing answers on 127.0.0.1 -- e.g. ListenAddress points elsewhere.
    _fake_local_machine.sshd_active = True
    _fake_local_machine.reachable = False
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    result = runner.invoke(app, ["init", "--inventory", str(tmp_path / "Homelab"), "-y"])
    assert result.exit_code == 0, result.output
    assert "sshd isn't answering on 127.0.0.1" in result.output
    assert "host key" not in result.output
    assert not any("sshd_config" in " ".join(c) for c in _fake_local_machine.calls)


def test_cli_init_sshd_ready_even_if_systemctl_reports_inactive(
    runner, tmp_path, monkeypatch, interactive, _fake_local_machine
):
    # A reachable 127.0.0.1 is authoritative -- e.g. a socket-activated unit systemd calls inactive.
    _fake_local_machine.sshd_active = False
    _fake_local_machine.reachable = True
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    result = runner.invoke(app, ["init", "--inventory", str(tmp_path / "Homelab"), "-y"])
    assert result.exit_code == 0, result.output
    assert "sshd isn't" not in result.output
    assert "No local host in the inventory yet" in result.output


def test_cli_init_offers_to_start_sshd_and_continues_when_confirmed(
    runner, tmp_path, monkeypatch, interactive, _fake_local_machine
):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    inv = tmp_path / "Homelab"
    first = runner.invoke(app, ["init", "--inventory", str(inv), "-y"])
    assert first.exit_code == 0, first.output
    _fake_local_machine.calls.clear()
    _fake_local_machine.sshd_active = False
    _fake_local_machine.reachable = False

    result = runner.invoke(
        app,
        ["init", "--lab-name", "Homelab", "--public-domain", "", "--internal-domain", "", "--snippet"],
        input="y\ny\n",  # go ahead: yes; start sshd now: yes
    )
    assert result.exit_code == 0, result.output
    assert "Start sshd now" in result.output
    enable_calls = [c for c in _fake_local_machine.calls if c[:4] == ["sudo", "-n", "systemctl", "enable"]]
    assert enable_calls == [["sudo", "-n", "systemctl", "enable", "--now", "sshd"]]
    assert "No local host in the inventory yet" in result.output


def test_cli_init_declines_to_start_sshd_and_issues_no_enable_command(
    runner, tmp_path, monkeypatch, interactive, _fake_local_machine
):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    inv = tmp_path / "Homelab"
    first = runner.invoke(app, ["init", "--inventory", str(inv), "-y"])
    assert first.exit_code == 0, first.output
    _fake_local_machine.calls.clear()
    _fake_local_machine.sshd_active = False
    _fake_local_machine.reachable = False

    result = runner.invoke(
        app,
        ["init", "--lab-name", "Homelab", "--public-domain", "", "--internal-domain", "", "--snippet"],
        input="y\nn\n",  # go ahead: yes; start sshd now: no
    )
    assert result.exit_code == 0, result.output
    assert "sshd isn't active" in result.output
    enable_calls = [c for c in _fake_local_machine.calls if c[:4] == ["sudo", "-n", "systemctl", "enable"]]
    assert enable_calls == []
    assert "No local host in the inventory yet" not in result.output


def test_cli_init_reports_enable_now_failure(runner, tmp_path, monkeypatch, interactive, _fake_local_machine):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    inv = tmp_path / "Homelab"
    first = runner.invoke(app, ["init", "--inventory", str(inv), "-y"])
    assert first.exit_code == 0, first.output
    _fake_local_machine.calls.clear()
    _fake_local_machine.sshd_active = False
    _fake_local_machine.reachable = False
    _fake_local_machine.enable_fails = True

    result = runner.invoke(
        app,
        ["init", "--lab-name", "Homelab", "--public-domain", "", "--internal-domain", "", "--snippet"],
        input="y\ny\n",  # go ahead: yes; start sshd now: yes
    )
    assert result.exit_code == 0, result.output
    assert "enable --now sshd failed" in result.output
    assert "Unit file sshd.service does not exist" in result.output


def test_cli_init_sshd_uninstalled_prints_install_hint_with_no_start_offer(
    runner, tmp_path, monkeypatch, interactive, _fake_local_machine
):
    _fake_local_machine.sshd_active = False
    _fake_local_machine.sshd_installed = False
    _fake_local_machine.reachable = False
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    result = runner.invoke(app, ["init", "--inventory", str(tmp_path / "Homelab"), "-y"])
    assert result.exit_code == 0, result.output
    assert "install openssh" in result.output
    assert "Start sshd now" not in result.output
    enable_calls = [c for c in _fake_local_machine.calls if c[:4] == ["sudo", "-n", "systemctl", "enable"]]
    assert enable_calls == []


def test_cli_init_yes_never_offers_to_start_sshd(runner, tmp_path, monkeypatch, interactive, _fake_local_machine):
    _fake_local_machine.sshd_active = False
    _fake_local_machine.reachable = False
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    result = runner.invoke(app, ["init", "--inventory", str(tmp_path / "Homelab"), "-y"])
    assert result.exit_code == 0, result.output
    assert "Start sshd now" not in result.output
    assert "sshd isn't active" in result.output
    enable_calls = [c for c in _fake_local_machine.calls if c[:4] == ["sudo", "-n", "systemctl", "enable"]]
    assert enable_calls == []


def test_cli_init_declined_fingerprint_is_not_recorded(runner, tmp_path, monkeypatch, interactive):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    inv = tmp_path / "Homelab"
    first = runner.invoke(app, ["init", "--inventory", str(inv), "-y"])
    assert first.exit_code == 0, first.output

    (inv / "hosts").mkdir(exist_ok=True)
    (inv / "hosts" / "laptop1.md").write_text("---\nbastet: host\ntype: laptop\nconnection: local\n---\n# laptop1\n")
    import subprocess as sp
    sp.run(["git", "-C", str(inv), "add", "."], check=True)
    sp.run(["git", "-C", str(inv), "-c", "user.name=T", "-c", "user.email=t@example.com",
           "commit", "-q", "-m", "add laptop1"], check=True)

    result = runner.invoke(
        app,
        ["init", "--lab-name", "Homelab", "--public-domain", "", "--internal-domain", "", "--snippet"],
        input="y\nn\n",  # go ahead: yes; trust the host key: no
    )
    assert result.exit_code == 0, result.output
    assert "host key not recorded" in result.output
    assert "ssh_host_key" not in (inv / "hosts" / "laptop1.md").read_text()


def test_cli_init_confirmed_fingerprint_is_recorded(runner, tmp_path, monkeypatch, interactive):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    inv = tmp_path / "Homelab"
    first = runner.invoke(app, ["init", "--inventory", str(inv), "-y"])
    assert first.exit_code == 0, first.output

    (inv / "hosts").mkdir(exist_ok=True)
    (inv / "hosts" / "laptop1.md").write_text("---\nbastet: host\ntype: laptop\nconnection: local\n---\n# laptop1\n")
    import subprocess as sp
    sp.run(["git", "-C", str(inv), "add", "."], check=True)
    sp.run(["git", "-C", str(inv), "-c", "user.name=T", "-c", "user.email=t@example.com",
           "commit", "-q", "-m", "add laptop1"], check=True)

    result = runner.invoke(
        app,
        ["init", "--lab-name", "Homelab", "--public-domain", "", "--internal-domain", "", "--snippet"],
        input="y\ny\n",  # go ahead: yes; trust the host key: yes
    )
    assert result.exit_code == 0, result.output
    assert "host key recorded" in result.output
    assert f"ssh_host_key: ssh-ed25519 {FAKE_HOST_KEYS[0].fingerprint}" in (inv / "hosts" / "laptop1.md").read_text()

    second = runner.invoke(app, ["init", "-y"])
    assert second.exit_code == 0, second.output
    assert "laptop1: host key already set up" in second.output
