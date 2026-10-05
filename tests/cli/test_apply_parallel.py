"""Check and apply run their hosts through core.parallel: a parallel check, one question before
applying, guests waiting for their node, and reboots asked serially but run in parallel."""

import threading
import time
from types import SimpleNamespace

import pytest

import bastet.cli.reboot as reboot_mod
import bastet.cli.run as run_mod
from bastet.cli.app import app
from bastet.core.errors import BastetError
from bastet.engine.model import FieldChange
from bastet.engine.packages import Reboot
from bastet.engine.run import Batch, HostRun, Item


class _Resource:
    family = "Other"
    secret = False

    def __init__(self, label="thing"):
        self.label = label


def _applied(role="files"):
    return [SimpleNamespace(role=SimpleNamespace(name=role), sources=[])]


def _batches(resources=None):
    return [Batch("files", resources if resources is not None else [_Resource()])]


def _check_run(host: str, pending: int, failed: int = 0) -> HostRun:
    items = [
        Item(_Resource(f"{host}-p{i}"), ["files"], [], status="would-change",
             changes=[FieldChange("content", "(absent)", "x")])
        for i in range(pending)
    ]
    items += [Item(_Resource(f"{host}-f{i}"), ["files"], [], status="failed", error="boom") for i in range(failed)]
    return HostRun(host, False, items)


def _apply_run(host: str, changed: int, failed: int = 0) -> HostRun:
    items = [Item(_Resource(f"{host}-c{i}"), ["files"], [], status="changed",
                  changes=[FieldChange("content", "(absent)", "x")]) for i in range(changed)]
    items += [Item(_Resource(f"{host}-f{i}"), ["files"], [], status="failed", error="boom") for i in range(failed)]
    return HostRun(host, True, items)


def make_host(inventory, name, *, runs_on=None, type_="vm"):
    extra = f'\nruns_on: "[[{runs_on}]]"' if runs_on else ""
    (inventory / "hosts" / f"{name}.md").write_text(f"---\nbastet: host\ntype: {type_}{extra}\n---\n# {name}\n")


def plan_stub(pending_by_host: dict[str, int], reboots_by_host: dict[str, list] | None = None):
    reboots_by_host = reboots_by_host or {}

    def plan_for(ctx, doc, roles, updates=False):
        resources = [_Resource() for _ in range(max(pending_by_host.get(doc.name, 0), 1))]
        resources += reboots_by_host.get(doc.name, [])
        return _applied(), _batches(resources)
    return plan_for


class FakeRunner:
    def __init__(self, host):
        self.host = host

    def run(self, script, *, timeout=120):
        from bastet.core.remote import CommandResult
        return CommandResult("", "", 0)


def connect_stub(barrier=None, delay=0.0):
    def connect(ctx, doc, tmp, *, yes):
        if barrier is not None:
            barrier.wait(timeout=2)
        if delay:
            time.sleep(delay)
        return FakeRunner(doc.name), SimpleNamespace(control_path=None)
    return connect


@pytest.fixture
def three_hosts(inventory):
    make_host(inventory, "git1")
    make_host(inventory, "pve2")
    return inventory


# --- parallel check ---


def test_check_runs_hosts_concurrently(runner, three_hosts, monkeypatch):
    barrier = threading.Barrier(3, timeout=2)
    monkeypatch.setattr(run_mod, "plan_for", plan_stub({}))
    monkeypatch.setattr(run_mod, "connect", connect_stub(barrier))
    monkeypatch.setattr(run_mod, "run_host", lambda runner_, host, batches, **kw: _check_run(host, 0))

    result = runner.invoke(app, ["check", "-j", "3"])

    assert result.exit_code == 0, result.output
    for host in ("pve1", "pve2", "git1"):
        assert host in result.output


# --- the one question ---


