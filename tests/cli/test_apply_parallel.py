"""Check and apply run their hosts through core.parallel: a parallel check, one question before
applying, guests waiting for their node, and reboots asked serially but run in parallel."""

import threading
from types import SimpleNamespace

import pytest

import bastet.cli.reboot as reboot_mod
import bastet.cli.run as run_mod
from bastet.cli.app import app
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


def connect_stub(barrier=None):
    def connect(ctx, doc, tmp, *, yes):
        if barrier is not None:
            barrier.wait(timeout=0.2)
        return FakeRunner(doc.name), SimpleNamespace(control_path=None)
    return connect


@pytest.fixture
def three_hosts(inventory):
    make_host(inventory, "git1")
    make_host(inventory, "pve2")
    return inventory


def test_check_runs_hosts_concurrently(runner, three_hosts, monkeypatch):
    barrier = threading.Barrier(3, timeout=0.2)
    monkeypatch.setattr(run_mod, "plan_for", plan_stub({}))
    monkeypatch.setattr(run_mod, "connect", connect_stub(barrier))
    monkeypatch.setattr(run_mod, "run_host", lambda runner_, host, batches, **kw: _check_run(host, 0))

    result = runner.invoke(app, ["run", "-c", "-j", "3"])

    assert result.exit_code == 0, result.output
    for host in ("pve1", "pve2", "git1"):
        assert host in result.output


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
    result = runner.invoke(app, ["run"], input="y\n")
    assert result.exit_code == 0, result.output
    assert set(calls) == {"pve1", "pve2", "git1"}


def test_question_dash_y_applies_all_without_asking(runner, three_hosts, monkeypatch):
    calls: list[str] = []
    _apply_setup(monkeypatch, {"pve1": 2, "pve2": 1, "git1": 1}, calls)
    result = runner.invoke(app, ["run", "-y"])
    assert result.exit_code == 0, result.output
    assert set(calls) == {"pve1", "pve2", "git1"}
    assert "Changes to apply" not in result.output


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
        with lock:
            order.append(f"{host}-end")
        return _apply_run(host, pending[host])

    monkeypatch.setattr(run_mod, "run_host", run_host)
    result = runner.invoke(app, ["run", "-y"])
    assert result.exit_code == 0, result.output
    assert order.index("pve1-end") < order.index("guest1-start")


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
    result = runner.invoke(app, ["run", "-y"])
    assert result.exit_code == 1
    assert "pve2: unexpected error: ValueError: kaboom" in result.output
    assert set(calls) == {"pve1", "git1"}


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
        with lock:
            order.append(f"{plan.host}-end")
        return f"{plan.host}: rebooted, back after 1s"

    monkeypatch.setattr(run_mod, "perform_reboot", perform_reboot)

    result = runner.invoke(app, ["run"])

    assert result.exit_code == 0, result.output
    assert len(asked) == 2
    assert order.index("guest1-end") < order.index("pve1-start")
    assert "pve1: rebooted" in result.output and "guest1: rebooted" in result.output
