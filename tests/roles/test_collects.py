"""The `collects` contract key: a role gathers the `proxy` exposures other hosts' roles declare into one of its lists."""

from pathlib import Path

import pytest
import yaml

from bastet.core.errors import BastetError
from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.collect import collect, collect_all, warnings_for
from bastet.roles.contract import load_roles, parse_role
from bastet.roles.resolve import resolve

TYPES = load_host_types()
EXPOSURE = {"type": "object", "fields": {
    "subdomain": {"type": "string"}, "domain": {"type": "string"}, "port": {"type": "int"}, "via": {"type": "any"},
    "upstream": {"type": "string"}}}
SITE = {"type": "object", "fields": {"name": {"type": "string"}, "upstream": {"type": "string"}, "host": {"type": "string"},
                                     "source": {"type": "string"}}}
GATE_OPTIONS = {"serves": {"type": "list", "items": {"type": "string"}}, "sites": {"type": "list", "items": SITE}}
HOSTS = {"vps1": {"ip": "10.1.0.5"}, "lab1": {"ip": "10.1.0.6"}, "nas1": {"ip": "10.1.0.7"}}


def role_file(folder: Path, name: str, options: dict, **extra) -> Path:
    (folder / name).mkdir(parents=True)
    data = {"bastet": "role-definition", "name": name, "version": "1.0.0", "api": 0, "description": f"A demo {name} role",
            "options": options, **extra}
    path = folder / name / f"{name} role.md"
    path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\nNotes.\n", encoding="utf-8")
    return path


def demo_roles(tmp_path: Path) -> dict:
    folder = tmp_path / "roles"
    role_file(folder, "gate", GATE_OPTIONS, collects={"proxy": "sites"},
              files=[{"path": "/etc/gate/{{ item.name }}.conf", "content": "{{ item.name }} {{ item.upstream }}\n", "each": "sites"}])
    role_file(folder, "app", {"proxy": {"type": "list", "items": EXPOSURE}}, packages=["app-pkg"])
    role_file(folder, "keyed", {"proxy": {"type": "list", "items": {"type": "object", "fields": {
        "subdomain": {"type": "string"}, "port": {"type": "int"}, "token": {"type": "string", "secret": True}}}}})
    role_file(folder, "plain", {"x": {"type": "string"}})
    return {**load_roles(), **load_roles(folder)}


def lab(tmp_path: Path, domains: dict | None = None, hosts: dict | None = None, notes: dict | None = None, name: str = "vault"):
    """hosts: name -> frontmatter; notes: 'host/role' -> option values."""
    root = tmp_path / name
    files = {"Homelab.md": "---\n" + yaml.safe_dump({"bastet": "lab", "domains": domains or {"public": "example.com"}}) + "---\n"}
    for host, data in (hosts or {}).items():
        files[f"hosts/{host}.md"] = "---\n" + yaml.safe_dump({"bastet": "host", "type": "vps", **data}) + "---\n"
    for key, values in (notes or {}).items():
        host, role = key.split("/")
        files[f"_roles/hosts/{host}/{role}.md"] = "---\n" + yaml.safe_dump(
            {"bastet": "role", "role": role, "applies_to": f"[[{host}]]", **values}) + "---\n"
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    return load_inventory(root, TYPES)


def sites_of(inv, roles, host="lab1", role="gate"):
    return collect(inv, inv.get(host), TYPES, roles)[role]


def names(sites):
    return sorted((s["name"], s["upstream"], s["host"]) for s in sites)


def test_a_demo_role_collects_sites_from_two_hosts_and_two_caddies(tmp_path):
    roles = demo_roles(tmp_path)
    inv = lab(tmp_path, {"public": "example.com", "internal": "lab.example.com"}, HOSTS, {
        "vps1/gate": {"serves": ["public"]}, "lab1/gate": {"serves": ["internal"]},
        "vps1/app": {"proxy": [{"subdomain": "git", "domain": "public", "port": 3000}]},
        "nas1/app": {"proxy": [{"subdomain": "media", "domain": "internal", "port": 8096}]}})
    assert names(sites_of(inv, roles, "vps1")) == [("git.example.com", "127.0.0.1:3000", "vps1")]
    assert names(sites_of(inv, roles, "lab1")) == [("media.lab.example.com", "10.1.0.7:8096", "nas1")]
    assert sites_of(inv, roles, "lab1")[0]["source"] == "nas1/app proxy[0]"
    assert sorted(collect_all(inv, TYPES, roles)) == [("lab1", "gate"), ("vps1", "gate")]