def _apply_setup(monkeypatch, pending, calls):
    monkeypatch.setattr(run_mod, "plan_for", plan_stub(pending))
    monkeypatch.setattr(run_mod, "connect", connect_stub())

    def run_host(runner_, host, batches, *, apply=False, **kw):
        if not apply:
            return _check_run(host, pending.get(host, 0))
        calls.append(host)
        return _apply_run(host, pending.get(host, 0))

    monkeypatch.setattr(run_mod, "run_host", run_host)


def test_question_yes_applies_all(runner, three_hosts, monkeypatch):
    calls: list[str] = []
    _apply_setup(monkeypatch, {"pve1": 2, "pve2": 1, "git1": 1}, calls)
    result = runner.invoke(app, ["apply"], input="y\n")
    assert result.exit_code == 0, result.output
    assert set(calls) == {"pve1", "pve2", "git1"}


def test_question_no_applies_none(runner, three_hosts, monkeypatch):
    calls: list[str] = []
    _apply_setup(monkeypatch, {"pve1": 2, "pve2": 1, "git1": 1}, calls)
    result = runner.invoke(app, ["apply"], input="n\n")
    assert result.exit_code == 0, result.output
    assert calls == []
    assert "nothing applied" in result.output


def test_question_numbers_applies_only_those(runner, three_hosts, monkeypatch):
    # inventory order is alphabetical: git1, pve1, pve2 -- 1,3 picks git1 and pve2.
    calls: list[str] = []
    _apply_setup(monkeypatch, {"pve1": 2, "pve2": 1, "git1": 1}, calls)
    result = runner.invoke(app, ["apply"], input="1,3\n")
    assert result.exit_code == 0, result.output
    assert set(calls) == {"git1", "pve2"}
    assert "pve1: nothing applied" in result.output


def test_question_bad_input_then_valid(runner, three_hosts, monkeypatch):
    # inventory order is alphabetical: git1, pve1, pve2 -- "2" picks pve1.
    calls: list[str] = []
    _apply_setup(monkeypatch, {"pve1": 2, "pve2": 1, "git1": 1}, calls)
    result = runner.invoke(app, ["apply"], input="bogus\n2\n")
    assert result.exit_code == 0, result.output
    assert calls == ["pve1"]


def test_question_dash_y_applies_all_without_asking(runner, three_hosts, monkeypatch):
    calls: list[str] = []
    _apply_setup(monkeypatch, {"pve1": 2, "pve2": 1, "git1": 1}, calls)
    result = runner.invoke(app, ["apply", "-y"])
    assert result.exit_code == 0, result.output
    assert set(calls) == {"pve1", "pve2", "git1"}
    assert "Changes to apply" not in result.output


# --- guests wait for their node ---


@pytest.fixture
def node_and_guest(inventory):
    make_host(inventory, "guest1", runs_on="pve1")
    return inventory


def test_guest_starts_after_its_node(runner, node_and_guest, monkeypatch):
    order: list[str] = []
    lock = threading.Lock()
    pending = {"pve1": 1, "guest1": 1}
    monkeypatch.setattr(run_mod, "plan_for", plan_stub(pending))
    monkeypatch.setattr(run_mod, "connect", connect_stub())

    def run_host(runner_, host, batches, *, apply=False, **kw):
        if not apply:
            return _check_run(host, pending[host])
        with lock:
            order.append(f"{host}-start")
        if host == "pve1":
            time.sleep(0.05)
        with lock:
            order.append(f"{host}-end")
        return _apply_run(host, pending[host])

    monkeypatch.setattr(run_mod, "run_host", run_host)
    result = runner.invoke(app, ["apply", "-y"])
    assert result.exit_code == 0, result.output
    assert order.index("pve1-end") < order.index("guest1-start")


