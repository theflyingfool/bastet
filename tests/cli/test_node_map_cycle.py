import io
from types import SimpleNamespace

from bastet.cli import run as run_cli
from bastet.ui import Console, use


def _ready(name, runs_on):
    return SimpleNamespace(doc=SimpleNamespace(name=name, data={"runs_on": runs_on}))


class Inv:
    def get(self, name):
        return SimpleNamespace(name=name)


def _run(by_name, names):
    buf = io.StringIO()
    with use(Console(buf, io.StringIO(), color=False)):
        result = run_cli._node_of_map(by_name, names, Inv())
    return result, buf.getvalue()


def test_a_two_host_cycle_is_reported_not_crashed():
    by_name = {"a": _ready("a", "[[b]]"), "b": _ready("b", "[[a]]")}
    result, printed = _run(by_name, ["a", "b"])
    assert isinstance(result, dict) and "runs_on loop" in printed


def test_a_host_that_runs_on_itself_is_reported():
    result, printed = _run({"a": _ready("a", "[[a]]")}, ["a"])
    assert result == {} and "runs_on loop" in printed
