from pathlib import Path

from bastet.core.changes import Change, render_diff, write_changes


def test_diff_for_new_file(tmp_path):
    c = Change(tmp_path / "hosts" / "a.md", None, "line1\nline2\n")
    d = render_diff(c, tmp_path)
    assert "--- /dev/null" in d and "+++ b/hosts/a.md" in d and "+line1" in d


def test_diff_for_edit(tmp_path):
    c = Change(tmp_path / "a.md", "x: 1\n", "x: 2\n")
    d = render_diff(c, tmp_path)
    assert "--- a/a.md" in d and "-x: 1" in d and "+x: 2" in d


def test_write_creates_parents(tmp_path):
    p = tmp_path / "deep" / "dir" / "a.md"
    write_changes([Change(p, None, "hello\n")])
    assert p.read_text() == "hello\n"
    assert [x.name for x in p.parent.iterdir()] == ["a.md"]