def test_collected_sites_join_the_manual_ones_in_the_files_the_role_builds(tmp_path):
    roles = demo_roles(tmp_path)
    inv = lab(tmp_path, None, HOSTS, {"vps1/gate": {"serves": ["public"], "sites": [{"name": "router.example.com", "upstream": "10.1.0.1:443"}]},
                                      "nas1/app": {"proxy": [{"subdomain": "media", "port": 8096}]}})
    host = inv.get("vps1")
    gate = [a for a in resolve(inv, host, TYPES, roles) if a.role.name == "gate"]
    info = HostInfo(name="vps1", type="vps", data={"os": "Arch Linux"}, root=Path("/x"), lab={}, collected=collect(inv, host, TYPES, roles))
    files = {f.path: f.content for b in batches_for(gate, info) for f in b.resources}
    assert files == {"/etc/gate/router.example.com.conf": "router.example.com 10.1.0.1:443\n",
                     "/etc/gate/media.example.com.conf": "media.example.com 10.1.0.7:8096\n"}


def test_nothing_collected_leaves_the_manual_list_alone(tmp_path):
    roles = demo_roles(tmp_path)
    inv = lab(tmp_path, None, HOSTS, {"vps1/gate": {"serves": ["public"], "sites": [{"name": "router.example.com", "upstream": "10.1.0.1:443"}]}})
    host = inv.get("vps1")
    gate = [a for a in resolve(inv, host, TYPES, roles) if a.role.name == "gate"]
    info = HostInfo(name="vps1", type="vps", data={"os": "Arch Linux"}, root=Path("/x"), lab={}, collected=collect(inv, host, TYPES, roles))
    assert [f.path for b in batches_for(gate, info) for f in b.resources] == ["/etc/gate/router.example.com.conf"]


def test_with_no_collects_anywhere_nothing_is_collected_or_warned(tmp_path):
    roles = {n: r for n, r in demo_roles(tmp_path).items() if n not in ("gate", "caddy")}
    inv = lab(tmp_path, None, HOSTS, {"vps1/plain": {"x": "1"}, "nas1/app": {"proxy": [{"subdomain": "media", "port": 8096}]}})
    for host in ("vps1", "nas1"):
        assert collect(inv, inv.get(host), TYPES, roles) == {}
        assert warnings_for(inv, inv.get(host), TYPES, roles) == []
    assert collect_all(inv, TYPES, roles) == {}
    assert HostInfo(name="vps1", type="vps", data={}, root=Path("/x")).collected == {}


@pytest.mark.parametrize(("gates", "exposure", "expect"), [
    pytest.param({"vps1": ["public"], "lab1": ["internal"]}, {"domain": "internal"}, ["lab1"], id="one caddy serves the scope"),
    pytest.param({"vps1": ["public"], "lab1": ["public"]}, {"domain": "public", "via": "[[lab1/gate]]"}, ["lab1"], id="via pins one"),
    pytest.param({"vps1": ["public"], "lab1": ["public"]}, {"domain": "public", "via": ["[[lab1/gate]]", "[[vps1/gate]]"]},
                 ["lab1", "vps1"], id="via lists several"),
    pytest.param({"vps1": ["public"], "lab1": ["internal"]}, {"domain": "public", "via": "[[lab1/gate]]"}, ["lab1"],
                 id="via beats serves"),
    pytest.param({"vps1": ["internal"], "lab1": ["internal"]}, {"domain": "public"}, [], id="none serves the scope"),
])
def test_routing_table(tmp_path, gates, exposure, expect):
    roles = demo_roles(tmp_path)
    notes = {f"{h}/gate": {"serves": s} for h, s in gates.items()}
    notes["nas1/app"] = {"proxy": [{"subdomain": "media", "port": 8096, **exposure}]}
    inv = lab(tmp_path, {"public": "example.com", "internal": "example.com"}, HOSTS, notes)
    got = collect_all(inv, TYPES, roles)
    assert sorted(h for (h, _), s in got.items() if s) == expect


def test_none_serving_the_scope_warns_on_the_exposing_host(tmp_path):
    roles = demo_roles(tmp_path)
    inv = lab(tmp_path, None, HOSTS, {"vps1/gate": {"serves": []}, "nas1/app": {"proxy": [{"subdomain": "media", "port": 8096}]}})
    [(role, text)] = warnings_for(inv, inv.get("nas1"), TYPES, roles)
    assert role == "app" and "public" in text and "media.example.com" in text
    assert warnings_for(inv, inv.get("vps1"), TYPES, roles) == []


