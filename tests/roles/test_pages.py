from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from bastet.roles.contract import load_roles
from bastet.roles.pages import role_page, role_page_path, role_pages

TYPES = load_host_types()


def test_role_page_lists_every_option_and_users():
    text = role_page(load_roles()["packages"], [("media01", ["lab", "host media01"])])
    assert text.startswith("---\ngenerated: true\nrole: packages\n---\n# packages role")
    assert "| install | list of object |" in text and "| install[].version | string |" in text
    assert "| refresh | bool | true |" in text
    assert "- [[media01]]: lab, host media01" in text


def test_role_pages_for_inventory(tmp_path):
    (tmp_path / "Homelab.md").write_text("---\nbastet: lab\n---\n# Homelab\n")
    (tmp_path / "hosts").mkdir()
    (tmp_path / "hosts" / "media01.md").write_text("---\nbastet: host\ntype: vm\nip: 10.0.10.5\n---\n# media01\n")
    (tmp_path / "_roles" / "lab").mkdir(parents=True)
    (tmp_path / "_roles" / "lab" / "packages.md").write_text('---\nbastet: role\nrole: packages\napplies_to: "[[Homelab]]"\n---\n')
    pages = role_pages(load_inventory(tmp_path, TYPES), TYPES)
    assert set(pages) == {role_page_path(tmp_path, r) for r in load_roles()} | {tmp_path / "_bastet" / "Roles.md"}
    assert "- [[media01]]: lab" in pages[role_page_path(tmp_path, "packages")]
    assert "(no hosts yet)" in pages[role_page_path(tmp_path, "users")]


def test_role_page_has_examples_before_options():
    text = role_page(load_roles()["packages"], [])
    assert "## Examples" in text and text.index("## Examples") < text.index("## Options")
    assert "```yaml\ninstall:\n" in text


def test_options_in_page_text_are_spotted():
    from bastet.roles.pages import options_in_body
    role = load_roles()["packages"]
    assert options_in_body(role, "# packages for hp-13\n\ninstall:\n- tree\n") == ["install"]
    assert options_in_body(role, "# notes\n\nI install things here\n```yaml\ninstall:\n```\n") == []


def test_roles_index_lists_every_role_with_description_and_users():
    from bastet.roles.pages import roles_index
    roles = load_roles()
    text = roles_index(roles, {"packages": ["pve1", "git1"]})
    for name in roles:
        assert f"[[{name} role\\|{name}]]" in text
    assert "| 2: [[pve1]], [[git1]] |" in text
    assert roles["base"].description.split(". ")[0].rstrip(".") in text


def test_repo_roles_doc_is_current():
    import importlib.util
    from pathlib import Path
    root = Path(__file__).parents[2]
    spec = importlib.util.spec_from_file_location("gen", root / "scripts" / "gen_roles_doc.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert gen.render() == (root / "docs" / "roles.md").read_text(), "run: uv run python scripts/gen_roles_doc.py"
