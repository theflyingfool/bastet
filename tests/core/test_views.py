from bastet.core.views import (
    HARDWARE_BASE_PATH, HOST_SUMMARY_BASE_PATH, HARDWARE_SUMMARY_BASE_PATH, VIEWS, ensure_views,
    has_hardware_section, insert_after_title,
)


def test_ensure_views_creates_all_then_nothing(tmp_path):
    changes = ensure_views(tmp_path)
    assert {c.path for c in changes} == {tmp_path / p for p in (HARDWARE_BASE_PATH, HOST_SUMMARY_BASE_PATH, HARDWARE_SUMMARY_BASE_PATH)}
    for c in changes:
        c.path.parent.mkdir(parents=True, exist_ok=True)
        c.path.write_text(c.after)
    assert ensure_views(tmp_path) == []


def test_ensure_views_refreshes_outdated_bastet_views(tmp_path):
    p = tmp_path / HARDWARE_BASE_PATH
    p.parent.mkdir(parents=True)
    p.write_text("old\n")
    [c] = [c for c in ensure_views(tmp_path) if c.path == p]
    assert c.before == "old\n" and c.after == VIEWS[HARDWARE_BASE_PATH]


def test_views_have_cards_first_then_table():
    for path, text in VIEWS.items():
        cards, table = text.index("type: cards"), text.index("type: table")
        assert cards < table, path
    assert "file.path == this.file.path" in VIEWS[HOST_SUMMARY_BASE_PATH]
    assert "installed_in == this" in VIEWS[HARDWARE_BASE_PATH]


def test_has_hardware_section():
    assert has_hardware_section("# h\n\n## Hardware\n\n![[hardware-here.base]]\n")
    assert not has_hardware_section("# h\n")


def test_insert_after_title():
    section = "\n## Summary\n\n![[host-summary.base]]\n"
    text = "---\nbastet: host\n---\n# pve1\nMy notes.\n"
    out = insert_after_title(text, section)
    assert out == "---\nbastet: host\n---\n# pve1\n\n## Summary\n\n![[host-summary.base]]\n\nMy notes.\n"
    assert insert_after_title("---\na: 1\n---\nno title\n", section).startswith("---\na: 1\n---\n\n## Summary")