def test_one_name_on_two_caddies_is_split_horizon_but_on_one_caddy_an_error(tmp_path):
    roles = demo_roles(tmp_path)
    domains = {"public": "example.com", "internal": "example.com"}
    both = [{"subdomain": "vault", "domain": "public", "port": 8222}, {"subdomain": "vault", "domain": "internal", "port": 8222}]
    inv = lab(tmp_path, domains, HOSTS, {"vps1/gate": {"serves": ["public"]}, "lab1/gate": {"serves": ["internal"]}, "nas1/app": {"proxy": both}})
    assert [s["name"] for s in sites_of(inv, roles, "vps1")] == ["vault.example.com"]
    assert [s["name"] for s in sites_of(inv, roles, "lab1")] == ["vault.example.com"]
    shared = lab(tmp_path, domains, HOSTS, {"lab1/gate": {"serves": ["public", "internal"]}, "nas1/app": {"proxy": both}}, name="two")
    with pytest.raises(BastetError, match=r"vault\.example\.com.*proxy\[0\].*proxy\[1\]") as exc:
        sites_of(shared, roles, "lab1")
    assert exc.value.file.name == "app.md"


def test_a_manual_site_counts_as_a_source_for_duplicates(tmp_path):
    roles = demo_roles(tmp_path)
    manual = [{"name": "Media.example.com.", "upstream": "10.1.0.9:80"}]
    inv = lab(tmp_path, None, HOSTS, {"vps1/gate": {"serves": ["public"], "sites": manual},
                                      "nas1/app": {"proxy": [{"subdomain": "media", "port": 8096}]}})
    with pytest.raises(BastetError, match=r"media\.example\.com.*vps1/gate sites\[0\].*nas1/app proxy\[0\]"):
        sites_of(inv, roles, "vps1")


def test_serves_can_come_from_a_group_note(tmp_path):
    roles = demo_roles(tmp_path)
    lab(tmp_path, None, {**HOSTS, "lab1": {"ip": "10.1.0.6", "groups": ["[[proxies]]"]}},
              {"nas1/app": {"proxy": [{"subdomain": "m", "port": 1}]}})
    root = tmp_path / "vault"
    (root / "groups").mkdir()
    (root / "groups" / "proxies.md").write_text("---\nbastet: group\n---\n")
    (root / "_roles" / "groups" / "proxies").mkdir(parents=True)
    (root / "_roles" / "groups" / "proxies" / "gate.md").write_text(
        '---\nbastet: role\nrole: gate\napplies_to: "[[proxies]]"\nserves: [public]\n---\n')
    assert names(sites_of(load_inventory(root, TYPES), roles)) == [("m.example.com", "10.1.0.7:1", "nas1")]


@pytest.mark.parametrize(("domains", "exposure", "message"), [
    pytest.param({"public": "example.com"}, {"domain": "lan"}, r"lan.*public", id="scope not in domains"),
    pytest.param({"public": "example.com", "internal": "example.com"}, {}, r"internal, public", id="no scope, several domains"),
    pytest.param({"public": "example.com"}, {"via": "[[lab1/plain]]"}, r"plain.*collects", id="via names a non-collecting role"),
    pytest.param({"public": "example.com"}, {"via": "[[lab1/nothing]]"}, r"nothing", id="via names no role"),
    pytest.param({"public": "example.com"}, {"upstream": "secret:app-upstream"}, r"secret", id="secret reference in proxy"),
    pytest.param({"public": "example.com"}, {"port": None}, r"port or an upstream", id="no port and no upstream"),
])
def test_exposure_errors_name_the_file(tmp_path, domains, exposure, message):
    roles = demo_roles(tmp_path)
    item = {k: v for k, v in {"subdomain": "media", "port": 8096, **exposure}.items() if v is not None}
    inv = lab(tmp_path, domains, HOSTS, {"lab1/gate": {"serves": ["public"]}, "lab1/plain": {"x": "1"}, "nas1/app": {"proxy": [item]}})
    with pytest.raises(BastetError, match=message) as exc:
        collect_all(inv, TYPES, roles)
    assert exc.value.file.name == "app.md" and exc.value.key == "proxy"


