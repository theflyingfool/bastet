# The `caddy` role, collectors and the DNS-challenge build

**Status:** draft for the owner's review (2026-10-14). Nothing is built. Decisions D-036 to D-038 in `docs/decisions.md` record what the owner chose in the design talk; this spec is the detail. The plan is `docs/plans/2026-10-14-bastet-caddy-role.md`.

**Goal.** A `caddy` role for the VPS now and the home lab later: Caddy builds its sites from what other roles and hosts expose, with sensible defaults for the knobs, and can be built with a DNS-challenge plugin (the home lab needs DNS-01 for names that are not reachable from the internet; the owner is also changing the DNS provider of the domain).

**In scope:** the `caddy` role; a small contract feature so a role can collect what other hosts expose; the DNS build (`dns` option). **Out of scope:** the `wireguard`, `forgejo` and `vaultwarden` roles (each has its own spec/plan; `vaultwarden` is the first user of the collector), the spec's final-phase ordering and "pending" reporting, the DNS collector (records at a provider), a host firewall, the AUR.

## 1. What the owner decided (design talk, 2026-10-14)

1. Sites come from **collection by default**; a manual `sites:` list stays, because hosts Bastet does not configure (an appliance, a router UI) have no note to expose anything from (D-036).
2. Per-site knobs **inherit defaults** from the `caddy` role (`site_defaults`), so a group note can give the home-lab proxy different defaults from the VPS proxy (D-036).
3. Caddy does **not** expose every Caddyfile directive: a curated typed set, plus raw `extra:` text (the two tiers of the original design, section 9.1 of the design spec).
4. DNS challenge: **build the binary on the host with `xcaddy`**, keyed on the repo's `caddy` version, run in a sandboxed build unit, started by a pacman hook and by a guarded Bastet command, pointed at by a systemd drop-in. The plugin follows its latest release by default; a note can pin it (D-037).
5. The AUR stays out for now. The reason is not "never": validating build files that cannot all be read by hand is unsolved. A reviewed `PKGBUILD` kept in a role folder (pinned checksums, built by an unprivileged user, installed with `pacman -U`) is a possible later replacement for the `xcaddy` build; it needs a "local package" building block and its own spec (D-038).
6. The option is called `proxy` (the lab note's domain-to-proxy map is `proxies:` so the two names do not clash). There are **no lab-level site defaults** (a proxy host or group note carries `site_defaults`), but the **lab note lists every site**: the lab dashboard gets a Sites table built by the same collector (name, domain, proxy, upstream, where it comes from) (D-036).
7. `xcaddy` is not a package: the build unit runs `go install github.com/caddyserver/xcaddy/cmd/xcaddy@latest` into its cache and then builds with it. Only `go` comes from the repo (D-037).
8. Arch is rolling, so "latest" is the default for the plugin and the build relies on the `pacman -Syu` Arch installs already run, so `caddy` and `go` move together.

## 2. Collectors

### 2.1 What exists

- `resolve(inv, host, types, roles)` (`roles/resolve.py`) already receives the whole inventory, so another host's resolved options can be computed at planning time.
- `declarative.build(role, values, host, ...)` (`roles/declarative.py`) builds one host's entries from that host's `Applied` values and a `HostInfo`; `expr.context()` turns them into the names `when:` and `{{ }}` see (options, `host`, `lab`, `applied`). `cli/run.py` `plan_for()` has the inventory (`ctx.inventory`) and calls `resolve()` and then `batches_for()`.
- So **the seam is `plan_for` → `HostInfo` → `expr.context`**: `plan_for` can resolve the other hosts and hand the matching exposures to the build. Entries never see another host's `Applied` directly.

### 2.2 The `proxy` option

An app role that wants a proxy in front of it declares an option named **`proxy`** (type `object`; it is the same shape in every app role, so the proxy can read them all):

```yaml
proxy:
  subdomain: git          # the name under the domain: git.example.com
  domain: public          # public | internal, which proxy the lab file names for it
  port: 3000
  upstream: null          # optional: host:port; default is this host's address and `port`
  # optional site knobs (section 3), set here only for what only the app knows:
  tls_skip_verify: false
  allow: [10.1.0.0/16]
  headers: {}
  encode: true
  extra: ""
```

- `proxy` holds no secret field (the collector refuses one).
- The lab note names the proxy for each domain: `proxies: {public: "[[vps1/caddy]]", internal: "[[lab1/caddy]]"}`. A group or host note can override it (same rules as any lab value).
- Two exposures with the same name on the same domain are an error naming both files. An exposure whose domain has no proxy in the lab note is a `checks:` warning on the exposing host, not an error.

### 2.3 The `collects` contract key

The `caddy` role file carries `collects: {proxy: sites}`: "append every `proxy` that targets this host's `caddy` role to my list option `sites` before entries are built". Then a role writes one `each: sites` entry and sees manual and collected sites alike (a collected site also carries `host` (the exposing host's name) and `address`).

- Collection runs **at planning time over declared options**. It does not wait for the exposing host to be applied, so Caddy may point at an app that is not up yet (a 502 until it is). The spec's final phase, "pending" reporting and host-to-host waits stay deferred with the capabilities step (roadmap).
- The exposing host's address is a fact of the inventory (the plan's first task finds the field). A collected exposure without an address (an unmanaged or unaddressed host) and no `upstream:` is an error naming the file.
- Hosts that are unmanaged or not reached by the run are still scanned: the collector reads the whole inventory, like the spec says, not only the hosts in the run.
- The cost is one `resolve()` per other host for every host that collects. `plan_for` caches resolved hosts for the run.
- Secrets: `resolve_refs()` is not run for other hosts' values (collected fields are not secret, above).

### 2.4 Not decided here

How the contract grows `collects` for other kinds (DNS records from the same exposures: `collects: {proxy: records}` later), and ordering between collectors (DNS after the proxy). Recorded in the roadmap.

## 3. Sites and their defaults

A site (manual or collected) has: `name` (the full host name, or `subdomain` + `domain` for collected), `upstream` (one `host:port` or a list), and the knobs:

| Knob | Caddy | Notes |
|---|---|---|
| `tls_skip_verify` | `reverse_proxy` transport `tls_insecure_skip_verify` | for HTTPS backends with a self-signed certificate |
| `allow` | a `remote_ip` matcher; others get 403 | list of addresses/CIDRs; the vaultwarden rule (home WAN IP + tunnel subnet) |
| `headers` | `header_up` per entry | map name → value |
| `encode` | `encode zstd gzip` | bool |
| `extra` | raw text inside the site block | the escape hatch |

**Inheritance.** The role has `site_defaults` with the same knob names. A site's value is: its own, else `site_defaults`'s, else nothing is written (Caddy's own default applies, so unset still means leave alone). Resolved in the role's templating, not with a Caddy snippet: Caddy directives add up rather than override each other, so a snippet could not be overridden by a site. `false`, `0`, `""` and `[]` are values, so they override a default. Scalars and lists replace the default, `headers` merge by header name with the site winning, and `extra` is appended after the default's `extra`. Whether a site can drop an inherited value (an explicit `null`) is decided in the plan's templating task. The plan's first caddy task settles the exact syntax once it sees what the Jinja templating can express.

Because `site_defaults` is an ordinary role option, a group note gives the home-lab proxy its own (for example `allow` = the LAN and tunnel subnets) while the VPS note differs. There is no lab-level default.

**The lab lists every site.** The generated lab dashboard (`core/render.py`, `dashboard()`, embedded in the lab note) gets a **Sites** table from the same collector: site name, domain, proxy host, upstream and where the site comes from (the exposing host, or a manual `sites:` entry). It is regenerated like the rest of the dashboard, so the lab note always shows what is exposed where, and a name collision is visible there as well as an error on the run.

## 4. The `caddy` role

Role `caddy`, `os: [arch]` for now (the apt side is deferred, D-028).

| Option | Purpose | Default |
|---|---|---|
| `email` | ACME account email (global block) | unset |
| `admin` | admin endpoint (`off` or an address) | unset |
| `log_level` | global log level | unset |
| `trusted_proxies` | `servers { trusted_proxies static ... }` | unset |
| `snippets` | map name → raw text, written as `(name) { ... }` blocks others `import` | unset |
| `site_defaults` | section 3 | unset |
| `sites` | manual sites, plus the collected ones (section 2.3) | unset |
| `extra` | raw text appended to the global block | unset |
| `dns` | section 5 | unset |

With **no options** the role documents and does exactly this: install `caddy`, manage the main `/etc/caddy/Caddyfile` (an optional global block, then `import /etc/caddy/conf.d/*`), create `conf.d`, enable and start the unit, validate the Caddyfile (`caddy validate`) before the reload. The role owns the main Caddyfile outright; `conf.d` belongs to other roles. Each site becomes one file `/etc/caddy/conf.d/<name>.caddy`. Sites that disappear from the list leave their file behind (file removal is deferred; the role says so with an info check).

Triggers: a changed file reloads `caddy` (only a running unit is touched); a changed binary or unit restarts it.

## 5. The DNS-challenge build (`dns` option)

`dns: {provider: <name>, version: latest|<tag>, env: {VAR: value}}`; unset means none of this exists on the host. `provider` maps to the Go module `github.com/caddy-dns/<provider>`. `env` holds the provider's credentials (`secret: true`).

Pieces, all data over existing blocks:

1. **Packages:** `caddy` (always) and `go` (when `dns` is set) from the Arch repos; Go stays installed because every Caddy bump rebuilds. `xcaddy` is not installed as a package (below).
2. **Build unit** `caddy-bastet-build.service` (a `files:` entry with `daemon_reload`): `Type=oneshot`, `DynamicUser=yes` (no account on disk, nothing for `accounts:`), `CacheDirectory=caddy-bastet` as `GOCACHE`/`GOPATH` through `Environment=`, network allowed, a long `TimeoutStartSec`, an optional `MemoryMax` (a small VPS). `ExecStartPre` runs `go install github.com/caddyserver/xcaddy/cmd/xcaddy@latest` (into the cache directory, so `xcaddy` is always current and nothing is added to the system), then `ExecStart` runs `<cache>/bin/xcaddy build <caddy version> --with <module>[@<tag>] --output <cache>/new`. `ExecStartPost=+` (privileged) moves it atomically to `/usr/local/bin/caddy-bastet` and runs `systemctl try-restart caddy.service`. A failed build never reaches the move, so the previous binary keeps serving.
3. **Drop-in** `caddy.service.d/bastet-dns.conf`: clears `ExecStart=` and `ExecReload=` and points both at `caddy-bastet` (same arguments as the packaged unit, checked in the plan's first task), plus `EnvironmentFile=` for the credentials file (mode 0600, `secret: true`).
4. **Caddyfile:** a global `acme_dns <provider> {env.<VAR>}` line, only when `dns` is set. A site can still opt out with its own `tls`.
5. **Triggers to build:**
   - **pacman hook** `/etc/pacman.d/hooks/caddy-bastet.hook` (a `files:` entry): after Install/Upgrade of `caddy` or `go`, run `systemctl start --no-block caddy-bastet-build.service`. `--no-block` so pacman does not hold its database lock for the length of the build.
   - **a guarded command** in the Bastet run: `systemctl start caddy-bastet-build.service` unless `caddy-bastet version` equals `caddy version` and the module version from `caddy-bastet list-modules --versions` is the requested one (for `latest`, the newest tag from `git ls-remote --tags --refs`, read-only). This catches a new plugin release, a first install, a missed hook and a failed hook build. `systemctl start` on a oneshot blocks until it ends, so a build that still fails **fails the command and the run says so**, with the journal as the hint. That is the failure report; no separate "last result" check is needed.
   - The hook and the command start the same unit; systemd serialises them.
6. **Version rule:** `version: latest` (documented default when `dns` is set) follows the plugin's newest tag at rebuild time; a tag pins it. The run log records what was built.
7. **Turning `dns` off:** Go stays (removal is deferred) and the role gives an info check; the drop-in is blanked (`ExecStart` back to the packaged unit's line), not deleted.

Known limits, stated plainly in the role's body: unreviewed upstream plugin code is built whenever its newest tag changes (Go's checksum database verifies the content matches the tag, not that it is good), so a host can pin; a rebuild restarts Caddy briefly; the first build needs about 1 GB of memory on a small VPS.

## 6. Verification before the plan's code tasks (not yet checked)

These are facts I could not confirm from here; the first plan task checks each and the plan changes if one is wrong:

- the packaged `caddy.service` lines (`ExecStart`, `ExecReload`, `AmbientCapabilities`), for the drop-in and for "no `setcap` needed";
- that `go` is in the official repos (the owner says it is) and that `go install ...xcaddy@latest` works inside the sandboxed unit (`GOPATH`, `GOCACHE`, `GOBIN` under the cache directory, no `HOME`, network allowed);
- that `caddy list-modules --versions` shows the plugin version;
- what the sandboxed Jinja templating allows for the site defaults (loops, `is not none`), which fixes the syntax in section 3;
- the exposing host's address field in the inventory;
- whether a trigger on a `files` entry can run `systemctl try-restart` for a *different* unit than the one restarted by `ExecStartPost` (probably not needed; `ExecStartPost` does it).

## 7. Deferred (roadmap rows)

`wireguard` role (peers as `each:`, the server key a secret; the laptop and phone key and config question is open); update visibility for software outside the package manager (the "newest plugin tag" as an info line in `check`, if the report can carry it); the collector's final phase, pending and waiting; a DNS collector; the local-package block (reviewed `PKGBUILD`) as a possible replacement for the `xcaddy` build; file removal for stale site files; apt support.