def test_guest_skipped_when_node_fails(runner, node_and_guest, monkeypatch):
    pending = {"pve1": 1, "guest1": 1}
    monkeypatch.setattr(run_mod, "plan_for", plan_stub(pending))
    monkeypatch.setattr(run_mod, "connect", connect_stub())

    def run_host(runner_, host, batches, *, apply=False, **kw):
        if not apply:
            return _check_run(host, pending[host])
        if host == "pve1":
            raise ValueError("pve1 blew up")  # a worker error, not just failed items: status "error"
        raise AssertionError("guest1 must not run after its node failed")

    monkeypatch.setattr(run_mod, "run_host", run_host)
    result = runner.invoke(app, ["apply", "-y"])
    assert result.exit_code == 1
    assert "its node pve1 failed" in result.output


def test_guest_skipped_when_node_apply_has_failed_items(runner, node_and_guest, monkeypatch):
    """A node's apply can finish (no exception) with failed items -- `done.ok` is False, not a
    worker error -- and its guests must still be skipped, with the node's own result still shown."""
    pending = {"pve1": 1, "guest1": 1}
    monkeypatch.setattr(run_mod, "plan_for", plan_stub(pending))
    monkeypatch.setattr(run_mod, "connect", connect_stub())

    def run_host(runner_, host, batches, *, apply=False, **kw):
        if not apply:
            return _check_run(host, pending[host])
        if host == "pve1":
            return _apply_run(host, 0, failed=1)
        raise AssertionError("guest1 must not run after its node failed")

    monkeypatch.setattr(run_mod, "run_host", run_host)
    result = runner.invoke(app, ["apply", "-y"])
    assert result.exit_code == 1
    assert "its node pve1 failed" in result.output
    assert "HOST: pve1" in result.output and "1 failed" in result.output


# --- a worker raising an unexpected error ---


def test_unexpected_error_reported_others_continue(runner, three_hosts, monkeypatch):
    pending = {"pve1": 1, "pve2": 1, "git1": 1}
    calls: list[str] = []
    monkeypatch.setattr(run_mod, "plan_for", plan_stub(pending))
    monkeypatch.setattr(run_mod, "connect", connect_stub())

    def run_host(runner_, host, batches, *, apply=False, **kw):
        if not apply:
            return _check_run(host, pending[host])
        if host == "pve2":
            raise ValueError("kaboom")
        calls.append(host)
        return _apply_run(host, pending[host])

    monkeypatch.setattr(run_mod, "run_host", run_host)
    result = runner.invoke(app, ["apply", "-y"])
    assert result.exit_code == 1
    assert "pve2: unexpected error: ValueError: kaboom" in result.output
    assert set(calls) == {"pve1", "git1"}


# --- reboot: asked serially, rebooted in parallel, node after its guest ---


def test_reboot_asks_serially_and_node_waits_for_guest(runner, node_and_guest, monkeypatch):
    pending = {"pve1": 0, "guest1": 0}
    reboots = {"pve1": [Reboot(policy="ask", timeout=30)], "guest1": [Reboot(policy="ask", timeout=30)]}
    monkeypatch.setattr(run_mod, "plan_for", plan_stub(pending, reboots))
    monkeypatch.setattr(run_mod, "connect", connect_stub())
    monkeypatch.setattr(run_mod, "run_host", lambda runner_, host, batches, **kw: _check_run(host, 0))
    monkeypatch.setattr(reboot_mod, "reboot_needed", lambda runner_, host, rb: (True, "kernel"))

    asked: list[str] = []

    def confirm(text, **kw):
        asked.append(text)
        assert threading.current_thread() is threading.main_thread()
        return True

    monkeypatch.setattr("typer.confirm", confirm)

    order: list[str] = []
    lock = threading.Lock()

    def perform_reboot(plan, connect_again, sleep=None, clock=None):
        with lock:
            order.append(f"{plan.host}-start")
        if plan.host == "guest1":
            time.sleep(0.05)
        with lock:
            order.append(f"{plan.host}-end")
        return f"{plan.host}: rebooted, back after 1s"

    monkeypatch.setattr(run_mod, "perform_reboot", perform_reboot)

    result = runner.invoke(app, ["apply"])

    assert result.exit_code == 0, result.output
    assert len(asked) == 2  # one per host, in inventory order, both on the main thread
    assert order.index("guest1-end") < order.index("pve1-start")
    assert "pve1: rebooted" in result.output and "guest1: rebooted" in result.output


