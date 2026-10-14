"""The plain `caddy` role: what it builds with no options, from sites, and how it validates and reloads."""

from pathlib import Path

import pytest
import yaml

from bastet.core.errors import BastetError
from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from bastet.engine.command import Command
from bastet.engine.files import Directory, File
from bastet.engine.packages import Package
from bastet.engine.systemd import Unit
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.collect import collect
from bastet.roles.contract import check_values, load_roles, with_defaults
from bastet.roles.resolve import Applied, resolve

ROLES = load_roles()
CADDY = ROLES["caddy"]
TYPES = load_host_types()
CADDYFILE = "/etc/caddy/Caddyfile"
CONF_D = "/etc/caddy/conf.d"
SOCKET = 'admin "unix//run/caddy/admin.socket"'
VALIDATE = "caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile"
ARCH = HostInfo(name="vps1", type="vps", data={"os": "Arch Linux"}, root=Path("/nonexistent"), lab={})


def build(values, host=ARCH):
    """(resources, notes) the caddy role builds for one host from these option values."""
    applied = Applied(CADDY, with_defaults(CADDY, check_values(CADDY, values, "caddy")), origins={})
    batches = batches_for([applied], host)
    return [r for b in batches for r in b.resources], [n for b in batches for n in b.notes]


def files(resources):
    return {r.path: r for r in resources if isinstance(r, File)}


def caddyfile(values):
    return files(build(values)[0])[CADDYFILE].content


def site_file(site, **extra):
    return files(build({"sites": [site], **extra})[0])[f"{CONF_D}/{site['name']}.caddy"].content


def test_no_options_build_exactly_the_documented_defaults():
    resources, notes = build({})
    assert notes == []
    assert [type(r) for r in resources] == [File, Directory, Package, Unit, Command]
    caddyfile_, conf_d, package, unit, standing = resources
    assert package.name == "caddy"
    assert caddyfile_.path == CADDYFILE
    assert caddyfile_.content == (
        "# Managed by Bastet (the caddy role); changes made here are overwritten.\n{\n\t" + SOCKET + "\n}\n\n"
        "import /etc/caddy/conf.d/*\n")
    assert "http://" not in caddyfile_.content and "email" not in caddyfile_.content
    assert conf_d.path == CONF_D
    assert (unit.name, unit.enabled, unit.state) == ("caddy.service", True, "up")
    assert standing.run == "runuser -u caddy -- env XDG_DATA_HOME=/var/lib XDG_CONFIG_HOME=/etc " + VALIDATE


def test_unset_email_writes_no_global_line_and_a_set_one_does():
    assert "email" not in caddyfile({"log_level": "INFO"})
    assert "\temail admin@example.com\n" in caddyfile({"email": "admin@example.com"})


def test_global_options_are_written_and_admin_replaces_the_socket():
    text = caddyfile({"admin": "off", "log_level": "DEBUG", "trusted_proxies": ["10.1.0.0/16", "10.2.0.1"], "extra": "debug\n"})
    assert text == ("# Managed by Bastet (the caddy role); changes made here are overwritten.\n{\n\tadmin off\n"
                    "\tlog {\n\t\tlevel DEBUG\n\t}\n\tservers {\n\t\ttrusted_proxies static 10.1.0.0/16 10.2.0.1\n\t}\n"
                    "\tdebug\n}\n\nimport /etc/caddy/conf.d/*\n")
    assert SOCKET not in text


def test_extra_text_goes_inside_the_global_block_and_snippets_before_the_import():
    text = caddyfile({"extra": "servers {\n\ttimeouts\n}\n", "snippets": {"security": "header X-Frame-Options DENY\nencode gzip\n"}})
    assert "\tservers {\n\t\ttimeouts\n\t}\n}\n" in text
    assert "\n(security) {\n\theader X-Frame-Options DENY\n\tencode gzip\n}\n\nimport /etc/caddy/conf.d/*\n" in text


@pytest.mark.parametrize(("values", "key"), [
    pytest.param({"email": "a@example.com\nadmin off"}, "email", id="email"),
    pytest.param({"admin": "off\nextra"}, "admin", id="admin"),
    pytest.param({"trusted_proxies": ["10.1.0.0/16\nrespond 200"]}, "trusted_proxies", id="trusted proxy"),
    pytest.param({"sites": [{"name": "a.example.com\nb.example.com"}]}, "sites", id="site name"),
    pytest.param({"sites": [{"name": "a.example.com", "allow": ["10.1.0.0/16\nrespond 200"]}]}, "sites", id="allow entry"),
    pytest.param({"sites": [{"name": "a.example.com", "headers": {"X-A": "b\nrespond 200"}}]}, "sites", id="header value"),
])
def test_a_line_break_in_a_curated_value_is_refused(values, key):
    with pytest.raises(BastetError, match=key):
        build(values)


