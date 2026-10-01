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
    assert set(pages) == {role_page_path(tmp_path, r) for r in ("systemd", "packages", "users", "files")}
    assert "- [[media01]]: lab" in pages[role_page_path(tmp_path, "packages")]
    assert "(no hosts yet)" in pages[role_page_path(tmp_path, "users")]