# --- Ctrl-C mid-check ---


def test_ctrl_c_reports_not_started_closes_masters_and_still_refreshes(runner, three_hosts, monkeypatch):
    pending = {"pve1": 0, "pve2": 0, "git1": 0}
    monkeypatch.setattr(run_mod, "plan_for", plan_stub(pending))
    monkeypatch.setattr(run_mod, "connect", connect_stub())
    monkeypatch.setattr(run_mod, "run_host", lambda runner_, host, batches, **kw: _check_run(host, 0))

    closed: list[object] = []
    monkeypatch.setattr(run_mod, "close_master", lambda target: closed.append(target))

    refreshed = []
    monkeypatch.setattr(run_mod, "refresh_generated", lambda ctx, **kw: refreshed.append(True) or 0)

    # Only the first host to finish gets interrupted -- with `-j 1` the other two are still
    # waiting for a slot, so `run_parallel` reports them "not started" once it stops admitting.
    triggered = {"done": False}
    real_render = run_mod.render_host

    def render_host(run, *, full):
        if not triggered["done"]:
            triggered["done"] = True
            raise KeyboardInterrupt()
        return real_render(run, full=full)

    monkeypatch.setattr(run_mod, "render_host", render_host)

    result = runner.invoke(app, ["check", "-j", "1"])

    assert result.exit_code == 1
    not_started = [line for line in result.output.splitlines() if "not started" in line]
    assert len(not_started) == 2
    assert len(closed) == 1  # only the host that actually connected ever needs its master closed
    assert refreshed == [True]


# --- Ctrl-C mid-apply: the running host must stop at the next item, not run to completion ---


def test_ctrl_c_during_apply_stops_later_items_on_that_host(runner, inventory, tmp_path, monkeypatch):
    from bastet.core.remote import LocalRunner
    from engine_fakes import Flag

    a, b = tmp_path / "a", tmp_path / "b"

    class StoppingRunner(LocalRunner):
        """Its first fix (writing `a`) sets the global stop flag, as a real Ctrl-C would have by
        the time the engine checks `should_stop()` before the next item."""

        def run(self, script, timeout=120):
            res = super().run(script, timeout=timeout)
            # Only the *fix* script actually redirects into `a` (the read/check script just `cat`s
            # it inside a printf-wrapped probe) -- match that, not every script that mentions the path.
            if f"> {a}" in script:
                from bastet.core.parallel import _stop_event
                _stop_event.set()
            return res

    def plan_for(ctx, doc, roles, updates=False):
        return _applied(), _batches([Flag(path=str(a), value="1"), Flag(path=str(b), value="2")])

    monkeypatch.setattr(run_mod, "plan_for", plan_for)
    monkeypatch.setattr(
        run_mod, "connect",
        lambda ctx, doc, tmp, *, yes: (StoppingRunner(), SimpleNamespace(control_path=None)),
    )

    result = runner.invoke(app, ["apply", "pve1", "-y"])

    assert result.exit_code == 1, result.output
    assert a.read_text() == "1"
    assert not b.exists()
    assert "stopped (Ctrl-C)" in result.output


