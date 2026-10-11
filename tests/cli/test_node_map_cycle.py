from types import SimpleNamespace

from bastet.cli import run as run_cli


def _ready(name, runs_on):
    return SimpleNamespace(doc=SimpleNamespace(name=name, data={"runs_on": runs_on}))


class Inv:
    def get(self, name):
        return SimpleNamespace(name=name)


def _run(monkeypatch, by_name, names):
    printed = []
    monkeypatch.setattr(run_cli.out, "secho", lambda text, **kw: printed.append(text))
    result = run_cli._node_of_map(by_name, names, Inv())
    return result, printed


def test_a_two_host_cycle_is_reported_not_crashed(monkeypatch):
    by_name = {"a": _ready("a", "[[b]]"), "b": _ready("b", "[[a]]")}
    result, printed = _run(monkeypatch, by_name, ["a", "b"])
    assert isinstance(result, dict) and any("runs_on loop" in p for p in printed)


def test_a_host_that_runs_on_itself_is_reported(monkeypatch):
    result, printed = _run(monkeypatch, {"a": _ready("a", "[[a]]")}, ["a"])
    assert result == {} and any("runs_on loop" in p for p in printed)
