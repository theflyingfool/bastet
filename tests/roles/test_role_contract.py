import pytest

from bastet.core.errors import BastetError
from bastet.roles.contract import check_values, load_roles, with_defaults


def test_shipped_roles_load():
    roles = load_roles()
    assert set(roles) == {"systemd", "packages", "users", "files", "base"}
    assert roles["systemd"].options["ntp_service"].choices == ("keep", "timesyncd", "chrony")
    assert roles["packages"].options["install"].items.shorthand == "name"
    assert roles["users"].options["users"].items.fields["password_hash"].secret is True


def test_shorthand_and_reserved_keys():
    pk = load_roles()["packages"]
    out = check_values(pk, {"bastet": "role", "role": "packages", "applies_to": "[[x]]",
                            "install": ["tree", {"name": "jq", "version": "1.7"}]}, "pk")
    assert out == {"install": [{"name": "tree"}, {"name": "jq", "version": "1.7"}]}


@pytest.mark.parametrize("role,values,message", [
    ("systemd", {"timezon": "UTC"}, "systemd has no option 'timezon'"),
    ("systemd", {"ntp": "yes"}, "expected true or false"),
    ("systemd", {"ntp_service": "ntpd"}, "isn't one of keep, timesyncd, chrony"),
    ("files", {"files": {"/etc/x": {"content": "a", "mode": 420}}}, "quote it"),
    ("files", {"files": {"/etc/x": {"contents": "a"}}}, "unknown field contents"),
    ("packages", {"install": "tree"}, "expected a list"),
    ("users", {"users": {"nick": {"uid": "1000"}}}, "expected a whole number"),
])
def test_errors_name_the_option(role, values, message):
    with pytest.raises(BastetError) as e:
        check_values(load_roles()[role], values, "f")
    assert message in str(e.value)


def test_defaults():
    v = with_defaults(load_roles()["systemd"], {"timezone": "UTC"})
    assert v["timezone"] == "UTC" and v["ntp_service"] == "keep" and v["manage_hostname"] is True
    assert v["rtc_local"] is False and v["ntp"] is None and v["services"] is None


def test_bad_role_definitions(tmp_path):
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "role.yml").write_text("options:\n  a: {type: str}\n")
    with pytest.raises(BastetError):
        load_roles(tmp_path)
    (tmp_path / "x" / "role.yml").write_text("options:\n  role: {type: string}\n")
    with pytest.raises(BastetError) as e:
        load_roles(tmp_path)
    assert "reserved" in str(e.value)


def test_every_role_has_examples_that_validate():
    import yaml
    for role in load_roles().values():
        assert role.examples, role.name
        for ex in role.examples:
            assert ex["title"] and check_values(role, yaml.safe_load(ex["yaml"]), role.name) is not None


def test_files_lines_expose_after():
    assert "after" in load_roles()["files"].options["lines"].items.fields
