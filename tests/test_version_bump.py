import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
_spec = importlib.util.spec_from_file_location("version_bump", ROOT / "scripts" / "version_bump.py")
vb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vb)

PYPROJECT = '[project]\nname = "bastet"\nversion = "0.2.0"\n\n[tool.x]\nversion = "9.9.9"\n'
ZONES = ["Africa/Cairo", "Europe/Berlin", "UTC"]


def test_read_and_set_version_round_trip():
    assert vb.read_version(PYPROJECT) == "0.2.0"
    new = vb.set_version(PYPROJECT, "0.3.0")
    assert vb.read_version(new) == "0.3.0"
    assert 'version = "9.9.9"' in new
    assert new.replace("0.3.0", "0.2.0") == PYPROJECT


@pytest.mark.parametrize("bad", ["1.2", "v1.2.3", "1.2.3-rc1", "", "a.b.c"])
def test_set_version_refuses_bad_version(bad):
    with pytest.raises(ValueError):
        vb.set_version(PYPROJECT, bad)


def test_set_version_refuses_same_version_unless_refresh():
    with pytest.raises(ValueError):
        vb.set_version(PYPROJECT, "0.2.0")
    assert vb.set_version(PYPROJECT, "0.2.0", refresh=True) == PYPROJECT


def test_normalise_sorts_strips_and_drops_blanks():
    assert vb.normalise_zones([" UTC ", "", "Europe/Berlin\n", "   ", "Africa/Cairo"]) == ZONES


def test_normalise_refuses_empty():
    with pytest.raises(ValueError, match="empty"):
        vb.normalise_zones(["", "  "])


def test_normalise_refuses_duplicates():
    with pytest.raises(ValueError, match="UTC"):
        vb.normalise_zones(["UTC", "Europe/Berlin", "UTC"])


def test_normalise_refuses_unloadable_name():
    with pytest.raises(ValueError, match="Mars/Base"):
        vb.normalise_zones(["UTC", "Mars/Base"])


def test_render_and_parse_round_trip():
    text = vb.render_zone_file("0.3.0", ZONES)
    assert text.startswith("# refreshed for bastet 0.3.0\n")
    assert vb.parse_zone_file(text) == ("# refreshed for bastet 0.3.0", ZONES)


def test_diff_zones():
    added, removed = vb.diff_zones(["A/a", "B/b"], ["B/b", "C/c"])
    assert added == ["C/c"]
    assert removed == ["A/a"]


def test_format_changes_caps_lists():
    out = vb.format_changes([f"X/z{i:03}" for i in range(45)], ["Y/y"], 100)
    assert "100 zones" in out
    assert "and 5 more" in out
    assert "removed:" in out and "Y/y" in out


def test_refresh_zone_file_new_file_creates_parent(tmp_path):
    path = tmp_path / "roles" / "time" / "time zones.txt"
    vb.refresh_zone_file(path, "0.3.0", ["UTC", "Europe/Berlin"])
    assert path.read_text() == vb.render_zone_file("0.3.0", ["Europe/Berlin", "UTC"])


def test_refresh_with_same_zones_rewrites_only_stamp(tmp_path):
    path = tmp_path / "time zones.txt"
    vb.refresh_zone_file(path, "0.2.0", ZONES)
    old_lines = path.read_text().splitlines()
    added, removed = vb.refresh_zone_file(path, "0.3.0", list(reversed(ZONES)))
    assert (added, removed) == ([], [])
    new_lines = path.read_text().splitlines()
    assert new_lines[0] == "# refreshed for bastet 0.3.0"
    assert new_lines[1:] == old_lines[1:]


def test_refresh_reports_changes(tmp_path):
    path = tmp_path / "time zones.txt"
    vb.refresh_zone_file(path, "0.2.0", ["Europe/Berlin", "UTC"])
    added, removed = vb.refresh_zone_file(path, "0.3.0", ["Africa/Cairo", "UTC"])
    assert added == ["Africa/Cairo"]
    assert removed == ["Europe/Berlin"]
    assert vb.parse_zone_file(path.read_text())[1] == ["Africa/Cairo", "UTC"]


def test_refresh_refuses_bad_zones_and_leaves_file(tmp_path):
    path = tmp_path / "time zones.txt"
    vb.refresh_zone_file(path, "0.2.0", ZONES)
    before = path.read_text()
    with pytest.raises(ValueError):
        vb.refresh_zone_file(path, "0.3.0", ["UTC", "Mars/Base"])
    assert path.read_text() == before


def good(version="0.2.0", zones=ZONES):
    return vb.render_zone_file(version, zones)


