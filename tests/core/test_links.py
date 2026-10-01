from bastet.core.links import link_target, make_link


def test_link_target_forms():
    assert link_target("[[pve1]]") == "pve1"
    assert link_target("[[hosts/pve1|PVE]]") == "pve1"
    assert link_target("[[pve1#Hardware]]") == "pve1"
    assert link_target("[[WD Red 4TB WX12]]") == "WD Red 4TB WX12"


def test_not_a_link():
    assert link_target("pve1") is None
    assert link_target(3) is None
    assert link_target(None) is None


def test_make_link():
    assert make_link("pve1") == "[[pve1]]"
