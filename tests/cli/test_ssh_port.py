from bastet.cli.common import load_context, ssh_port


def test_default_port_is_22(inventory):
    ctx = load_context()
    assert ssh_port(ctx, ctx.inventory.get("pve1")) == 22
