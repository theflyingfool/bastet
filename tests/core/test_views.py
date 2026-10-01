from bastet.core.views import HARDWARE_BASE_PATH, VIEWS, ensure_views, has_hardware_section, insert_after_title


def test_ensure_views_creates_all_then_nothing(tmp_path):
    changes = ensure_views(tmp_path)
    assert {c.path for c in changes} == {tmp_path / HARDWARE_BASE_PATH}
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


def test_hardware_view_table_first_then_cards():
    text = VIEWS[HARDWARE_BASE_PATH]
    assert text.index("type: table") < text.index("type: cards") and "installed_in == this" in text


def test_has_hardware_section():
    assert has_hardware_section("# h\n\n## Hardware\n\n![[hardware-here.base]]\n")
    assert not has_hardware_section("# h\n")


def test_insert_after_title():
    section = "\n## Summary\n\n![[host-summary.base]]\n"
    text = "---\nbastet: host\n---\n# pve1\nMy notes.\n"
    out = insert_after_title(text, section)
    assert out == "---\nbastet: host\n---\n# pve1\n\n## Summary\n\n![[host-summary.base]]\n\nMy notes.\n"
    assert insert_after_title("---\na: 1\n---\nno title\n", section).startswith("---\na: 1\n---\n\n## Summary")


def test_ensure_page_embed_replaces_legacy_block_or_inserts():
    from bastet.core.views import ensure_page_embed
    legacy = "---\nbastet: host\n---\n# h\n\n## Summary\n\n![[host-summary.base]]\n\nnotes\n"
    assert ensure_page_embed(legacy, "![[h summary]]") == "---\nbastet: host\n---\n# h\n\n![[h summary]]\n\nnotes\n"
    plain = "---\nbastet: host\n---\n# h\nnotes\n"
    assert ensure_page_embed(plain, "![[h summary]]") == "---\nbastet: host\n---\n# h\n\n![[h summary]]\n\nnotes\n"
    done = ensure_page_embed(plain, "![[h summary]]")
    assert ensure_page_embed(done, "![[h summary]]") == done