def test_a_site_becomes_one_self_contained_validated_file():
    resources, _ = build({"sites": [{"name": "git.example.com", "upstream": "127.0.0.1:3000"}]})
    site = files(resources)[f"{CONF_D}/git.example.com.caddy"]
    assert site.content == ("# Managed by Bastet (the caddy role); changes made here are overwritten.\n"
                            "git.example.com {\n\treverse_proxy 127.0.0.1:3000\n}\n")
    assert "import" not in site.content
    assert site.validate == "caddy validate --adapter caddyfile --config %s"


def test_two_sites_make_two_files_and_every_knob_is_written():
    full = {"name": "Vault.example.com", "upstream": ["10.1.0.7:8222", "10.1.0.8:8222"], "tls_skip_verify": True,
            "allow": ["10.1.0.0/16", "203.0.113.7"], "headers": {"X-Real-IP": "{remote_host}"}, "encode": True, "extra": "log\n"}
    resources, _ = build({"sites": [{"name": "git.example.com", "upstream": "127.0.0.1:3000"}, full]})
    assert sorted(p for p in files(resources) if p.startswith(CONF_D)) == [f"{CONF_D}/git.example.com.caddy", f"{CONF_D}/vault.example.com.caddy"]
    assert files(resources)[f"{CONF_D}/vault.example.com.caddy"].content == (
        "# Managed by Bastet (the caddy role); changes made here are overwritten.\nVault.example.com {\n"
        "\t@denied not remote_ip 10.1.0.0/16 203.0.113.7\n\trespond @denied 403\n\tencode zstd gzip\n"
        "\treverse_proxy 10.1.0.7:8222 10.1.0.8:8222 {\n\t\ttransport http {\n\t\t\ttls_insecure_skip_verify\n\t\t}\n"
        "\t\theader_up \"X-Real-IP\" \"{remote_host}\"\n\t}\n\tlog\n}\n")


@pytest.mark.parametrize("knobs", [
    pytest.param({"tls_skip_verify": False, "encode": False, "allow": [], "headers": {}, "extra": ""}, id="falsy values"),
    pytest.param({}, id="unset"),
])
def test_unset_or_falsy_knobs_write_only_the_proxy_line(knobs):
    assert site_file({"name": "a.example.com", "upstream": "10.1.0.5:80", **knobs}).endswith("a.example.com {\n\treverse_proxy 10.1.0.5:80\n}\n")


def test_no_file_entry_uses_a_unit_reload_or_restart_and_all_carry_one_identical_trigger():
    resources, _ = build({"sites": [{"name": "a.example.com", "upstream": "10.1.0.5:80"}, {"name": "b.example.com", "upstream": "10.1.0.6:80"}]})
    written = [r for r in resources if isinstance(r, File)]
    assert len(written) == 3
    assert all(len(f.on_change) == 1 for f in written)
    assert len({f.on_change for f in written}) == 1
    assert not [t for f in written for t in f.on_change if t.command.startswith(("systemctl reload", "systemctl restart"))]
    assert all(r.on_change == () for r in resources if isinstance(r, Directory))


def test_the_reload_trigger_does_nothing_when_stopped_and_validates_before_it_reloads():
    [trigger] = files(build({})[0])[CADDYFILE].on_change
    active, validate, reload = trigger.command.strip().splitlines()
    assert active == "systemctl is-active --quiet caddy.service || exit 0"
    assert validate == ("runuser -u caddy -- env XDG_DATA_HOME=/var/lib XDG_CONFIG_HOME=/etc "
                        "caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile")
    assert reload == "systemctl reload caddy.service"


def test_the_standing_validation_reports_without_changing_anything():
    [standing] = [r for r in build({})[0] if isinstance(r, Command)]
    assert standing.unless == standing.run
    assert standing.run.endswith(VALIDATE) and "reload" not in standing.run


@pytest.mark.parametrize(("values", "level", "text"), [
    pytest.param({"sites": [{"name": "git.example.com/x", "upstream": "10.1.0.5:80"}]}, "error", "not a valid hostname", id="bad hostname"),
    pytest.param({"sites": [{"name": "http://git.example.com", "upstream": "10.1.0.5:80"}]}, "error", "not a valid hostname", id="scheme"),
    pytest.param({"snippets": {"bad name": "encode gzip"}}, "error", "snippets name", id="bad snippet name"),
])
def test_bad_names_stop_the_host(values, level, text):
    with pytest.raises(BastetError, match=text):
        build(values)


