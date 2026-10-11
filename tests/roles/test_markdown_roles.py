import pytest

from bastet.core.errors import BastetError
from bastet.roles.contract import API_VERSIONS, Option, check_value, load_roles, parse_role

BASE = {"bastet": "role-definition", "name": "demo", "version": "1.2.3", "api": 0, "description": "A demo role"}


def _fm(**over):
    data = {**BASE, **over}
    return {k: v for k, v in data.items() if v is not None}


def _write(tmp_path, front, name="demo", body="Notes.\n"):
    import yaml
    folder = tmp_path / name
    folder.mkdir(exist_ok=True)
    path = folder / f"{name} role.md"
    path.write_text("---\n" + yaml.safe_dump(front, sort_keys=False) + "---\n" + body, encoding="utf-8")
    return path


def _err(tmp_path, front, **kw):
    path = _write(tmp_path, front, **kw)
    with pytest.raises(BastetError) as e:
        parse_role(path)
    return str(e.value)


def test_minimal_role_parses(tmp_path):
    role = parse_role(_write(tmp_path, _fm()))
    assert role.name == "demo" and role.markdown is True and role.api == 0
    assert role.version == "1.2.3" and role.description == "A demo role"
    assert role.os == () and role.provides == () and role.options == {} and role.entries == []
    assert API_VERSIONS == (0,)


def test_os_provides_options_examples_files(tmp_path):
    front = _fm(os=["arch"], provides=["ntp"],
                options={"b": {"type": "string"}, "a": {"type": "int", "min": 1}},
                examples=[{"title": "t", "yaml": "a: 1\n"}],
                files=[{"path": "/etc/x.conf", "render": "apt", "mode": "0644"}])
    role = parse_role(_write(tmp_path, front))
    assert role.os == ("arch",) and role.provides == ("ntp",)
    assert list(role.options) == ["b", "a"]  # order preserved
    assert role.examples == [{"title": "t", "yaml": "a: 1\n"}]
    assert role.entries == [{"path": "/etc/x.conf", "render": "apt", "mode": "0644"}]


@pytest.mark.parametrize("key,value,message", [
    ("bastet", "role", "bastet: role-definition"),
    ("bastet", None, "bastet: role-definition"),
    ("name", "other", "name"),
    ("name", None, "name"),
    ("version", "1.2", "version"),
    ("version", None, "version"),
    ("api", None, "api"),
    ("description", None, "description"),
])
def test_required_fields(tmp_path, key, value, message):
    msg = _err(tmp_path, _fm(**{key: value}))
    assert message in msg and "demo role.md" in msg


def test_api_one_refused(tmp_path):
    assert "api" in _err(tmp_path, _fm(api=1))


def test_no_frontmatter(tmp_path):
    (tmp_path / "demo").mkdir()
    p = tmp_path / "demo" / "demo role.md"
    p.write_text("just text\n")
    with pytest.raises(BastetError):
        parse_role(p)


def test_unknown_top_level_key(tmp_path):
    assert "colour" in _err(tmp_path, _fm(colour="red"))


def test_reserved_keys_accepted_and_ignored(tmp_path):
    reserved = ["uses", "needs", "contributes", "collects", "requires", "tags", "cssclasses", "types", "not_types",
                "os_min", "data", "vars", "presets", "packages", "templates", "units", "hooks", "source",
                "source_hash"]
    role = parse_role(_write(tmp_path, _fm(**{k: [k] for k in reserved})))
    assert set(role.raw) >= set(reserved)
    assert role.options == {} and role.entries == []


@pytest.mark.parametrize("entry,message", [
    ({"path": "/x"}, "edit"),
    ({"path": "/x", "edit": "ini", "render": "apt"}, "edit"),
    ({"path": "/x", "edit": "ini", "colour": 1}, "colour"),
    ({"edit": "ini"}, "path"),
    ({"path": "/x", "edit": "yaml"}, "edit"),
    ({"path": "/x", "render": "ini"}, "render"),
])
def test_files_entry_errors(tmp_path, entry, message):
    assert message in _err(tmp_path, _fm(files=[entry]))


def test_files_entry_optional_keys(tmp_path):
    entries = [{"path": "/x", "render": "apt", "mode": "0600", "owner": "root", "group": "root",
                "validate": "true", "before": "packages", "backup": True},
               {"path": "/y", "edit": "ini", "validate": "true", "after": "files", "backup": False}]
    assert parse_role(_write(tmp_path, _fm(files=entries))).entries == entries


@pytest.mark.parametrize("opt", [
    {"type": "string", "key": "K", "section": "S", "as": "value", "single_line": True},
    {"type": "int", "min": 1, "max": 5, "as": "flag"},
    {"type": "number", "min": 0.5, "max": 2},
    {"type": "list", "items": {"type": "string"}, "as": "list"},
])
def test_option_keys_accepted(tmp_path, opt):
    assert "o" in parse_role(_write(tmp_path, _fm(options={"o": opt}))).options


@pytest.mark.parametrize("opt,message", [
    ({"type": "string", "min": 1}, "min"),
    ({"type": "bool", "max": 1}, "max"),
    ({"type": "int", "single_line": True}, "single_line"),
    ({"type": "string", "as": "weird"}, "as"),
])
def test_option_keys_rejected(tmp_path, opt, message):
    assert message in _err(tmp_path, _fm(options={"o": opt}))


def test_option_fields_set(tmp_path):
    o = parse_role(_write(tmp_path, _fm(options={"o": {"type": "int", "key": "K", "section": "S", "as": "value",
                                                       "min": 1, "max": 3}}))).options["o"]
    assert (o.key, o.section, o.as_, o.min, o.max) == ("K", "S", "value", 1, 3)


def test_check_value_min_max_single_line():
    n = Option(type="int", min=2, max=4)
    assert check_value(n, 3, "w") == 3
    with pytest.raises(BastetError, match="w: must be 2 or more"):
        check_value(n, 1, "w")
    with pytest.raises(BastetError, match="w: must be 4 or less"):
        check_value(n, 5, "w")
    s = Option(type="string", single_line=True)
    assert check_value(s, "one", "w") == "one"
    for bad in ("", "  ", "a\nb"):
        with pytest.raises(BastetError, match="w: needs a single non-empty line"):
            check_value(s, bad, "w")


def test_load_roles_markdown_and_both(tmp_path):
    _write(tmp_path, _fm())
    assert load_roles(tmp_path)["demo"].markdown is True
    (tmp_path / "demo" / "role.yml").write_text("description: x\n")
    with pytest.raises(BastetError, match="both"):
        load_roles(tmp_path)


def test_load_roles_yml_unchanged(tmp_path):
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "role.yml").write_text("description: d\noptions:\n  a: {type: string}\n")
    r = load_roles(tmp_path)["x"]
    assert r.markdown is False and r.api is None and r.version == "0.0.0" and "a" in r.options


def test_bundled_set_unchanged():
    assert set(load_roles()) == {"systemd", "packages", "users", "files", "base", "pacman", "apt", "ssh", "harden"}
