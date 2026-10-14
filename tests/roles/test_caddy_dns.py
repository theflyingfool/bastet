"""The `dns` option of the caddy role: what is built when a DNS plugin is wanted, who can see the credentials, and the version guard."""

import subprocess
from pathlib import Path

import pytest
import yaml

from bastet.core.errors import BastetError
from bastet.engine.command import Command
from bastet.engine.files import Directory, File
from bastet.engine.packages import Package
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import check_values, load_roles, with_defaults
from bastet.roles.entries import run_checks
from bastet.roles.resolve import Applied

CADDY = load_roles()["caddy"]
ARCH = HostInfo(name="vps1", type="vps", data={"os": "Arch Linux"}, root=Path("/nonexistent"), lab={})
LIB = "/usr/local/lib/caddy-bastet"
LINODE = {"dns": {"provider": "linode"}, "dns_secrets": {"api_token": "tok-123"}}
DNS_PATHS = {"/etc/caddy/dns.caddy", "/etc/caddy/dns.env", LIB, f"{LIB}/build", "/etc/systemd/system/caddy-bastet-build.service",
             "/etc/systemd/system/caddy.service.d", "/etc/systemd/system/caddy.service.d/bastet-dns.conf", "/etc/pacman.d/hooks",
             "/etc/pacman.d/hooks/caddy-bastet.hook"}


def build(values, secret=()):
    applied = Applied(CADDY, with_defaults(CADDY, check_values(CADDY, values, "caddy")), origins={}, secret_options=frozenset(secret))
    batches = batches_for([applied], ARCH)
    return [r for b in batches for r in b.resources], [n for b in batches for n in b.notes]


def files(resources):
    return {r.path: r for r in resources if isinstance(r, (File, Directory))}


def text(path, values, secret=()):
    return files(build(values, secret)[0])[path].content


def messages(values, level):
    from bastet.roles import expr

    ctx = expr.context(CADDY.options, with_defaults(CADDY, check_values(CADDY, values, "caddy")), ARCH, {})
    return [n.message for n in run_checks(CADDY, ctx) if n.level == level]


def test_without_dns_none_of_it_exists():
    resources, _ = build({"sites": [{"name": "a.example.com", "upstream": "10.1.0.5:80"}]})
    assert not DNS_PATHS & set(files(resources))
    assert [r.name for r in resources if isinstance(r, Package)] == ["caddy"]
    assert [r.name for r in resources if isinstance(r, Command)] == ["caddy config is valid"]
    assert "dns" not in text("/etc/caddy/Caddyfile", {}) and "caddy-bastet" not in text("/etc/caddy/conf.d/a.example.com.caddy", {
        "sites": [{"name": "a.example.com", "upstream": "10.1.0.5:80"}]})


def test_dns_builds_exactly_the_listed_pieces():
    resources, notes = build(LINODE)
    assert DNS_PATHS <= set(files(resources))
    assert sorted(r.name for r in resources if isinstance(r, Package)) == ["caddy", "go"]
    commands = [r for r in resources if isinstance(r, Command)]
    assert [c.name for c in commands] == ["build caddy with the dns plugin", "caddy config is valid (with the dns plugin)"]
    build_cmd = commands[0]
    assert (build_cmd.run, build_cmd.unless, build_cmd.run_before) == (f"{LIB}/build rebuild", f"{LIB}/build current", "systemd")
    assert not [n for n in notes if n.level in ("error", "warning")]


def test_only_the_files_that_hold_or_name_a_secret_are_hidden():
    resources, _ = build({**LINODE, "sites": [{"name": "a.example.com", "upstream": "10.1.0.5:80"}]}, secret=["dns_secrets"])
    hidden = {r.path for r in resources if isinstance(r, File) and r.secret}
    assert hidden == {"/etc/caddy/dns.caddy", "/etc/caddy/dns.env"}
    assert files(resources)["/etc/caddy/dns.env"].mode == "0600"