def test_reboot_decision_error_is_one_hosts_red_line_others_still_reboot(runner, three_hosts, monkeypatch):
    """A BastetError from reboot_decision (e.g. the reboot-status probe failed, or the connection
    dropped) must be that one host's red line, not an exception that aborts the whole run -- the
    other hosts' reboot decisions, their reboots, and phase 7 (notes, summary, refresh) must still
    happen."""
    pending = {"pve1": 0, "pve2": 0, "git1": 0}
    reboots = {
        "pve1": [Reboot(policy="auto", timeout=30)],
        "pve2": [Reboot(policy="auto", timeout=30)],
        "git1": [],
    }
    monkeypatch.setattr(run_mod, "plan_for", plan_stub(pending, reboots))
    monkeypatch.setattr(run_mod, "connect", connect_stub())
    monkeypatch.setattr(run_mod, "run_host", lambda runner_, host, batches, **kw: _check_run(host, 0))

    def reboot_needed(runner_, host, rb):
        if host == "pve1":
            raise BastetError(f"{host}: couldn't tell whether a reboot is needed: boom")
        return (True, "kernel")

    monkeypatch.setattr(reboot_mod, "reboot_needed", reboot_needed)

    rebooted: list[str] = []

    def perform_reboot(plan, connect_again, sleep=None, clock=None):
        rebooted.append(plan.host)
        return f"{plan.host}: rebooted, back after 1s"

    monkeypatch.setattr(run_mod, "perform_reboot", perform_reboot)

    refreshed = []
    monkeypatch.setattr(run_mod, "refresh_generated", lambda ctx, **kw: refreshed.append(True) or 0)

    result = runner.invoke(app, ["apply", "-y"])

    assert result.exit_code == 1  # pve1 failed
    assert "pve1: couldn't tell whether a reboot is needed: boom" in result.output
    assert rebooted == ["pve2"]  # pve2's reboot still happens
    assert "pve2: rebooted" in result.output
    assert refreshed == [True]  # phase 7 still runs


def test_runs_on_loop_warns_and_does_not_hang(runner, inventory, monkeypatch):
    """A `runs_on` cycle must not hang apply -- the loop is broken and reported, and every host
    still runs."""
    make_host(inventory, "ct-a", runs_on="ct-b")
    make_host(inventory, "ct-b", runs_on="ct-a")
    pending = {"ct-a": 1, "ct-b": 1}
    monkeypatch.setattr(run_mod, "plan_for", plan_stub(pending))
    monkeypatch.setattr(run_mod, "connect", connect_stub())

    def run_host(runner_, host, batches, *, apply=False, **kw):
        if not apply:
            return _check_run(host, pending[host])
        return _apply_run(host, pending[host])

    monkeypatch.setattr(run_mod, "run_host", run_host)

    captured: dict = {}

    def target():
        captured["result"] = runner.invoke(app, ["apply", "ct-a", "ct-b", "-y"])

    t = threading.Thread(target=target)
    t.start()
    t.join(timeout=10)
    assert not t.is_alive(), "apply hung on a runs_on cycle"

    result = captured["result"]
    assert result.exit_code == 0, result.output
    assert "runs_on loop: ct-a → ct-b → ct-a; ignoring it for ordering" in result.output
    assert "HOST: ct-a" in result.output and "HOST: ct-b" in result.output


def test_roles_line_is_per_host_inside_its_check_block_with_dash_j_2(runner, three_hosts, monkeypatch):
    """The `roles: …` line must say which host it's for, and sit inside that host's own check
    block (right before its rendered check), not be printed up front for every host."""
    monkeypatch.setattr(run_mod, "plan_for", plan_stub({}))
    monkeypatch.setattr(run_mod, "connect", connect_stub())
    monkeypatch.setattr(run_mod, "run_host", lambda runner_, host, batches, **kw: _check_run(host, 0))

    result = runner.invoke(app, ["check", "pve2", "git1", "-j", "2"])

    assert result.exit_code == 0, result.output
    for host in ("pve2", "git1"):
        line = f"{host}: roles: files ()"
        assert line in result.output
        host_block_start = result.output.index(f"HOST: {host}")
        role_line_index = result.output.index(line)
        # the roles line comes right before this host's own HOST: block, not before every host's
        assert role_line_index < host_block_start
        assert host_block_start - role_line_index < 100
