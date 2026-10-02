"""After apply: reboot a host that needs it, as its packages role's reboot policy says."""

from __future__ import annotations

import time

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


def handle_reboot(runner, target, doc, reboots: list[Reboot], *, yes: bool, connect_again,
                  sleep=time.sleep, clock=time.monotonic) -> str | None:
    if not reboots:
        return None
    policy, timeout = reboots[0].policy, reboots[0].timeout
    needed, why = reboot_needed(runner, doc.name, reboots[:1])
    if not needed:
        return None
    host = doc.name
    if doc.data.get("connection") == "local":
        return f"{host}: reboot needed ({why}); reboot this machine yourself"
    if policy == "never":
        return f"{host}: reboot needed ({why}); policy is never"
    if policy == "ask":
        if yes:
            return (f"{host}: reboot needed ({why}); not rebooting under -y (policy ask). "
                    "Run without -y, or set reboot: auto")
        if not typer.confirm(f"Reboot {host} now ({why})?", default=False):
            return f"{host}: reboot needed ({why}); not rebooted"
    try:
        runner.run(exec_script(["systemctl reboot"], root=True, mark=new_mark()), timeout=30)
    except BastetError:
        pass  # the connection dropping is the reboot happening
    if target is not None:
        close_master(target)
    start = clock()
    sleep(POLL)
    while True:
        try:
            runner = connect_again()
            if runner.run("true", timeout=15).returncode == 0:
                break
        except BastetError:
            pass
        if clock() - start >= timeout:
            raise BastetError(f"{host}: didn't come back within {timeout}s after the reboot")
        sleep(POLL)
    back = int(clock() - start)
    still, why_now = reboot_needed(runner, host, reboots[:1])
    return f"{host}: rebooted, but a reboot is still needed ({why_now})" if still else f"{host}: rebooted, back after {back}s"
