from bastet.core.views import HARDWARE_BASE_PATH, ensure_views, has_hardware_section


def test_ensure_views_only_when_missing(tmp_path):
    [c] = ensure_views(tmp_path)
    assert c.path == tmp_path / HARDWARE_BASE_PATH and c.before is None
    assert "installed_in == this" in c.after
    c.path.parent.mkdir(parents=True)
    c.path.write_text(c.after)
    assert ensure_views(tmp_path) == []


def test_has_hardware_section():
    assert has_hardware_section("# h\n\n## Hardware\n\n![[hardware-here.base]]\n")
    assert has_hardware_section("text ![[hardware-here.base]]")
    assert not has_hardware_section("# h\n")
