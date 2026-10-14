"""The lab dashboard lists every site the Caddy roles serve, by hand or collected from other hosts, and never fails on a bad exposure."""

import yaml

from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from bastet.core.render import dashboard, site_listing
from bastet.roles.contract import load_roles

TYPES = load_host_types()
EXPOSURE = {"type": "object", "fields": {"subdomain": {"type": "string"}, "domain": {"type": "string"}, "port": {"type": "int"}}}


def roles(tmp_path):
    folder = tmp_path / "roles" / "app"
    folder.mkdir(parents=True)
    (folder / "app role.md").write_text("---\n" + yaml.safe_dump({
        "bastet": "role-definition", "name": "app", "version": "1.0.0", "api": 0, "description": "A demo app",
        "options": {"proxy": {"type": "list", "items": EXPOSURE}}}) + "---\nNotes.\n", encoding="utf-8")
    return {**load_roles(), **load_roles(tmp_path / "roles")}


def lab(tmp_path, notes, domains=None, name="vault", nas_ip="10.1.0.7"):
    root = tmp_path / name
    files = {"Homelab.md": {"bastet": "lab", "domains": domains or {"public": "example.com", "internal": "example.com"}},
             "hosts/vps1.md": {"bastet": "host", "type": "vps", "ip": "10.1.0.5"},
             "hosts/lab1.md": {"bastet": "host", "type": "vps", "ip": "10.1.0.6"},
             "hosts/nas1.md": {"bastet": "host", "type": "vps", "ip": nas_ip}}
    for key, values in notes.items():
        host, role = key.split("/")
        files[f"_roles/hosts/{host}/{role}.md"] = {"bastet": "role", "role": role, "applies_to": f"[[{host}]]", **values}
    for rel, data in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("---\n" + yaml.safe_dump(data) + "---\n")
    return load_inventory(root, TYPES)


NOTES = {
    "vps1/caddy": {"serves": ["public"]},
    "lab1/caddy": {"serves": ["internal"], "sites": [{"name": "router.example.com", "upstream": "10.1.0.1:443"}]},
    "nas1/app": {"proxy": [{"subdomain": "media", "domain": "public", "port": 8096},
                           {"subdomain": "media", "domain": "internal", "port": 8096}]},
}


def test_every_site_is_listed_once_per_caddy_by_hand_or_collected(tmp_path):
    sites, problems = site_listing(lab(tmp_path, NOTES), TYPES, roles(tmp_path))
    assert problems == []
    assert [(s["name"], s["scope"], s["proxy"], s["upstream"], s["from"]) for s in sites] == [
        ("media.example.com", "internal", "lab1/caddy", "10.1.0.7:8096", "nas1"),
        ("media.example.com", "public", "vps1/caddy", "10.1.0.7:8096", "nas1"),
        ("router.example.com", "", "lab1/caddy", "10.1.0.1:443", "by hand")]


def test_the_dashboard_has_a_sites_table_with_links_to_the_hosts(tmp_path):
    sites, problems = site_listing(lab(tmp_path, NOTES), TYPES, roles(tmp_path))
    text = dashboard(lab(tmp_path, NOTES, name="again"), TYPES, {}, [], sites=sites, site_problems=problems)
    assert "\n## Sites\n\n| Site | Scope | Served by | Upstream | From |\n|---|---|---|---|---|\n" in text
    assert "| media.example.com | public | [[vps1]] (caddy) | 10.1.0.7:8096 | [[nas1]] |\n" in text
    assert "| router.example.com |  | [[lab1]] (caddy) | 10.1.0.1:443 | by hand |\n" in text
    assert "Not collected" not in text


def test_no_sites_means_no_section(tmp_path):
    inv = lab(tmp_path, {"vps1/caddy": {"serves": ["public"]}})
    assert site_listing(inv, TYPES, roles(tmp_path)) == ([], [])
    assert "## Sites" not in dashboard(inv, TYPES, {}, [], sites=[], site_problems=[])
    assert "## Sites" not in dashboard(inv, TYPES, {}, [])


def test_a_clash_shows_as_a_problem_and_the_dashboard_still_renders(tmp_path):
    notes = {**NOTES, "nas1/app": {"proxy": [{"subdomain": "router", "domain": "internal", "port": 80},
                                            {"subdomain": "media", "domain": "public", "port": 8096}]}}
    inv = lab(tmp_path, notes)
    sites, problems = site_listing(inv, TYPES, roles(tmp_path))
    assert [s["name"] for s in sites] == ["media.example.com", "router.example.com"]
    assert [s["from"] for s in sites] == ["nas1", "by hand"]
    [problem] = problems
    assert "router.example.com" in problem and "nothing wins silently" in problem
    text = dashboard(inv, TYPES, {}, [], sites=sites, site_problems=problems)
    assert "\n### Not collected\n\n- " in text and "router.example.com comes from both" in text


def test_a_lab_without_a_caddy_gets_nothing_from_any_of_this_even_when_another_host_is_broken(tmp_path):
    inv = lab(tmp_path, {"nas1/nosuchrole": {}, "nas1/app": {"proxy": [{"subdomain": "media", "domain": "public", "port": 8096}]}})
    known = roles(tmp_path)
    sites, problems = site_listing(inv, TYPES, known)
    assert (sites, problems) == ([], [])
    assert "Sites" not in dashboard(inv, TYPES, {}, [], sites=sites, site_problems=problems)


def test_an_ipv6_upstream_is_bracketed(tmp_path):
    inv = lab(tmp_path, {"lab1/caddy": {"serves": ["internal"]},
                         "nas1/app": {"proxy": [{"subdomain": "media", "domain": "internal", "port": 8096}]}}, nas_ip="fd00::7")
    [site] = site_listing(inv, TYPES, roles(tmp_path))[0]
    assert site["upstream"] == "[fd00::7]:8096"


def test_a_host_whose_roles_cannot_be_resolved_does_not_stop_the_listing(tmp_path):
    inv = lab(tmp_path, {**NOTES, "nas1/nosuchrole": {}})
    sites, problems = site_listing(inv, TYPES, roles(tmp_path))
    assert [s["name"] for s in sites] == ["router.example.com"]
    assert len(problems) == 1 and "nosuchrole" in problems[0]
