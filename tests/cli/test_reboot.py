import pytest

import bastet.cli.reboot as reboot_mod
from bastet.cli.reboot import handle_reboot
from bastet.core.errors import BastetError
from bastet.core.remote import CommandResult
from bastet.engine.packages import Reboot


class Box:
    """A fake host: needs a reboot until `systemctl reboot` arrives; then answers `true` if it comes back."""

    def __init__(self, needed=True, comes_back=True):
        self.needed, self.comes_back, self.rebooted = needed, comes_back, False

    def run(self, script, *, timeout=120):
        if "systemctl reboot" in script:
            self.rebooted, self.needed = True, False
            return CommandResult("", "Connection closed", 255)
        return CommandResult("", "", 0 if self.comes_back else 255)


@pytest.fixture
def box(monkeypatch):
    b = Box()
    monkeypatch.setattr(reboot_mod, "reboot_needed", lambda runner, host, reboots: (b.needed, "kernel" if b.needed else ""))
    return b


class Doc:
    def __init__(self, local=False):
        self.name, self.data = "box", ({"connection": "local"} if local else {})


def batches(policy):
    return [Reboot(policy=policy, timeout=30)]


def ticks():
    t = iter(range(0, 1000, 5))
    return dict(sleep=lambda s: None, clock=lambda: next(t))


def test_nothing_needed(box):
    box.needed = False
    assert handle_reboot(box, None, Doc(), batches("auto"), yes=True, connect_again=lambda: box) is None


def test_local_host_never_rebooted(box):
    msg = handle_reboot(box, None, Doc(local=True), batches("auto"), yes=True, connect_again=lambda: box)
    assert "reboot this machine yourself" in msg and not box.rebooted


def test_never_only_reports(box):
    msg = handle_reboot(box, None, Doc(), batches("never"), yes=False, connect_again=lambda: box)
    assert "policy is never" in msg and not box.rebooted


def test_ask_under_yes_does_not_reboot(box):
    msg = handle_reboot(box, None, Doc(), batches("ask"), yes=True, connect_again=lambda: box)
    assert "not rebooting under -y" in msg and not box.rebooted


def test_auto_reboots_and_waits(box):
    msg = handle_reboot(box, None, Doc(), batches("auto"), yes=True, connect_again=lambda: box, **ticks())
    assert box.rebooted and msg.startswith("box: rebooted, back after")


def test_auto_times_out(box):
    box.comes_back = False
    with pytest.raises(BastetError, match="didn't come back within 30s"):
        handle_reboot(box, None, Doc(), batches("auto"), yes=True, connect_again=lambda: box, **ticks())
