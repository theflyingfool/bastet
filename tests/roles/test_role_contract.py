import pytest

from bastet.core.errors import BastetError, did_you_mean
from bastet.roles.contract import Option, check_value, check_values, load_roles, with_defaults


def test_shipped_roles_load():
    roles = load_roles()
    assert set(roles) == {"systemd", "packages", "users", "files", "base", "pacman", "proxmox", "ssh", "harden"}
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
    ("systemd", {"ntp": "maybe"}, "expected true or false"),
    ("systemd", {"ntp_service": "ntpd"}, "isn't one of keep, timesyncd, chrony"),
    ("files", {"files": {"/etc/x": {"content": "a", "mode": 420}}}, "quote it"),
    ("files", {"files": {"/etc/x": {"contents": "a"}}}, "unknown field contents"),
    ("packages", {"install": "tree"}, "expected a list"),
    ("users", {"users": {"alice": {"uid": "abc"}}}, "expected a whole number"),
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


def test_unresolved_secret_reference_passes_any_type_check():
    """An unresolved `secret:` reference is checked once more, against the real value, after it's resolved."""
    assert check_value(Option(type="int"), "secret:count", "w") == "secret:count"
    assert check_value(Option(type="bool"), "secret:flag", "w") == "secret:flag"
    assert check_value(Option(type="string", choices=("a", "b")), "secret:x", "w") == "secret:x"


def test_secret_reference_survives_check_values_on_a_non_string_option():
    out = check_values(load_roles()["users"], {"users": {"alice": {"uid": "secret:nick_uid"}}}, "f")
    assert out["users"]["alice"]["uid"] == "secret:nick_uid"


@pytest.mark.parametrize("role,values", [
    ("packages", {"install": [{"version": "1.7"}]}),
    ("packages", {"remove": [{"purge": True}]}),
    ("files", {"lines": [{"line": "x"}]}),
    ("systemd", {"dropins": [{"unit": "a.service"}]}),
])
def test_missing_required_fields_are_named(role, values):
    with pytest.raises(BastetError) as e:
        check_values(load_roles()[role], values, role)
    assert "needs" in str(e.value)


# --- lenient values: Obsidian stores a property as text once it was text anywhere ---


@pytest.mark.parametrize("text", ["true", "True", "TRUE", "yes", "Yes", "YES"])
def test_bool_accepts_true_variants(text):
    assert check_value(Option(type="bool"), text, "w") is True


@pytest.mark.parametrize("text", ["false", "False", "FALSE", "no", "No", "NO"])
def test_bool_accepts_false_variants(text):
    assert check_value(Option(type="bool"), text, "w") is False


def test_bool_invalid_string_still_errors():
    with pytest.raises(BastetError, match="expected true or false"):
        check_value(Option(type="bool"), "maybe", "w")


def test_int_accepts_numeric_text():
    assert check_value(Option(type="int"), "42", "w") == 42
    assert check_value(Option(type="int"), "-5", "w") == -5


def test_int_rejects_float_or_non_numeric_text():
    with pytest.raises(BastetError, match="expected a whole number"):
        check_value(Option(type="int"), "3.0", "w")
    with pytest.raises(BastetError, match="expected a whole number"):
        check_value(Option(type="int"), "abc", "w")


def test_number_accepts_integer_and_float_text():
    assert check_value(Option(type="number"), "42", "w") == 42
    assert check_value(Option(type="number"), "3.14", "w") == 3.14


def test_number_rejects_non_numeric_text():
    with pytest.raises(BastetError, match="expected a number"):
        check_value(Option(type="number"), "abc", "w")


def test_string_type_is_not_made_lenient():
    assert check_value(Option(type="string"), "true", "w") == "true"
    assert check_value(Option(type="string"), "42", "w") == "42"


def test_lenient_parsing_leaves_already_typed_values_unchanged():
    assert check_value(Option(type="bool"), True, "w") is True
    assert check_value(Option(type="int"), 42, "w") == 42
    assert check_value(Option(type="number"), 3.14, "w") == 3.14


# --- did you mean: a typo names up to three close matches, instead of the whole option list ---


def test_did_you_mean_single_match():
    result = did_you_mean("permitroot_login", ["permit_root_login", "allow_root_login", "other"])
    assert "did you mean" in result and "permit_root_login" in result


def test_did_you_mean_at_most_three_matches():
    result = did_you_mean("ntp", ["ntp_service", "manage_ntp", "systemd_ntp", "other1", "other2"])
    assert result.count("`") <= 6  # up to 3 suggestions, each wrapped in a pair of backticks


def test_did_you_mean_no_close_match_is_empty():
    assert did_you_mean("xyz", ["abc", "def", "ghi"]) == ""


def test_check_values_suggests_the_close_option_for_a_typo():
    pk = load_roles()["packages"]
    with pytest.raises(BastetError, match="did you mean|install") as e:
        check_values(pk, {"instll": ["tree"]}, "f")
    assert "install" in str(e.value)
