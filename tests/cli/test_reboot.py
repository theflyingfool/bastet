import pytest

import bastet.cli.reboot as reboot_mod
from bastet.cli.reboot import RebootPlan, perform_reboot, reboot_decision
from bastet.core.errors import BastetError
from bastet.core.remote import CommandResult
from bastet.engine.packages import Reboot


class Box:
    """A fake host with a boot id: needs a reboot until it really reboots; `slow` polls still see the old boot."""

    def __init__(self, needed=True, comes_back=True, refuse=False, slow=0):
        self.needed, self.comes_back, self.refuse, self.slow = needed, comes_back, refuse, slow
        self.rebooted, self.boot = False, "boot-1"

    def run(self, script, *, timeout=120):
        if "systemctl reboot" in script:
            if self.refuse:
                return CommandResult("", "needs root: sudo -n is not available", 126)
            self.rebooted, self.needed = True, False
            return CommandResult("", "Connection closed", 255)
        if "boot_id" in script:
            if self.rebooted and self.slow:
                self.slow -= 1
                return CommandResult("boot-1\n", "", 0)
            if self.rebooted and not self.comes_back:
                return CommandResult("", "", 255)
            return CommandResult(("boot-2" if self.rebooted else "boot-1") + "\n", "", 0)
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


def handle_reboot(runner, target, doc, reboots, *, yes, connect_again, apply_failed=False, sleep=None, clock=None):
    """Test-only helper: drives `reboot_decision` + `perform_reboot` the way `_run` will, so the
    existing scenarios below keep exercising both halves of the split together."""
    plan = reboot_decision(runner, target, doc, reboots, yes=yes, apply_failed=apply_failed)
    if plan is None or isinstance(plan, str):
        return plan
    kwargs = {}
    if sleep is not None:
        kwargs["sleep"] = sleep
    if clock is not None:
        kwargs["clock"] = clock
    return perform_reboot(plan, connect_again, **kwargs)


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


def test_failed_apply_never_reboots(box):
    msg = handle_reboot(box, None, Doc(), batches("auto"), yes=True, connect_again=lambda: box, apply_failed=True)
    assert "apply had failures" in msg and not box.rebooted


def test_refused_reboot_is_an_error(box):
    box.refuse = True
    with pytest.raises(BastetError, match="reboot refused"):
        handle_reboot(box, None, Doc(), batches("auto"), yes=True, connect_again=lambda: box, **ticks())


def test_waits_for_a_new_boot_not_just_ssh(box):
    box.slow = 3  # sshd still answers from the old boot for a while
    msg = handle_reboot(box, None, Doc(), batches("auto"), yes=True, connect_again=lambda: box, **ticks())
    assert msg.startswith("box: rebooted, back after") and box.slow == 0


# --- the split itself ---


def test_decision_returns_a_plan_when_it_will_reboot(box):
    plan = reboot_decision(box, "target", Doc(), batches("auto"), yes=True)
    assert isinstance(plan, RebootPlan)
    assert plan.host == "box" and plan.target == "target" and not box.rebooted


def test_decision_asks_once_on_policy_ask(box, monkeypatch):
    asked = []
    monkeypatch.setattr("typer.confirm", lambda *a, **k: asked.append(a) or True)
    plan = reboot_decision(box, None, Doc(), batches("ask"), yes=False)
    assert isinstance(plan, RebootPlan) and len(asked) == 1


def test_perform_reboot_runs_the_plan(box):
    plan = reboot_decision(box, None, Doc(), batches("auto"), yes=True)
    msg = perform_reboot(plan, lambda: box, **ticks())
    assert box.rebooted and msg.startswith("box: rebooted, back after")
