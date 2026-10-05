"""Apply's reboot step, not a command of its own: after apply, reboot a host that needs it, as its
packages role's reboot policy says.

Split in two so the asking (inventory order, main thread) and the actual reboot (parallel, through
`run_parallel`) can happen in different phases: `reboot_decision` keeps every rule and message and
does the one question it needs; `perform_reboot` does the reboot and waits for the host to come back.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import typer

from bastet.core.errors import BastetError
from bastet.core.remote import close_master
from bastet.engine.packages import Reboot
from bastet.engine.run import Batch, run_host
from bastet.engine.script import exec_script, new_mark

POLL = 5


def reboot_needed(runner, host: str, reboots: list[Reboot]) -> tuple[bool, str]:
    run = run_host(runner, host, [Batch("reboot", list(reboots))], apply=False)
    item = run.items[0]
    if item.status == "failed":
        raise BastetError(f"{host}: couldn't tell whether a reboot is needed: {item.error}")
    return bool(item.current.get("needed")), str(item.current.get("why") or "")


def _boot_id(runner) -> str | None:
    try:
        res = runner.run("cat /proc/sys/kernel/random/boot_id", timeout=15)
    except BastetError:
        return None
    return res.stdout.strip() or None if res.returncode == 0 else None


@dataclass
class RebootPlan:
    """A host that's actually going to be rebooted: everything `perform_reboot` needs to do it."""

    host: str
    runner: object
    target: object
    reboots: list[Reboot]
    timeout: int


def reboot_decision(
    runner, target, doc, reboots: list[Reboot], *, yes: bool, apply_failed: bool = False
) -> RebootPlan | str | None:
    """Decide whether a host should be rebooted, asking if its policy needs it (main thread only).

    None: no reboot needed. A string: a message to report, no reboot happens. A `RebootPlan`:
    hand it to `perform_reboot` (which can run in a worker, since it asks nothing).
    """
    if not reboots:
        return None
    policy, timeout = reboots[0].policy, reboots[0].timeout
    needed, why = reboot_needed(runner, doc.name, reboots[:1])
    if not needed:
        return None
    host = doc.name
    if doc.data.get("connection") == "local":
        return f"{host}: reboot needed ({why}); reboot this machine yourself"
    if apply_failed:
        return f"{host}: reboot needed ({why}); not rebooting because apply had failures — fix them first"
    if policy == "never":
        return f"{host}: reboot needed ({why}); policy is never"
    if policy == "ask":
        if yes:
            return (f"{host}: reboot needed ({why}); not rebooting under -y (policy ask). "
                    "Run without -y, or set reboot: auto")
        if not typer.confirm(f"Reboot {host} now ({why})?", default=False):
            return f"{host}: reboot needed ({why}); not rebooted"
    return RebootPlan(host, runner, target, reboots[:1], timeout)


def perform_reboot(plan: RebootPlan, connect_again, sleep=time.sleep, clock=time.monotonic) -> str:
    """Reboot a host already decided on, and wait for it to come back. Safe to run in a worker thread."""
    host, runner, target, reboots, timeout = plan.host, plan.runner, plan.target, plan.reboots, plan.timeout
    before = _boot_id(runner)
    try:
        res = runner.run(exec_script(["systemctl reboot"], root=True, mark=new_mark()), timeout=30)
    except BastetError:
        res = None  # the connection dropping is the reboot happening
    if res is not None and res.returncode not in (0, 255):
        tail = (res.stderr.strip().splitlines() or [f"exit status {res.returncode}"])[-1]
        raise BastetError(f"{host}: reboot refused: {tail}")
    if target is not None:
        close_master(target)
    start = clock()
    sleep(POLL)
    while True:
        try:
            runner = connect_again()
            now = _boot_id(runner)
            if now is not None and now != before:  # a new boot, not sshd still answering during shutdown
                break
        except BastetError:
            pass
        if clock() - start >= timeout:
            raise BastetError(f"{host}: didn't come back within {timeout}s after the reboot")
        sleep(POLL)
    back = int(clock() - start)
    still, why_now = reboot_needed(runner, host, reboots)
    return f"{host}: rebooted, but a reboot is still needed ({why_now})" if still else f"{host}: rebooted, back after {back}s"