@pytest.mark.parametrize(("sites", "levels"), [
    pytest.param([{"name": "a.example.com", "upstream": "10.1.0.5:80"}], ["info"], id="stale files noted"),
    pytest.param([{"name": "a.example.com", "upstream": "10.1.0.5:80"}, {"name": "b.example.com", "extra": "respond 200"}], ["warning", "info"],
                 id="no upstream warns"),
    pytest.param([{"name": "*.example.com", "upstream": ["10.1.0.5:80"]}], ["info"], id="wildcard and list are fine"),
])
def test_site_checks(sites, levels):
    assert [n.level for n in build({"sites": sites})[1]] == levels


def test_nothing_in_the_checks_fires_without_sites():
    assert build({"email": "a@example.com"})[1] == []


def lab(tmp_path):
    root = tmp_path / "vault"
    files_ = {"Homelab.md": {"bastet": "lab", "domains": {"public": "example.com"}},
              "hosts/vps1.md": {"bastet": "host", "type": "vps", "ip": "10.1.0.5"},
              "hosts/nas1.md": {"bastet": "host", "type": "vps", "ip": "10.1.0.7"},
              "_roles/hosts/vps1/caddy.md": {"bastet": "role", "role": "caddy", "applies_to": "[[vps1]]", "serves": ["public"]},
              "_roles/hosts/nas1/app.md": {"bastet": "role", "role": "app", "applies_to": "[[nas1]]",
                                           "proxy": [{"subdomain": "media", "port": 8096, "encode": True}]}}
    for rel, data in files_.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("---\n" + yaml.safe_dump(data) + "---\n")
    return load_inventory(root, TYPES)


def test_a_site_exposed_by_another_host_ends_up_as_a_file(tmp_path):
    folder = tmp_path / "roles" / "app"
    folder.mkdir(parents=True)
    exposure = {"type": "object", "fields": {"subdomain": {"type": "string"}, "port": {"type": "int"}, "encode": {"type": "bool"}}}
    (folder / "app role.md").write_text("---\n" + yaml.safe_dump({
        "bastet": "role-definition", "name": "app", "version": "1.0.0", "api": 0, "description": "A demo app",
        "options": {"proxy": {"type": "list", "items": exposure}}}) + "---\nNotes.\n", encoding="utf-8")
    roles = {**ROLES, **load_roles(tmp_path / "roles")}
    inv = lab(tmp_path)
    host = inv.get("vps1")
    caddy = [a for a in resolve(inv, host, TYPES, roles) if a.role.name == "caddy"]
    info = HostInfo(name="vps1", type="vps", data={"os": "Arch Linux"}, root=Path("/x"), lab={}, collected=collect(inv, host, TYPES, roles))
    written = files([r for b in batches_for(caddy, info) for r in b.resources])
    assert written[f"{CONF_D}/media.example.com.caddy"].content.endswith("media.example.com {\n\tencode zstd gzip\n\treverse_proxy 10.1.0.7:8096\n}\n")


# -- site_defaults: a site's own value, else the Caddy's default, else nothing -----------------------------------------------

HEADER = "# Managed by Bastet (the caddy role); changes made here are overwritten.\n"
DEFAULTS = {"allow": ["10.1.0.0/16"], "tls_skip_verify": True, "encode": True, "headers": {"X-A": "1", "X-B": "2"}, "extra": "log"}


def with_defaults_site(site=None, defaults=None):
    return site_file({"name": "a.example.com", "upstream": "10.1.0.5:80", **(site or {})}, site_defaults=DEFAULTS if defaults is None else defaults)


def test_a_site_inherits_every_default_it_does_not_set():
    assert with_defaults_site() == (
        HEADER + "a.example.com {\n\t@denied not remote_ip 10.1.0.0/16\n\trespond @denied 403\n\tencode zstd gzip\n"
        "\treverse_proxy 10.1.0.5:80 {\n\t\ttransport http {\n\t\t\ttls_insecure_skip_verify\n\t\t}\n"
        "\t\theader_up \"X-A\" \"1\"\n\t\theader_up \"X-B\" \"2\"\n\t}\n\tlog\n}\n")