def test_the_env_file_holds_the_values_and_nothing_else_does():
    values = {"dns": {"provider": "namecheap", "settings": {"user": "example-user"}},
              "dns_secrets": {"api_key": 'a"b\\c', "extra_token": "t2"}}
    resources, _ = build({**values, "sites": [{"name": "a.example.com", "upstream": "10.1.0.5:80"}]})
    env = files(resources)["/etc/caddy/dns.env"].content
    assert env == ('# Managed by Bastet (the caddy role); changes made here are overwritten.\n'
                   'DNS_API_KEY="a\\"b\\\\c"\nDNS_EXTRA_TOKEN="t2"\n')
    others = "".join(r.content for r in resources if isinstance(r, File) and r.path != "/etc/caddy/dns.env")
    assert "a\"b" not in others and "t2" not in others and "DNS_API_KEY=" not in others and "{env.DNS_API_KEY}" in others


@pytest.mark.parametrize(("values", "expected"), [
    pytest.param(LINODE, "acme_dns linode {\n\tapi_token {env.DNS_API_TOKEN}\n}\n", id="linode"),
    pytest.param({"dns": {"provider": "cloudflare"}, "dns_secrets": {"api_token": "x"}},
                 "acme_dns cloudflare {\n\tapi_token {env.DNS_API_TOKEN}\n}\n", id="cloudflare"),
    pytest.param({"dns": {"provider": "namecheap", "settings": {"user": "example-user", "api_endpoint": "https://example.test/xml"}},
                  "dns_secrets": {"api_key": "x"}},
                 "acme_dns namecheap {\n\tapi_key {env.DNS_API_KEY}\n\tuser example-user\n\tapi_endpoint https://example.test/xml\n}\n",
                 id="namecheap with plain fields"),
    pytest.param({"dns": {"provider": "linode"}}, "acme_dns linode\n", id="no fields at all"),
])
def test_the_provider_block(values, expected):
    body = text("/etc/caddy/dns.caddy", values)
    assert body == "# Managed by Bastet (the caddy role); changes made here are overwritten.\n" + expected


def test_the_caddyfile_only_imports_the_provider_block_when_dns_is_set():
    assert "dns.caddy" not in text("/etc/caddy/Caddyfile", {})
    with_dns = text("/etc/caddy/Caddyfile", LINODE)
    assert "\n\timport /etc/caddy/dns.caddy\n}" in with_dns and "tok-123" not in with_dns and "acme_dns" not in with_dns


def test_the_build_unit_never_sees_the_credentials_and_the_drop_in_points_at_the_new_binary():
    resources, _ = build(LINODE)
    unit = files(resources)["/etc/systemd/system/caddy-bastet-build.service"]
    assert "DynamicUser=yes" in unit.content and "ExecStartPost=+" in unit.content and "GOTOOLCHAIN=local" in unit.content
    assert "EnvironmentFile" not in unit.content and "dns.env" not in unit.content and "tok-123" not in unit.content
    assert "CacheDirectory=caddy-bastet" in unit.content and "RuntimeDirectory=caddy-bastet" in unit.content
    assert any("daemon-reload" in t.command for t in unit.on_change)
    drop_in = files(resources)["/etc/systemd/system/caddy.service.d/bastet-dns.conf"].content
    for name in ("ExecStartPre", "ExecStart", "ExecReload"):
        assert f"\n{name}=\n{name}=/usr/local/bin/caddy-bastet " in drop_in
    assert "EnvironmentFile=-/etc/caddy/dns.env" in drop_in


def test_a_changed_drop_in_or_env_file_restarts_caddy_only_after_validating_with_the_new_binary():
    resources, _ = build(LINODE)
    for path in ("/etc/systemd/system/caddy.service.d/bastet-dns.conf", "/etc/caddy/dns.env"):
        [restart] = [t for t in files(resources)[path].on_change if "restart" in t.command]
        lines = restart.command.strip().splitlines()
        assert lines[0].startswith("systemctl is-active --quiet caddy.service")
        assert "/usr/local/bin/caddy-bastet validate" in lines[1] and lines[2] == "systemctl try-restart caddy.service"
    assert not [t for t in files(resources)["/etc/caddy/Caddyfile"].on_change if "restart" in t.command]


def test_the_pacman_hook_rebuilds_after_caddy_or_go_change_without_blocking_pacman():
    hook = text("/etc/pacman.d/hooks/caddy-bastet.hook", LINODE)
    assert "Target = caddy\nTarget = go\n" in hook and "When = PostTransaction" in hook
    assert "Exec = /usr/bin/systemctl start --no-block caddy-bastet-build.service" in hook