def test_a_proxy_option_with_a_secret_field_is_refused(tmp_path):
    roles = demo_roles(tmp_path)
    inv = lab(tmp_path, None, HOSTS, {"vps1/gate": {"serves": ["public"]}, "nas1/keyed": {"proxy": [{"subdomain": "media", "port": 1}]}})
    with pytest.raises(BastetError, match="secret") as exc:
        collect_all(inv, TYPES, roles)
    assert exc.value.file.name == "keyed.md" and exc.value.key == "proxy"


def test_two_caddies_serving_a_scope_need_via_and_both_sides_are_told(tmp_path):
    roles = demo_roles(tmp_path)
    inv = lab(tmp_path, None, HOSTS, {"vps1/gate": {"serves": ["public"]}, "lab1/gate": {"serves": ["public"]},
                                      "nas1/app": {"proxy": [{"subdomain": "media", "port": 8096}]}})
    for host in ("nas1", "vps1", "lab1"):
        with pytest.raises(BastetError, match=r"nas1/app.*vps1/gate.*lab1/gate|nas1/app.*lab1/gate.*vps1/gate.*via") as exc:
            collect(inv, inv.get(host), TYPES, roles)
        assert exc.value.file.name == "app.md"


def test_an_exposure_error_does_not_stop_unrelated_hosts(tmp_path):
    roles = demo_roles(tmp_path)
    inv = lab(tmp_path, None, {**HOSTS, "pve1": {"ip": "10.1.0.8"}},
              {"vps1/gate": {"serves": ["public"]}, "nas1/app": {"proxy": [{"subdomain": "media", "domain": "lan", "port": 1}]}})
    assert collect(inv, inv.get("pve1"), TYPES, roles) == {}
    with pytest.raises(BastetError, match="lan"):
        collect(inv, inv.get("nas1"), TYPES, roles)


def test_serves_naming_an_unknown_scope_names_the_caddys_note(tmp_path):
    roles = demo_roles(tmp_path)
    inv = lab(tmp_path, None, HOSTS, {"vps1/gate": {"serves": ["lan"]}})
    with pytest.raises(BastetError, match=r"lan.*public") as exc:
        collect_all(inv, TYPES, roles)
    assert exc.value.file.name == "gate.md" and exc.value.key == "serves"


def test_an_exposure_without_an_address_needs_an_upstream(tmp_path):
    roles = demo_roles(tmp_path)
    hosts = {"vps1": {"ip": "10.1.0.5"}, "box": {"ip": "dhcp"}}
    exposure = {"subdomain": "media", "port": 80}
    inv = lab(tmp_path, None, hosts, {"vps1/gate": {"serves": ["public"]}, "box/app": {"proxy": [exposure]}})
    with pytest.raises(BastetError, match=r"address.*upstream") as exc:
        collect_all(inv, TYPES, roles)
    assert exc.value.file.name == "app.md"
    inv = lab(tmp_path, None, hosts, {"vps1/gate": {"serves": ["public"]}, "box/app": {"proxy": [{**exposure, "upstream": "10.1.0.50:80"}]}},
              name="ok")
    assert names(sites_of(inv, roles, "vps1")) == [("media.example.com", "10.1.0.50:80", "box")]


def test_an_unmanaged_host_is_still_scanned(tmp_path):
    roles = demo_roles(tmp_path)
    hosts = {"vps1": {"ip": "10.1.0.5"}, "router": {"type": "other", "ip": "10.1.0.1"}}
    inv = lab(tmp_path, None, hosts, {"vps1/gate": {"serves": ["public"]}})
    assert collect(inv, inv.get("vps1"), TYPES, roles) == {"gate": []}
    assert collect(inv, inv.get("router"), TYPES, roles) == {}


def test_the_hostname_is_subdomain_plus_the_only_domain_lowercased(tmp_path):
    roles = demo_roles(tmp_path)
    inv = lab(tmp_path, {"home": "Lab.Example.com"}, HOSTS, {"vps1/gate": {"serves": ["home"]},
                                                              "nas1/app": {"proxy": [{"subdomain": "a.b", "port": 1}]}})
    assert [s["name"] for s in sites_of(inv, roles, "vps1")] == ["a.b.lab.example.com"]