@pytest.mark.parametrize(("site", "present", "absent"), [
    pytest.param({"allow": []}, [], ["@denied", "10.1.0.0/16"], id="an empty allow list drops the restriction"),
    pytest.param({"allow": ["10.2.0.0/16"]}, ["remote_ip 10.2.0.0/16"], ["10.1.0.0/16"], id="a list replaces the default"),
    pytest.param({"encode": False}, [], ["encode"], id="false beats a true default"),
    pytest.param({"tls_skip_verify": False}, ["header_up"], ["tls_insecure_skip_verify"], id="false beats a true skip-verify"),
    pytest.param({"extra": ""}, ["\tlog\n"], [], id="an empty extra still gets the default's extra"),
])
def test_a_value_the_site_sets_wins_over_the_default(site, present, absent):
    text = with_defaults_site(site)
    assert all(p in text for p in present) and not any(a in text for a in absent)


def test_headers_merge_by_name_with_the_site_winning():
    text = with_defaults_site({"headers": {"X-B": "3", "X-C": "4"}})
    assert text.index('"X-A" "1"') < text.index('"X-B" "3"') < text.index('"X-C" "4"')
    assert '"X-B" "2"' not in text


def test_a_sites_extra_follows_the_defaults_extra():
    assert with_defaults_site({"extra": "debug"}).endswith("\tlog\n\tdebug\n}\n")


def test_unset_defaults_change_nothing():
    plain = site_file({"name": "a.example.com", "upstream": "10.1.0.5:80"})
    assert plain == with_defaults_site(defaults={}) and plain.endswith("a.example.com {\n\treverse_proxy 10.1.0.5:80\n}\n")


@pytest.mark.parametrize("defaults", [
    pytest.param({"allow": ["10.1.0.0/16\nrespond 200"]}, id="allow entry"),
    pytest.param({"headers": {"X-A": "b\nrespond 200"}}, id="header value"),
    pytest.param({"upstream": "10.1.0.5:80"}, id="a field that is not a knob"),
])
def test_site_defaults_are_checked_like_a_sites_own_values(defaults):
    with pytest.raises(BastetError, match="site_defaults"):
        build({"site_defaults": defaults})


def test_each_caddy_has_its_own_defaults_for_the_same_exposure(tmp_path):
    folder = tmp_path / "roles" / "app"
    folder.mkdir(parents=True)
    exposure = {"type": "object", "fields": {"subdomain": {"type": "string"}, "domain": {"type": "string"}, "port": {"type": "int"},
                                             "encode": {"type": "bool"}}}
    (folder / "app role.md").write_text("---\n" + yaml.safe_dump({
        "bastet": "role-definition", "name": "app", "version": "1.0.0", "api": 0, "description": "A demo app",
        "options": {"proxy": {"type": "list", "items": exposure}}}) + "---\nNotes.\n", encoding="utf-8")
    roles = {**ROLES, **load_roles(tmp_path / "roles")}
    root = tmp_path / "vault"
    notes = {"Homelab.md": {"bastet": "lab", "domains": {"public": "example.com", "internal": "example.com"}},
             "hosts/vps1.md": {"bastet": "host", "type": "vps", "ip": "10.1.0.5"},
             "hosts/lab1.md": {"bastet": "host", "type": "vps", "ip": "10.1.0.6"},
             "hosts/nas1.md": {"bastet": "host", "type": "vps", "ip": "10.1.0.7"},
             "_roles/hosts/vps1/caddy.md": {"bastet": "role", "role": "caddy", "applies_to": "[[vps1]]", "serves": ["public"],
                                            "site_defaults": {"allow": ["203.0.113.7"], "encode": False}},
             "_roles/hosts/lab1/caddy.md": {"bastet": "role", "role": "caddy", "applies_to": "[[lab1]]", "serves": ["internal"]},
             "_roles/hosts/nas1/app.md": {"bastet": "role", "role": "app", "applies_to": "[[nas1]]", "proxy": [
                 {"subdomain": "media", "domain": "public", "port": 8096, "encode": True},
                 {"subdomain": "media", "domain": "internal", "port": 8096}]}}
    for rel, data in notes.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("---\n" + yaml.safe_dump(data) + "---\n")
    inv = load_inventory(root, TYPES)

    def site(host):
        doc = inv.get(host)
        caddy = [a for a in resolve(inv, doc, TYPES, roles) if a.role.name == "caddy"]
        info = HostInfo(name=host, type="vps", data={"os": "Arch Linux"}, root=Path("/x"), lab={}, collected=collect(inv, doc, TYPES, roles))
        return files([r for b in batches_for(caddy, info) for r in b.resources])[f"{CONF_D}/media.example.com.caddy"].content

    public, internal = site("vps1"), site("lab1")
    assert "remote_ip 203.0.113.7" in public and "encode zstd gzip" in public  # the exposure's own encode beats the default's false
    assert "remote_ip" not in internal and "encode" not in internal