def test_validators_use_the_plugin_binary_once_dns_is_set():
    site = {"sites": [{"name": "a.example.com", "upstream": "10.1.0.5:80"}]}
    plain = files(build(site)[0])["/etc/caddy/conf.d/a.example.com.caddy"]
    with_dns = files(build({**LINODE, **site})[0])["/etc/caddy/conf.d/a.example.com.caddy"]
    assert plain.validate == "caddy validate --adapter caddyfile --config %s"
    assert with_dns.validate == ("if [ -x /usr/local/bin/caddy-bastet ]; then /usr/local/bin/caddy-bastet validate "
                                 "--adapter caddyfile --config %s; fi")
    reload_ = with_dns.on_change[0].command
    assert "/usr/local/bin/caddy-bastet validate --adapter caddyfile --config /etc/caddy/Caddyfile" in reload_
    assert " caddy validate" in plain.on_change[0].command
    assert len({f.on_change for f in files(build({**LINODE, **site})[0]).values() if isinstance(f, File) and "/conf.d/" in f.path
                or f.path == "/etc/caddy/Caddyfile"}) == 1


@pytest.mark.parametrize(("dns", "lines"), [
    pytest.param({}, "", id="none set"),
    pytest.param({"propagation_delay": "2m", "ttl": "30s", "resolvers": ["1.1.1.1", "9.9.9.9"]},
                 "\ttls {\n\t\tpropagation_delay 2m\n\t\tdns_ttl 30s\n\t\tresolvers 1.1.1.1 9.9.9.9\n\t}\n", id="delay, ttl and resolvers"),
    pytest.param({"propagation_timeout": "-1"}, "\ttls {\n\t\tpropagation_timeout -1\n\t}\n", id="timeout only"),
    pytest.param({"resolvers": []}, "", id="an empty resolver list writes nothing"),
])
def test_the_generic_challenge_keys_go_in_each_sites_tls_block(dns, lines):
    site = {"sites": [{"name": "a.example.com", "upstream": "10.1.0.5:80"}]}
    body = text("/etc/caddy/conf.d/a.example.com.caddy", {"dns": {"provider": "linode", **dns}, **site})
    assert body.endswith("\treverse_proxy 10.1.0.5:80\n" + lines + "}\n")


def test_the_build_script_is_valid_shell_and_bakes_in_the_provider(tmp_path):
    script = text(f"{LIB}/build", {"dns": {"provider": "cloudflare", "version": "v0.2.1"}})
    path = tmp_path / "build"
    path.write_text(script)
    assert subprocess.run(["sh", "-n", str(path)]).returncode == 0
    assert "MODULE=github.com/caddy-dns/cloudflare\nID=dns.providers.cloudflare\nPIN='v0.2.1'\n" in script
    assert "PIN=''\n" in text(f"{LIB}/build", LINODE)


def test_the_plugin_binary_is_never_run_as_root():
    script = text(f"{LIB}/build", LINODE)
    for call in ('"$BIN" version', '"$BIN" list-modules', '"$new" validate'):
        assert call in script and call not in script.replace(f"as_caddy {call}", "").replace(f"as_caddy env XDG_DATA_HOME=/var/lib "
                                                                                                 f"XDG_CONFIG_HOME=/etc {call}", "")


STUB_GO = """printf '{\\n\\t"Path": "m",\\n\\t"Version": "%s",\\n\\t"Query": "latest"\\n}\\n' 'LATEST'"""


