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
    monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))


class FakeLocalSystem:
    def __init__(self):
        self.user_exists = False
        self.password = ""
        self.sudoers: str | None = None
        self.authorized_keys: str | None = None
        self.calls: list[list[str]] = []
        self.sshd_active = True
        self.sshd_installed = True
        self.reachable = True

    def scan(self, address: str = "127.0.0.1", port: int = 22):
        return FAKE_HOST_KEYS

    def __call__(self, argv: list[str]) -> ProcResult:
        self.calls.append(argv)
        if argv in (["systemctl", "cat", "sshd"], ["systemctl", "cat", "ssh"]):
            return ProcResult(0)
        if argv in (["systemctl", "is-active", "sshd"], ["systemctl", "is-active", "ssh"]):
            return ProcResult(0, "active\n")
        if argv == ["id", "bastet"]:
            return ProcResult(0 if self.user_exists else 1)
        if argv[:3] == ["sudo", "-n", "useradd"]:
            self.user_exists = True
            return ProcResult(0)
        if argv[:4] == ["sudo", "-n", "getent", "shadow"]:
            return ProcResult(0, "bastet:*:19000:0:99999:7:::\n")
        if argv == ["getent", "passwd", "bastet"]:
            return ProcResult(0, "bastet:x:1001:1001::/home/bastet:/bin/sh\n")
        if argv == ["getent", "group", "1001"]:
            return ProcResult(0, "bastet:x:1001:\n")
        if argv[:3] == ["sudo", "-n", "visudo"]:
            return ProcResult(0)
        if argv[:3] == ["sudo", "-n", "install"]:
            return ProcResult(0)
        return ProcResult(0)


@pytest.fixture(autouse=True)
def _fake_local_machine(monkeypatch):
    fake = FakeLocalSystem()
    monkeypatch.setattr(init_mod, "_runner", fake)
    monkeypatch.setattr(init_mod, "_sudo_validate", lambda: True)
    monkeypatch.setattr(init_mod, "_scan_local", fake.scan)
    return fake


@pytest.fixture
def interactive(monkeypatch):
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
        "alice",                 # bootstrap user
        "My Lab",                # lab name
        "example.com",           # public domain
        "-",                     # internal domain: none
        "",                      # run records: keep forever
        "y",                     # stylesheet
        "",                      # your SSH public key: skip
        "y",                     # go ahead
    ]) + "\n"
    result = runner.invoke(app, ["init", "--no-manage-this-machine"], input=answers)
    assert result.exit_code == 0, result.output
    assert load_config(cfg).inventory.path == tmp_path / "Lab"
    assert "name: My Lab" in (tmp_path / "Lab" / "Homelab.md").read_text()


def test_cli_init_declined_writes_nothing(runner, tmp_path, monkeypatch, interactive):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    answers = "\n".join([str(tmp_path / "Lab"), "", "new", "alice", "Homelab", "", "-", "", "y", "", "n"]) + "\n"
    result = runner.invoke(app, ["init", "--no-manage-this-machine"], input=answers)
    assert result.exit_code == 0
    assert not cfg.exists() and not (tmp_path / "Lab").exists()


def test_cli_init_builds_dashboard(runner, tmp_path, monkeypatch):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    result = runner.invoke(app, ["init", "--inventory", str(tmp_path / "Homelab"), "-y", "--manage-this-machine"])
    assert result.exit_code == 0, result.output
    assert "![[bastet dashboard]]" in (tmp_path / "Homelab" / "Homelab.md").read_text()
    assert (tmp_path / "Homelab" / "_bastet" / "bastet dashboard.md").exists()


def test_cli_init_prints_recovery_key_once_and_never_writes_it(runner, tmp_path, monkeypatch, interactive):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    result = runner.invoke(app, ["init", "--inventory", str(tmp_path / "Homelab"), "-y", "--manage-this-machine"])
    assert result.exit_code == 0, result.output
    assert "Recovery key: keep this offline" in result.output
    m = RECOVERY_RE.search(result.output)
    assert m, result.output
    key = m.group(0)
    assert result.output.count(key) == 1


def test_cli_init_flag_sets_up_this_machine(runner, tmp_path, monkeypatch, interactive, _fake_local_machine):
    monkeypatch.setenv("BASTET_CONFIG", str(tmp_path / "c" / "bastet.yml"))
    result = runner.invoke(app, ["init", "--inventory", str(tmp_path / "Homelab"), "-y", "--manage-this-machine"])
    assert result.exit_code == 0, result.output
    assert "created the local bastet user" in result.output


def _init_args(tmp_path, *extra):
    return ["init", "--inventory", str(tmp_path / "Homelab"), "--no-manage-this-machine", *extra]


def _interactive_answers(tmp_path, keep_days_answers):
    return "\n".join([
        "", "new", "alice", "Homelab", "", "-",   # remote, key, login, lab name, public domain, internal domain
        *keep_days_answers,
        "y",                                       # stylesheet
        "",                                        # your SSH public key: skip
        "y",                                       # go ahead
    ]) + "\n"


def test_init_yes_keeps_run_records_forever(runner, tmp_path, monkeypatch):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    result = runner.invoke(app, _init_args(tmp_path, "-y"))
    assert result.exit_code == 0, result.output
    assert "Keep run records" not in result.output
    assert "run records  kept forever" in result.output
    assert load_config(cfg).runs.keep_days is None


def test_init_keep_days_option(runner, tmp_path, monkeypatch):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    result = runner.invoke(app, _init_args(tmp_path, "--keep-days", "30", "-y"))
    assert result.exit_code == 0, result.output
    assert "run records  kept for 30 days" in result.output
    assert load_config(cfg).runs.keep_days == 30


def test_init_asks_and_enter_means_forever(runner, tmp_path, monkeypatch, interactive):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    result = runner.invoke(app, _init_args(tmp_path), input=_interactive_answers(tmp_path, [""]))
    assert result.exit_code == 0, result.output
    assert "Keep run records for how many days? (Enter to keep them forever)" in result.output
    assert "run records  kept forever" in result.output
    assert load_config(cfg).runs.keep_days is None
    assert "keep_days" in cfg.read_text()


def test_init_reasks_on_a_bad_answer(runner, tmp_path, monkeypatch, interactive):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    result = runner.invoke(app, _init_args(tmp_path), input=_interactive_answers(tmp_path, ["abc", "0", "45"]))
    assert result.exit_code == 0, result.output
    assert result.output.count("Enter a number of days, or press Enter to keep every run.") == 2
    assert "run records  kept for 45 days" in result.output
    assert load_config(cfg).runs.keep_days == 45


def test_init_with_an_existing_config_does_not_ask(runner, tmp_path, monkeypatch):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    first = runner.invoke(app, _init_args(tmp_path, "--keep-days", "30", "-y"))
    assert first.exit_code == 0, first.output
    before = cfg.read_text()
    second = runner.invoke(app, _init_args(tmp_path, "-y"))
    assert second.exit_code == 0, second.output
    assert "Keep run records" not in second.output and "run records  " not in second.output
    assert "or how long run records are kept" in second.output
    assert "--keep-days is ignored" not in second.output
    third = runner.invoke(app, _init_args(tmp_path, "--keep-days", "5", "-y"))
    assert third.exit_code == 0, third.output
    assert third.output.count("--keep-days is ignored; edit runs.keep_days") == 1
    assert cfg.read_text() == before
    assert cfg.read_text() == before
