from bastet.cli.app import app
from bastet.core.remote import LocalRunner


class AsRootLocally(LocalRunner):
    """Runs scripts as the current user, as if it were root, so role files can target temp paths."""

    def run(self, script, *, timeout=120):
        return super().run(script.replace('if [ "$(id -u)" = 0 ]; then SUDO=""', 'if true; then SUDO=""'), timeout=timeout)


def test_check_and_apply_together_is_an_error(runner, inventory):
    result = runner.invoke(app, ["run", "-c", "-a"])
    assert result.exit_code != 0
    assert "check or apply, not both" in result.output


def test_bare_run_dispatches_to_apply(runner, inventory, monkeypatch):
    import bastet.cli.run as run_mod
    calls = []
    monkeypatch.setattr(run_mod, "_run", lambda *a, **k: calls.append((a, k)))
    result = runner.invoke(app, ["run"])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1 and calls[0][1]["apply_changes"] is True


def test_dash_c_dispatches_to_check(runner, inventory, monkeypatch):
    import bastet.cli.run as run_mod
    calls = []
    monkeypatch.setattr(run_mod, "_run", lambda *a, **k: calls.append((a, k)))
    result = runner.invoke(app, ["run", "-c"])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1 and calls[0][1]["apply_changes"] is False


def test_dash_g_only_gathers(runner, inventory, monkeypatch):
    import bastet.cli.run as run_mod
    gather_calls = []
    run_calls = []
    monkeypatch.setattr(run_mod.gather_mod, "_gather", lambda *a, **k: gather_calls.append((a, k)))
    monkeypatch.setattr(run_mod, "_run", lambda *a, **k: run_calls.append((a, k)))
    result = runner.invoke(app, ["run", "-g"])
    assert result.exit_code == 0, result.output
    assert len(gather_calls) == 1 and run_calls == []


def test_dash_g_dash_a_gathers_then_applies(runner, inventory, monkeypatch):
    import bastet.cli.run as run_mod
    order = []
    monkeypatch.setattr(run_mod.gather_mod, "_gather", lambda *a, **k: order.append("gather"))
    monkeypatch.setattr(run_mod, "_run", lambda *a, **k: order.append(("run", k["apply_changes"])))
    result = runner.invoke(app, ["run", "-g", "-a"])
    assert result.exit_code == 0, result.output
    assert order == ["gather", ("run", True)]


def test_dash_g_dash_c_gathers_then_checks(runner, inventory, monkeypatch):
    import bastet.cli.run as run_mod
    order = []
    monkeypatch.setattr(run_mod.gather_mod, "_gather", lambda *a, **k: order.append("gather"))
    monkeypatch.setattr(run_mod, "_run", lambda *a, **k: order.append(("run", k["apply_changes"])))
    result = runner.invoke(app, ["run", "-g", "-c"])
    assert result.exit_code == 0, result.output
    assert order == ["gather", ("run", False)]


def test_gather_receives_the_exclude_option(runner, inventory, monkeypatch):
    import bastet.cli.run as run_mod
    seen = {}

    def fake_gather(hosts, accept_new_hostkey, yes, jobs, exclude=None):
        seen["exclude"] = exclude
    monkeypatch.setattr(run_mod.gather_mod, "_gather", fake_gather)
    result = runner.invoke(app, ["run", "-g", "--exclude", "pve1"])
    assert result.exit_code == 0, result.output
    assert seen["exclude"] == ["pve1"]


def _two_hosts(inventory, monkeypatch):
    import bastet.cli.run as run_mod
    (inventory / "hosts" / "box.md").write_text("---\nbastet: host\ntype: laptop\nconnection: local\n---\n# box\n")
    (inventory / "hosts" / "nas1.md").write_text("---\nbastet: host\ntype: server\nip: 10.0.20.40\nconnection: local\n---\n# nas1\n")
    monkeypatch.setattr(run_mod, "connect", lambda ctx, doc, tmp, yes: (AsRootLocally(), None))


def test_at_type_selector_restricts_to_that_type(runner, inventory, monkeypatch):
    _two_hosts(inventory, monkeypatch)
    result = runner.invoke(app, ["run", "-c", "@laptop"])
    assert result.exit_code == 0, result.output
    assert "box:" in result.output and "nas1:" not in result.output


def test_glob_selector_restricts_to_matching_names(runner, inventory, monkeypatch):
    _two_hosts(inventory, monkeypatch)
    result = runner.invoke(app, ["run", "-c", "nas*"])
    assert result.exit_code == 0, result.output
    assert "nas1:" in result.output and "box:" not in result.output


def test_exclude_removes_a_host_from_the_run(runner, inventory, monkeypatch):
    _two_hosts(inventory, monkeypatch)
    result = runner.invoke(app, ["run", "-c", "box", "nas1", "--exclude", "nas1"])
    assert result.exit_code == 0, result.output
    assert "box:" in result.output and "nas1:" not in result.output


def test_unknown_at_selector_is_a_clean_error(runner, inventory):
    result = runner.invoke(app, ["run", "-c", "@nope"])
    assert result.exit_code == 1
    assert "no group or type named 'nope'" in result.output


def test_map_check_apply_gather_do_not_exist(runner, inventory):
    for name in ("map", "check", "apply", "gather"):
        result = runner.invoke(app, [name])
        assert result.exit_code != 0
