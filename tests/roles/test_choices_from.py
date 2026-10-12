import pytest

from bastet.core.errors import BastetError
from bastet.roles.contract import Option, RoleDef, check_values, load_roles
from bastet.roles.pages import role_page, roles_markdown


def make_role(tmp_path, options: str, files: dict[str, str | bytes] | None = None, name="demo"):
    folder = tmp_path / name
    folder.mkdir(exist_ok=True)
    for fname, content in (files or {}).items():
        target = folder / fname
        target.write_bytes(content if isinstance(content, bytes) else content.encode())
    (folder / f"{name} role.md").write_text(
        f"---\nbastet: role-definition\nname: {name}\nversion: 1.0.0\napi: 0\ndescription: A demo.\n"
        f"options:\n{options}---\n# {name}\n")
    return load_roles(tmp_path)[name]


ZONES = "# zones\n\nEurope/Berlin\n  UTC  \nAsia/Tokyo\n"
STRING = "  zone: {type: string, choices_from: zones.txt}\n"


def test_values_come_from_the_file_ignoring_comments_blanks_and_spaces(tmp_path):
    role = make_role(tmp_path, STRING, {"zones.txt": ZONES})
    opt = role.options["zone"]
    assert opt.choices == ("Europe/Berlin", "UTC", "Asia/Tokyo")
    assert opt.choices_file == "zones.txt"
    assert check_values(role, {"zone": "UTC"}, "w") == {"zone": "UTC"}


def test_bad_value_names_option_and_file_without_the_list(tmp_path):
    role = make_role(tmp_path, STRING, {"zones.txt": ZONES})
    with pytest.raises(BastetError) as e:
        check_values(role, {"zone": "Asia/Tokio"}, "demo")
    msg = str(e.value)
    assert "'Asia/Tokio' isn't one of the values in zones.txt" in msg
    assert "did you mean `Asia/Tokyo`?" in msg
    assert "Europe/Berlin" not in msg
    with pytest.raises(BastetError) as e:
        check_values(role, {"zone": "Mars/Base"}, "demo")
    assert "isn't one of the values in zones.txt" in str(e.value) and "did you mean" not in str(e.value)


def test_works_on_list_and_map_items(tmp_path):
    options = ("  zones:\n    type: list\n    items: {type: string, choices_from: zones.txt}\n"
               "  by_host:\n    type: map\n    items: {type: string, choices_from: zones.txt}\n")
    role = make_role(tmp_path, options, {"zones.txt": ZONES})
    assert check_values(role, {"zones": ["UTC"], "by_host": {"a": "UTC"}}, "w")
    with pytest.raises(BastetError, match="isn't one of the values in zones.txt"):
        check_values(role, {"zones": ["UTC", "Mars/Base"]}, "w")
    with pytest.raises(BastetError, match="isn't one of the values in zones.txt"):
        check_values(role, {"by_host": {"a": "Mars/Base"}}, "w")


def test_secret_reference_is_not_checked(tmp_path):
    role = make_role(tmp_path, STRING, {"zones.txt": ZONES})
    assert check_values(role, {"zone": "secret:zone"}, "w") == {"zone": "secret:zone"}


@pytest.mark.parametrize("ref", ["/etc/hostname", "../outside.txt", "sub/../../outside.txt"])
def test_file_must_stay_inside_the_role_folder(tmp_path, ref):
    (tmp_path / "outside.txt").write_text("a\n")
    with pytest.raises(BastetError) as e:
        make_role(tmp_path, f"  zone: {{type: string, choices_from: {ref}}}\n", {"zones.txt": ZONES})
    assert "demo" in str(e.value) and ref in str(e.value) and "choices_from" in str(e.value)


def test_symlink_out_of_the_folder_is_refused(tmp_path):
    (tmp_path / "outside.txt").write_text("a\n")
    folder = tmp_path / "demo"
    folder.mkdir()
    (folder / "zones.txt").symlink_to(tmp_path / "outside.txt")
    with pytest.raises(BastetError, match="inside the role's folder"):
        make_role(tmp_path, STRING)


def test_missing_file_is_refused(tmp_path):
    with pytest.raises(BastetError) as e:
        make_role(tmp_path, STRING)
    assert "demo.zone" in str(e.value) and "zones.txt" in str(e.value) and "choices_from" in str(e.value)


def test_unreadable_text_is_refused(tmp_path):
    with pytest.raises(BastetError, match="zones.txt"):
        make_role(tmp_path, STRING, {"zones.txt": b"\xff\xfe\x00bad"})


@pytest.mark.parametrize("text", ["", "# only a comment\n\n   \n"])
def test_file_needs_at_least_one_value(tmp_path, text):
    with pytest.raises(BastetError, match="no values"):
        make_role(tmp_path, STRING, {"zones.txt": text})


def test_duplicates_are_refused(tmp_path):
    with pytest.raises(BastetError, match="twice"):
        make_role(tmp_path, STRING, {"zones.txt": "UTC\nAsia/Tokyo\n UTC\n"})


def test_with_choices_is_refused(tmp_path):
    with pytest.raises(BastetError, match="choices_from.*choices|choices.*choices_from"):
        make_role(tmp_path, "  zone: {type: string, choices: [a], choices_from: zones.txt}\n", {"zones.txt": ZONES})


def test_choices_from_must_be_a_file_name(tmp_path):
    with pytest.raises(BastetError, match="choices_from"):
        make_role(tmp_path, "  zone: {type: string, choices_from: [zones.txt]}\n", {"zones.txt": ZONES})


@pytest.mark.parametrize("typ", ["int", "bool", "object", "any"])
def test_only_string_options_take_it(tmp_path, typ):
    with pytest.raises(BastetError, match="choices_from only applies to string"):
        make_role(tmp_path, f"  v: {{type: {typ}, choices_from: zones.txt}}\n", {"zones.txt": ZONES})


def test_list_of_non_strings_is_refused(tmp_path):
    with pytest.raises(BastetError, match="choices_from only applies to string"):
        make_role(tmp_path, "  v:\n    type: list\n    items: {type: int}\n    choices_from: zones.txt\n",
                  {"zones.txt": ZONES})


def test_on_the_list_option_itself_with_string_items(tmp_path):
    role = make_role(tmp_path, "  v:\n    type: list\n    items: {type: string}\n    choices_from: zones.txt\n",
                     {"zones.txt": ZONES})
    assert check_values(role, {"v": ["UTC", "Asia/Tokyo"]}, "w")
    with pytest.raises(BastetError, match="isn't one of the values in zones.txt"):
        check_values(role, {"v": ["Mars/Base"]}, "w")


def test_docs_show_short_lists_inline_and_long_lists_collapsed(tmp_path):
    short = Option(type="string", choices=("a", "b"), choices_file="short.txt")
    long = Option(type="string", choices=tuple(f"v{i:02d}" for i in range(25)), choices_file="zones.txt")
    role = RoleDef("demo", "A demo.", {"short": short, "long": long}, tmp_path / "demo" / "demo role.md")
    for text in (role_page(role, []), roles_markdown({"demo": role})):
        assert "(one of a, b)" in text
        assert "<details><summary>25 allowed values</summary>" in text
        assert "v00, v01" in text and "v24" in text and "</details>" in text
        assert "one of v00" not in text
