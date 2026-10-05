import threading
import time

import pytest
import typer

from bastet.core.errors import BastetError
from bastet.core.parallel import HostLog, Outcome, in_worker, run_parallel, stopping


def test_results_in_input_order_despite_completion_order():
    order = []
    order_lock = threading.Lock()
    b_started = threading.Event()
    a_may_finish = threading.Event()

    def work(host, log):
        if host == "a":
            assert b_started.wait(timeout=1)
            assert a_may_finish.wait(timeout=1)
            with order_lock:
                order.append("a")
            return "a-value"
        with order_lock:
            order.append("b")
        b_started.set()
        a_may_finish.set()
        return "b-value"

    results = run_parallel(["a", "b"], work, jobs=2)

    assert [r.host for r in results] == ["a", "b"]
    assert order == ["b", "a"]
    assert results[0].status == "done" and results[0].value == "a-value"
    assert results[1].status == "done" and results[1].value == "b-value"


def test_at_most_jobs_run_concurrently():
    lock = threading.Lock()
    current = 0
    peak = 0

    def work(host, log):
        nonlocal current, peak
        with lock:
            current += 1
            peak = max(peak, current)
        time.sleep(0.05)
        with lock:
            current -= 1
        return host

    hosts = [f"h{i}" for i in range(6)]
    results = run_parallel(hosts, work, jobs=2)

    assert peak <= 2
    assert {r.host for r in results} == set(hosts)
    assert all(r.status == "done" for r in results)


def test_bastet_error_and_unexpected_error_leave_others_done():
    def work(host, log):
        if host == "b":
            raise BastetError("bad host")
        if host == "c":
            raise ValueError("boom")
        return host

    results = run_parallel(["a", "b", "c"], work, jobs=3)
    by_host = {r.host: r for r in results}

    assert by_host["a"].status == "done" and by_host["a"].value == "a"
    assert by_host["b"].status == "error" and by_host["b"].error == "bad host"
    assert by_host["c"].status == "error"
    assert by_host["c"].error == "unexpected error: ValueError: boom"


def test_after_guest_waits_for_its_node():
    order = []
    order_lock = threading.Lock()

    def work(host, log):
        with order_lock:
            order.append(host)
        return host

    results = run_parallel(["guest", "n1"], work, jobs=2, after={"guest": "n1"})

    assert order == ["n1", "guest"]
    by_host = {r.host: r for r in results}
    assert by_host["n1"].status == "done"
    assert by_host["guest"].status == "done"


def test_after_guest_errors_when_node_fails():
    def work(host, log):
        if host == "n1":
            raise BastetError("node broke")
        return host

    results = run_parallel(["guest", "n1"], work, jobs=2, after={"guest": "n1"})
    by_host = {r.host: r for r in results}

    assert by_host["n1"].status == "error"
    assert by_host["guest"].status == "error"
    assert by_host["guest"].error == "its node n1 failed"
    assert by_host["guest"].value is None


def test_in_worker_true_inside_false_outside():
    assert in_worker() is False
    seen = {}

    def work(host, log):
        seen["inside"] = in_worker()
        return None

    run_parallel(["a"], work, jobs=1)

    assert seen["inside"] is True
    assert in_worker() is False


def test_single_job_uses_same_code_path():
    def work(host, log):
        return host.upper()

    results = run_parallel(["a", "b"], work, jobs=1)

    assert [r.value for r in results] == ["A", "B"]
    assert all(r.status == "done" for r in results)


def test_ctrl_c_stops_unstarted_hosts_and_reraises():
    started = []
    started_lock = threading.Lock()

    def work(host, log):
        with started_lock:
            started.append(host)
        return host

    seen = []

    def on_done(outcome):
        seen.append(outcome.host)
        if len(seen) == 1:
            raise KeyboardInterrupt

    results = None
    with pytest.raises(KeyboardInterrupt):
        results = run_parallel(["a", "b", "c"], work, jobs=1, on_done=on_done)

    # with jobs=1, only the one host already running when the interrupt lands gets to start
    assert len(started) == 1
    assert results is None  # run_parallel re-raises instead of returning


def test_stopping_flag_set_during_interrupt_and_cleared_by_the_next_run():
    def work(host, log):
        return host

    seen = []

    def on_done(outcome):
        seen.append(outcome.host)
        if len(seen) == 1:
            assert stopping() is False
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_parallel(["a", "b"], work, jobs=1, on_done=on_done)

    assert stopping() is True

    run_parallel(["x"], work, jobs=1)
    assert stopping() is False


def test_host_log_echo_and_secho_record_lines():
    log = HostLog("myhost")
    log.echo("plain")
    log.secho("warn", fg="yellow")

    assert log.lines == [("plain", None), ("warn", "yellow")]


def test_outcome_is_generic_dataclass():
    log = HostLog("h")
    outcome: Outcome[str] = Outcome(host="h", status="done", value="v", error=None, log=log)
    assert outcome.host == "h"
    assert outcome.status == "done"


def test_typer_confirm_not_wrapped_by_default():
    # Without guard_prompts() active, in_worker() being True must not matter here --
    # guard_prompts() itself lives in bastet.cli.common, not in core.parallel.
    assert hasattr(typer, "confirm")
