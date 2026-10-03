from bastet.cli.common import load_context, ssh_port


def _ssh_role(inventory, port_yaml):
    roles = inventory / "_roles" / "hosts" / "pve1"
    roles.mkdir(parents=True, exist_ok=True)
    (roles / "ssh.md").write_text(f'---\nbastet: role\nrole: ssh\napplies_to: "[[pve1]]"\nport: {port_yaml}\n---\n')


def test_default_port_is_22(inventory):
    ctx = load_context()
    assert ssh_port(ctx, ctx.inventory.get("pve1")) == 22


def test_port_follows_ssh_role(inventory):
    _ssh_role(inventory, "[2222, 22]")
    ctx = load_context()
    assert ssh_port(ctx, ctx.inventory.get("pve1")) == 2222


def test_broken_role_file_falls_back_to_22(inventory):
    _ssh_role(inventory, "nope")
    ctx = load_context()
    assert ssh_port(ctx, ctx.inventory.get("pve1")) == 22


def test_connect_uses_the_port(inventory, monkeypatch):
    import bastet.cli.run as run_mod
    seen = {}

    def scan(address, recorded=None, port=22):
        seen["scan"] = port
        return []
    monkeypatch.setattr(run_mod, "scan_keys", scan)
    _ssh_role(inventory, "[2222]")
    (inventory / "hosts" / "pve1.md").write_text(
        "---\nbastet: host\ntype: proxmox-node\nip: 10.0.10.11\nssh_host_key: ssh-ed25519 SHA256:x\n---\n# pve1\n")
    ctx = load_context()
    try:
        run_mod.connect(ctx, ctx.inventory.get("pve1"), inventory, yes=True)
    except Exception:
        pass  # the fake scan returns no keys; only the port matters here
    assert seen["scan"] == 2222


def test_gather_pins_and_connects_on_the_port(inventory, monkeypatch):
    import bastet.cli.gather as gather_mod
    from bastet.core.errors import BastetError
    seen = {}

    def scan(address, recorded=None, port=22):
        seen["scan"] = port
        raise BastetError("stop here")
    monkeypatch.setattr(gather_mod, "scan_keys", scan)
    _ssh_role(inventory, "[2200]")
    from typer.testing import CliRunner
    from bastet.cli.app import app
    CliRunner().invoke(app, ["gather", "pve1", "-y"])
    assert seen["scan"] == 2200


def test_ports_in_order_with_22_last(inventory):
    from bastet.cli.common import ssh_ports
    _ssh_role(inventory, "[2222]")
    ctx = load_context()
    assert ssh_ports(ctx, ctx.inventory.get("pve1")) == [2222, 22]


def test_connect_falls_back_to_the_next_port_that_answers(inventory, monkeypatch):
    import bastet.cli.run as run_mod
    from bastet.core.errors import Unreachable
    tried = []

    def scan(address, recorded=None, port=22):
        tried.append(port)
        if port == 2222:
            raise Unreachable("nothing answered on port 2222")
        return []
    monkeypatch.setattr(run_mod, "scan_keys", scan)
    _ssh_role(inventory, "[2222, 22]")
    (inventory / "hosts" / "pve1.md").write_text(
        "---\nbastet: host\ntype: proxmox-node\nip: 10.0.10.11\nssh_host_key: ssh-ed25519 SHA256:x\n---\n# pve1\n")
    ctx = load_context()
    try:
        run_mod.connect(ctx, ctx.inventory.get("pve1"), inventory, yes=True)
    except Exception:
        pass
    assert tried == [2222, 22]
