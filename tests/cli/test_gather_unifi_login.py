from pathlib import Path

import pytest
from test_gather_unifi import DumpRunner, unifi_lab  # noqa: F401  (the fixture and the fake device)

import bastet.cli.gather as gather_mod
from bastet.cli.app import app
from bastet.core.errors import AuthFailed


def with_key(root: Path, tmp_path: Path) -> Path:
    key = tmp_path / "bastet_key"
    key.write_text("fake private key\n")
    cfg = tmp_path / "bastet.yml"
    cfg.write_text(cfg.read_text() + f"ssh:\n  key: {key}\n  bootstrap_user: admin\n")
    return key


class Attempts:
    """Records every login target and refuses the ones the test names."""

    def __init__(self, refuse_users=()):
        self.targets, self.refuse_users = [], set(refuse_users)

    def __call__(self, target):
        self.targets.append((target.user, target.key))
        refuse = target.user in self.refuse_users

        class Runner(DumpRunner):
            def run(self_, script, *, timeout=120):
                if refuse:
                    raise AuthFailed("refused")
                return super().run(script, timeout=timeout)

        return Runner(target.address)


@pytest.fixture
def attempts(monkeypatch):
    seen = Attempts()
    monkeypatch.setattr(gather_mod, "ssh_runner", seen)
    return seen


def test_unifi_is_tried_as_bastet_with_the_key_first(runner, unifi_lab, tmp_path, attempts):  # noqa: F811
    key = with_key(unifi_lab, tmp_path)
    result = runner.invoke(app, ["run", "-g", "uxg", "-y"])
    assert result.exit_code == 0, result.output
    assert attempts.targets[0] == ("bastet", key)
    assert all(user == "bastet" for user, _ in attempts.targets)


def test_a_refused_bastet_login_falls_back_to_the_old_login(runner, unifi_lab, tmp_path, monkeypatch):  # noqa: F811
    key = with_key(unifi_lab, tmp_path)
    seen = Attempts(refuse_users={"bastet"})
    monkeypatch.setattr(gather_mod, "ssh_runner", seen)
    result = runner.invoke(app, ["run", "-g", "uxg", "-y"])
    assert result.exit_code == 0, result.output
    assert seen.targets[0] == ("bastet", key)
    assert ("admin", None) in seen.targets  # bootstrap_user, no key: today's behaviour


def test_without_a_key_only_the_old_login_is_used(runner, unifi_lab, tmp_path, attempts):  # noqa: F811
    cfg = tmp_path / "bastet.yml"
    cfg.write_text(cfg.read_text() + "ssh:\n  bootstrap_user: admin\n")
    result = runner.invoke(app, ["run", "-g", "uxg", "-y"])
    assert result.exit_code == 0, result.output
    assert attempts.targets and all(target == ("admin", None) for target in attempts.targets)