@pytest.mark.parametrize(("extra", "message"), [
    pytest.param({"collects": {"dns": "sites"}}, r"dns.*proxy", id="unknown source"),
    pytest.param({"collects": {"proxy": "nothing"}}, r"nothing", id="target missing"),
    pytest.param({"collects": {"proxy": "text"}}, r"list", id="target not a list"),
    pytest.param({"collects": ["proxy"]}, r"collects must be a map", id="not a map"),
])
def test_collects_is_checked_when_the_role_is_read(tmp_path, extra, message):
    path = role_file(tmp_path, "gate", {**GATE_OPTIONS, "text": {"type": "string"}}, **extra)
    with pytest.raises(BastetError, match=message) as exc:
        parse_role(path)
    assert exc.value.file == path and exc.value.key == "collects"


def test_a_collecting_role_needs_a_serves_list(tmp_path):
    path = role_file(tmp_path, "gate", {"sites": GATE_OPTIONS["sites"]}, collects={"proxy": "sites"})
    with pytest.raises(BastetError, match="serves") as exc:
        parse_role(path)
    assert exc.value.file == path


def test_plan_for_hands_the_collected_sites_to_the_build_and_warns_the_exposing_host(tmp_path):
    from types import SimpleNamespace

    from bastet.cli import run as run_mod

    roles = demo_roles(tmp_path)
    inv = lab(tmp_path, {"public": "example.com", "internal": "example.com"}, HOSTS, {
        "vps1/gate": {"serves": ["public"]}, "nas1/app": {"proxy": [
            {"subdomain": "media", "domain": "public", "port": 8096}, {"subdomain": "nas", "domain": "internal", "port": 80}]}})
    ctx = SimpleNamespace(inventory=inv, types=TYPES, secrets=None, root=tmp_path)
    _, batches = run_mod.plan_for(ctx, inv.get("vps1"), roles)
    assert [f.path for b in batches for f in b.resources] == ["/etc/gate/media.example.com.conf"]
    _, batches = run_mod.plan_for(ctx, inv.get("nas1"), roles)
    [note] = [n for b in batches for n in b.notes]
    assert note.level == "warning" and "internal" in note.message


def test_the_role_page_shows_what_the_role_collects(tmp_path):
    from bastet.roles.pages import role_page, roles_markdown

    gate = demo_roles(tmp_path)["gate"]
    assert "Collects `proxy` exposures from other hosts' roles into `sites`" in role_page(gate, [])
    assert "into `sites`" in roles_markdown({"gate": gate})


def test_a_domain_that_is_not_text_names_the_lab_note(tmp_path):
    roles = demo_roles(tmp_path)
    inv = lab(tmp_path, {"public": 5}, HOSTS, {"vps1/gate": {"serves": ["public"]}, "nas1/app": {"proxy": [{"subdomain": "m", "port": 1}]}})
    with pytest.raises(BastetError, match=r"public.*domain name") as exc:
        collect_all(inv, TYPES, roles)
    assert exc.value.file.name == "Homelab.md" and exc.value.key == "domains"


def test_a_bad_note_on_one_host_only_fails_that_host(tmp_path):
    roles = demo_roles(tmp_path)
    inv = lab(tmp_path, None, {**HOSTS, "pve1": {"ip": "10.1.0.8"}}, {
        "vps1/gate": {"serves": ["public"]}, "nas1/app": {"proxy": [{"subdomain": "media", "port": 1}]},
        "pve1/nothing": {"x": 1}})
    assert names(sites_of(inv, roles, "vps1")) == [("media.example.com", "10.1.0.7:1", "nas1")]
    assert collect(inv, inv.get("nas1"), TYPES, roles) == {}
    with pytest.raises(BastetError, match="nothing"):
        collect(inv, inv.get("pve1"), TYPES, roles)
    with pytest.raises(BastetError, match="nothing"):
        collect_all(inv, TYPES, roles)


def test_a_same_host_proxy_needs_no_address(tmp_path):
    roles = demo_roles(tmp_path)
    hosts = {"vps1": {"ip": "dhcp"}, "lab1": {"ip": "10.1.0.6"}}
    app = {"proxy": [{"subdomain": "wiki", "port": 3000}]}
    inv = lab(tmp_path, None, hosts, {"vps1/gate": {"serves": ["public"]}, "vps1/app": app})
    assert names(sites_of(inv, roles, "vps1")) == [("wiki.example.com", "127.0.0.1:3000", "vps1")]
    other = lab(tmp_path, None, hosts, {"lab1/gate": {"serves": ["public"]}, "vps1/app": app}, name="other")
    with pytest.raises(BastetError, match=r"address.*upstream") as exc:
        collect_all(other, TYPES, roles)
    assert exc.value.file.name == "app.md"