@pytest.mark.parametrize(("case", "want"), [
    pytest.param({}, 0, id="same Caddy and the newest plugin"),
    pytest.param({"built": "v2.11.6 h1:old"}, 1, id="the packaged Caddy moved on"),
    pytest.param({"plugin": "v0.7.0"}, 1, id="a newer plugin release exists"),
    pytest.param({"plugin": "v0.7.0", "version": "v0.7.0", "latest": "v0.8.0"}, 0, id="pinned: a newer release does not matter"),
    pytest.param({"plugin": "v0.8.0", "version": "v0.7.0"}, 1, id="pinned to another release than the one built"),
    pytest.param({"missing": True}, 1, id="nothing built yet"),
    pytest.param({"latest": ""}, 0, id="the module proxy cannot be reached: keep what is built"),
    pytest.param({"latest": "", "plugin": ""}, 1, id="the proxy cannot be reached and the plugin is not in the binary"),
])
def test_the_version_guard(tmp_path, case, want):
    version = case.get("version")
    values = {"dns": {"provider": "linode", **({"version": version} if version else {})}}
    path, bin_, stubs = tmp_path / "build", tmp_path / "caddy-bastet", tmp_path / "stubs"
    stubs.mkdir()
    path.write_text(text(f"{LIB}/build", values).replace("BIN=/usr/local/bin/caddy-bastet", f"BIN={bin_}"))

    def stub(file, body):
        file.write_text("#!/bin/sh\n" + body + "\n")
        file.chmod(0o755)

    stub(stubs / "caddy", 'echo "v2.11.7 h1:packaged"')
    stub(stubs / "runuser", 'shift 3; exec "$@"')  # runuser -u caddy -- command ...: here just the command
    stub(stubs / "go", STUB_GO.replace("LATEST", case.get("latest", "v0.8.0")))
    if not case.get("missing"):
        stub(bin_, f'case "$1" in version) echo "{case.get("built", "v2.11.7 h1:custom")}";; '
                   f'list-modules) echo "dns.providers.linode {case.get("plugin", "v0.8.0")}";; esac')
    result = subprocess.run(["sh", str(path), "current"], env={"PATH": f"{stubs}:/usr/bin:/bin"}, capture_output=True, text=True)
    assert result.returncode == want, result.stderr


@pytest.mark.parametrize(("values", "fragment"), [
    pytest.param({"dns": {"provider": "Lin ode"}}, "caddy-dns module name", id="a provider name with a space"),
    pytest.param({"dns": {"provider": "linode", "settings": {"API Key": "x"}}}, "other than lower-case", id="a bad settings name"),
    pytest.param({"dns": {"provider": "linode"}, "dns_secrets": {"Api-Token": "x"}}, "other than lower-case", id="a bad secret name"),
    pytest.param({"dns_secrets": {"api_token": "x"}}, "dns is not", id="secrets without dns"),
    pytest.param({"dns": {"provider": "linode", "version": "v0.8 0; rm -rf /"}}, "release tag", id="a version with shell characters"),
    pytest.param({"dns": {"provider": "linode"}, "dns_secrets": {"api_token": "a\nb"}}, "single non-empty line", id="a secret with a line break (the contract's single_line)"),
])
def test_dns_mistakes_stop_the_host(values, fragment):
    with pytest.raises(BastetError, match=fragment):
        messages(values, "error")


@pytest.mark.parametrize(("values", "level", "fragment"), [
    pytest.param({"dns": {"provider": "porkbun"}, "dns_secrets": {"api_key": "x"}}, "info", "not documented", id="another provider"),
    pytest.param({"dns": {"provider": "linode"}}, "warning", "needs a secret field", id="linode without its token"),
    pytest.param({"dns": {"provider": "namecheap"}, "dns_secrets": {"api_token": "x"}}, "warning", "needs a secret field",
                 id="namecheap needs api_key, not api_token"),
])
def test_dns_notes(values, level, fragment):
    assert any(fragment in m for m in messages(values, level))


def test_a_complete_documented_setup_raises_no_check():
    for values in (LINODE, {"dns": {"provider": "cloudflare"}, "dns_secrets": {"api_token": "x"}},
                   {"dns": {"provider": "namecheap", "settings": {"user": "u"}}, "dns_secrets": {"api_key": "x"}}):
        assert not [m for level in ("error", "warning", "info") for m in messages(values, level) if "dns" in m.lower()]


@pytest.mark.parametrize("provider", ["linode", "cloudflare", "namecheap"])
def test_each_documented_provider_has_a_working_example(provider):
    [example] = [e for e in CADDY.examples if yaml.safe_load(e["yaml"]).get("dns", {}).get("provider") == provider]
    values = yaml.safe_load(example["yaml"])
    assert all(v.startswith("secret:") for v in values["dns_secrets"].values())
    values["dns_secrets"] = {k: "dummy" for k in values["dns_secrets"]}
    block = text("/etc/caddy/dns.caddy", values)
    assert block.splitlines()[1].startswith(f"acme_dns {provider}")
    assert not messages(values, "error") and not messages(values, "warning")
