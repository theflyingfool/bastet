import subprocess
from pathlib import Path

from bastet.cli.app import app


def head_author(root: Path) -> str:
    lines = subprocess.run(["git", "-C", str(root), "log", "--format=%an %s"], capture_output=True, text=True).stdout.splitlines()
    return next(line for line in lines if not line.startswith("Bastet refresh:"))


def test_interactive_vps(runner, inventory):
    result = runner.invoke(app, ["add", "host"], input="edge1\nvps\nlinode\n203.0.113.10\ny\n")
    assert result.exit_code == 0, result.output
    text = (inventory / "hosts" / "edge1.md").read_text()
    assert "type: vps\nprovider: linode\nip: 203.0.113.10\n" in text
    assert head_author(inventory) == "Bastet add host edge1"


def test_type_by_number_and_bad_choice_reprompts(runner, inventory):
    # types sorted: laptop, lxc, proxmox, server, unifi-ap, unifi-gateway, unifi-switch, unknown, vm, vps
    result = runner.invoke(app, ["add", "host"], input="edge1\nvpz\n10\nlinode\n203.0.113.10\ny\n")
    assert result.exit_code == 0, result.output
    assert "isn't one of the choices" in result.output
    assert "type: vps" in (inventory / "hosts" / "edge1.md").read_text()


def test_interactive_laptop_dhcp_local(runner, inventory):
    result = runner.invoke(app, ["add", "host", "laptop", "--type", "laptop"], input="dhcp\n\ny\ny\n")
    assert result.exit_code == 0, result.output
    text = (inventory / "hosts" / "laptop.md").read_text()
    assert "ip: dhcp\naddress: laptop.local\nconnection: local\n" in text


def test_interactive_lxc_picks_parent_network_and_suggestion(runner, inventory):
    result = runner.invoke(app, ["add", "host", "git1", "--type", "lxc"], input="1\nservers\n\ny\n")
    assert result.exit_code == 0, result.output
    text = (inventory / "hosts" / "git1.md").read_text()
    assert 'runs_on: "[[pve1]]"' in text and "network: servers\nip: 10.0.20.10\n" in text


def test_yes_without_type_is_error(runner, inventory):
    result = runner.invoke(app, ["add", "host", "x", "-y"])
    assert result.exit_code == 1 and "--type" in result.output


def test_interactive_hardware(runner, inventory):
    result = runner.invoke(app, ["add", "hardware"], input="WD Red WX12\ndrive\n\nWX12\n4 TB\npve1\n\ny\n")
    assert result.exit_code == 0, result.output
    text = (inventory / "hardware" / "WD Red WX12.md").read_text()
    assert "serial: WX12\nsize: 4 TB\nstatus: in-service\ninstalled_in: \"[[pve1]]\"\n" in text
    assert "model" not in text


def test_add_local_host_sets_up_this_machine_after_writing(runner, inventory, secret_keys, monkeypatch):
    import bastet.cli.init as init_mod
    calls = []
    monkeypatch.setattr(init_mod, "_stdout_is_tty", lambda: True)
    monkeypatch.setattr(init_mod, "_setup_this_machine",
                        lambda ctx, pub, *, yes: calls.append((pub.name, (inventory / "hosts" / "laptop1.md").exists())))
    result = runner.invoke(app, ["add", "host", "laptop1", "--type", "laptop", "--ip", "dhcp",
                                 "--address", "laptop1.local", "--local"], input="y\n")
    assert result.exit_code == 0, result.output
    assert calls == [("bastet_key.pub", True)]  # after the host note was written


def test_add_local_host_declined_sets_up_nothing(runner, inventory, secret_keys, monkeypatch):
    import bastet.cli.init as init_mod
    calls = []
    monkeypatch.setattr(init_mod, "_setup_this_machine", lambda *a, **k: calls.append(a))
    result = runner.invoke(app, ["add", "host", "laptop1", "--type", "laptop", "--ip", "dhcp",
                                 "--address", "laptop1.local", "--local"], input="n\n")
    assert calls == []


def test_add_local_host_without_a_bastet_key_says_to_run_init(runner, inventory, monkeypatch):
    import bastet.cli.init as init_mod
    calls = []
    monkeypatch.setattr(init_mod, "_setup_this_machine", lambda *a, **k: calls.append(a))
    result = runner.invoke(app, ["add", "host", "laptop1", "--type", "laptop", "--ip", "dhcp",
                                 "--address", "laptop1.local", "--local", "-y"])
    assert result.exit_code == 0, result.output
    assert calls == [] and "bastet init" in result.output


def test_add_non_local_host_never_sets_up_this_machine(runner, inventory, secret_keys, monkeypatch):
    import bastet.cli.init as init_mod
    calls = []
    monkeypatch.setattr(init_mod, "_setup_this_machine", lambda *a, **k: calls.append(a))
    result = runner.invoke(app, ["add", "host", "edge1", "--type", "vps", "--provider", "linode",
                                 "--ip", "203.0.113.10", "-y"])
    assert result.exit_code == 0, result.output
    assert calls == []