def test_check_passes_on_good_file():
    assert vb.check_zone_file(good(), "0.2.0") == []


def test_check_fails_on_stale_stamp():
    problems = vb.check_zone_file(good("0.1.0"), "0.2.0")
    assert problems and "0.2.0" in problems[0]


def test_check_fails_on_unsorted():
    text = "# refreshed for bastet 0.2.0\nUTC\nAfrica/Cairo\n"
    assert any("sorted" in p for p in vb.check_zone_file(text, "0.2.0"))


def test_check_fails_on_duplicate():
    text = "# refreshed for bastet 0.2.0\nAfrica/Cairo\nAfrica/Cairo\n"
    assert any("duplicate" in p for p in vb.check_zone_file(text, "0.2.0"))


def test_check_fails_on_empty_and_unloadable():
    assert vb.check_zone_file("# refreshed for bastet 0.2.0\n", "0.2.0")
    text = "# refreshed for bastet 0.2.0\nMars/Base\nUTC\n"
    assert any("Mars/Base" in p for p in vb.check_zone_file(text, "0.2.0"))


def _project(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(PYPROJECT)
    return pyproject, tmp_path / "time zones.txt"


def test_main_check_missing_file_fails(tmp_path, capsys):
    pyproject, zones = _project(tmp_path)
    assert vb.run_check(pyproject, zones) == 1
    assert "missing" in capsys.readouterr().err


def test_main_check_good_file_passes_and_writes_nothing(tmp_path, capsys):
    pyproject, zones = _project(tmp_path)
    zones.write_text(good())
    roles = _roles(tmp_path)
    record = tmp_path / "hashes.txt"
    record.write_text(vb.render_hashes(vb.role_hashes(roles)))
    assert vb.run_check(pyproject, zones, record, roles) == 0
    assert "time zone list and role hashes are current for bastet 0.2.0" in capsys.readouterr().out
    assert zones.read_text() == good()
    assert pyproject.read_text() == PYPROJECT


def test_run_bump_writes_both_files(tmp_path, capsys):
    pyproject, zones = _project(tmp_path)
    code = vb.run_bump("0.3.0", pyproject, zones, lines=["UTC", "Europe/Berlin"], refresh=False, gen_doc=False,
                       hashes_path=tmp_path / "hashes.txt", roles_dir=_roles(tmp_path))
    assert code == 0
    assert vb.read_version(pyproject.read_text()) == "0.3.0"
    assert vb.parse_zone_file(zones.read_text()) == ("# refreshed for bastet 0.3.0", ["Europe/Berlin", "UTC"])
    assert "2 zones" in capsys.readouterr().out


def test_run_bump_bad_zones_leaves_pyproject(tmp_path):
    pyproject, zones = _project(tmp_path)
    code = vb.run_bump("0.3.0", pyproject, zones, lines=[], refresh=False, gen_doc=False,
                       hashes_path=tmp_path / "hashes.txt", roles_dir=_roles(tmp_path))
    assert code == 1
    assert pyproject.read_text() == PYPROJECT
    assert not zones.exists()


def test_real_zone_path_constant():
    assert vb.ZONES_PATH == ROOT / "src" / "bastet" / "data" / "roles" / "time" / "time zones.txt"


def _roles(tmp_path):
    roles = tmp_path / "roles"
    (roles / "a").mkdir(parents=True)
    (roles / "a" / "a role.md").write_text("one\n")
    (roles / "b").mkdir()
    (roles / "b" / "role.yml").write_text("two\n")
    return roles


def test_role_hashes_change_with_content_and_ignore_the_record(tmp_path):
    roles = _roles(tmp_path)
    first = vb.role_hashes(roles)
    assert set(first) == {"a", "b"}
    (roles / "a" / "a role.md").write_text("changed\n")
    second = vb.role_hashes(roles)
    assert second["b"] == first["b"] and second["a"] != first["a"]


def test_check_hashes_names_changed_roles_until_a_bump_records_them(tmp_path):
    roles = _roles(tmp_path)
    record = tmp_path / "hashes.txt"
    assert vb.check_hashes(record, roles) == ["a", "b"]
    record.write_text(vb.render_hashes(vb.role_hashes(roles)))
    assert vb.check_hashes(record, roles) == []
    (roles / "b" / "role.yml").write_text("edited\n")
    assert vb.check_hashes(record, roles) == ["b"]
    (roles / "c").mkdir()
    (roles / "c" / "role.yml").write_text("new\n")
    assert vb.check_hashes(record, roles) == ["b", "c"]
