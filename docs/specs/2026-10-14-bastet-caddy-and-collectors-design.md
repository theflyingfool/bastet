# The `caddy` role, collectors and the DNS-challenge build

**Status:** revision 2, draft for the owner's review (2026-10-14). Nothing is built. Decisions D-036 to D-038 in `docs/decisions.md` record what the owner chose; this spec is the detail. The plan is `docs/plans/2026-10-14-bastet-caddy-role.md`. Revision 2 follows an independent review: validation of generated files (4.2), routing by `serves` instead of a lab map (2.3), duplicate detection (2.4), `go list -m` for "latest" (5.4), the `dns` option shape and provider documentation (5.1, 5.2).

**Goal.** A `caddy` role for the VPS now and the home lab later: Caddy builds its sites from what other roles and hosts expose, with sensible defaults for the knobs, and can be built with a DNS-challenge plugin. The home lab needs DNS-01 because the same names resolve to the VPS from outside and to the lab inside (split-horizon), so the lab's Caddy cannot pass HTTP-01 for them. The owner is also changing the DNS provider of the domain; Linode is the one that matters now, Cloudflare and Namecheap are documented too.

**In scope:** the `caddy` role; a small contract feature so a role can collect what other hosts expose; the DNS build (`dns` option) and provider documentation; a Sites table in the lab dashboard. **Out of scope:** the `wireguard`, `forgejo` and `vaultwarden` roles (each has its own spec/plan; `vaultwarden` is the first user of the collector), the original spec's final-phase ordering and "pending" reporting, the DNS collector (records at a provider), a host firewall, the AUR.

## 1. What the owner decided (design talk, 2026-10-14)

1. Sites come from **collection by default**; a manual `sites:` list stays, because hosts Bastet does not configure (an appliance, a router UI) have no note to expose anything from (D-036).
2. Per-site knobs **inherit defaults** from the `caddy` role (`site_defaults`), so a group note can give the home-lab proxy different defaults from the VPS proxy. There are **no lab-level defaults**. The **lab note lists every site** (a Sites table in the lab dashboard) (D-036).
3. Caddy does **not** expose every Caddyfile directive: a curated typed set, plus raw `extra:` text (the two tiers of the original design, section 9.1 of the design spec).
4. DNS challenge: **build the binary on the host with `xcaddy`**, keyed on the repo's `caddy` version, run in a sandboxed build unit, started by a pacman hook and by a guarded Bastet command, pointed at by a systemd drop-in. The plugin follows its latest release by default; a note can pin it. `xcaddy` is not a package: the unit runs `go install ...xcaddy@latest` itself; only `go` comes from the repo (D-037).
5. The AUR stays out for now. The reason is not "never": validating build files that cannot all be read by hand is unsolved. A reviewed `PKGBUILD` kept in a role folder (pinned checksums, built by an unprivileged user, installed with `pacman -U`) is a possible later replacement for the `xcaddy` build; it needs a "local package" building block and its own spec (D-038).
6. The per-app option is called `proxy`. Arch is rolling, so "latest" is the default for the plugin, and the build relies on the `pacman -Syu` Arch installs already run, so `caddy` and `go` move together.
7. **Split-horizon names (owner, 2026-10-14):** internal and external services use the same names, with no prefix per scope. A scope says *who answers*, not what the name is.
8. **Routing by `serves`:** which Caddy receives an exposure is decided by an option on the Caddy role, not a lab map (section 2.3). `via` pins a specific Caddy.
9. **`subdomain: vault` just works:** the name is `subdomain` + the scope's domain from the lab note's `domains:`; the scope is optional when the lab has one domain (section 2.2).
10. **DNS providers are documented in the role,** Linode first, with Cloudflare and Namecheap (section 5.1).

## 2. Collectors

### 2.1 What exists

- `resolve(inv, host, types, roles)` (`roles/resolve.py`) already receives the whole inventory, so another host's resolved options can be computed at planning time.
- `declarative.build(role, values, host, ...)` (`roles/declarative.py`) builds one host's entries from that host's `Applied` values and a `HostInfo`; `expr.context()` turns them into the names `when:` and `{{ }}` see (options, `host`, `lab`, `applied`). `cli/run.py` `plan_for()` has the inventory (`ctx.inventory`) and calls `resolve()` and then `batches_for()`.
- The lab note already has `domains:` (scope → domain, read by the dashboard in `core/render.py`). Lab keys are a fact (`lab.*`), **not** role options, so they have no per-group ranking: group and host overrides exist only for role options.
- So **the seam is `plan_for` → `HostInfo` → `expr.context`**: `plan_for` can resolve the other hosts and hand the matching exposures to the build. Entries never see another host's `Applied` directly.

### 2.2 The `proxy` option (on app roles)

An app role that wants a proxy in front of it declares an option named **`proxy`**: a **list of exposures** (the same shape in every app role, so the proxy can read them all). One exposure:

```yaml
proxy:
  - subdomain: vault        # the name before the scope's domain: vault.example.com
    domain: public          # the scope (a key of the lab note's `domains:`); optional, see below
    port: 8222
    via: null               # optional link(s) to a specific caddy role: "[[vps1/caddy]]"
    upstream: null          # optional host:port; default below
    # optional site knobs (section 3), only for what only the app knows:
    allow: [203.0.113.7, 10.8.0.0/24]
    tls_skip_verify: false
    headers: {}
    encode: true
    extra: ""
```

- **The name.** `subdomain` + `.` + `lab.domains[<scope>]`. With `domains: {public: example.com}` in the lab note, `subdomain: vault` is `vault.example.com`. A multi-label `subdomain` (`vault.apps`) works.
- **The scope is optional when the lab's `domains:` has exactly one entry** (that one is used). With two or more it is required, and leaving it out is an error listing the scopes. A scope that is not in `domains:` is an error naming the exposing note and listing the available scopes.
- **Same name in every scope (split-horizon).** `domains:` may map several scopes to the same domain: `{public: example.com, internal: example.com}`. An exposure with `domain: internal` is then `vault.example.com` too. An app exposed to both writes two entries, and each Caddy that serves one of those scopes builds the same hostname.
- **Default upstream:** the exposing host's address (its `ip`, or its `address` when `ip` is `dhcp`/unset) and `port`; when the Caddy that receives it is on the *same* host, `127.0.0.1:port`. An exposure without an address (an unmanaged or unaddressed host) and no `upstream:` is an error naming the file.
- `proxy` holds no secret field (the collector refuses one).

### 2.3 Which Caddy receives an exposure

The `caddy` role has an option **`serves`**: the list of lab scopes this Caddy answers for (`serves: [public]` in the VPS's note, `[internal]` in the lab's). It is an ordinary role option, so a group note sets it for a group of proxies and a host note overrides it.

An exposure goes to the Caddy roles for which:

1. its `via` names that Caddy's role note, **or**
2. it has no `via` and its scope is in that Caddy's `serves`.

| Case | Result |
|---|---|
| Exactly one Caddy matches | That Caddy builds the site. |
| No Caddy matches | A warning on the exposing host (the check names the scope and says nothing is generated); not an error. |
| Two or more Caddies serve the scope and the exposure has no `via` | **Error** naming the exposing note and both Caddies: add `via:` to say which (or both), or fix `serves`. |
| `via` lists several Caddies | Each builds the site (the intended "through more than one proxy" case, written explicitly). |
| `via` names something that is not a `caddy` role | Error naming the file. |
| `serves` names a scope not in `domains:` | Error naming the Caddy's note. |

A Caddy that serves no scope and receives no `via` collects nothing: `sites:` only. A Caddy with `serves` unset is not an error.

**Walk-through** (placeholder data). Lab note: `domains: {public: example.com, internal: example.com}`.

| Host | Roles | Notes |
|---|---|---|
| `vps1` | `caddy` (`serves: [public]`), `forgejo`, `vaultwarden` | the public proxy |
| `lab1` | `caddy` (`serves: [internal]`) | the lab proxy; also `sites:` for the router |
| `nas1` | `jellyfin` | |
| `router` | unmanaged | a manual `sites:` entry on `lab1`: `router.example.com` → `10.1.0.1:443`, `tls_skip_verify: true` |

- `forgejo` on `vps1`: `proxy: [{subdomain: git, domain: public, port: 3000}]` → `vps1`'s Caddy builds `git.example.com` → `127.0.0.1:3000` (same host).
- `vaultwarden` on `vps1`: `proxy: [{subdomain: vault, domain: public, port: 8222, allow: [home WAN IP, tunnel subnet]}, {subdomain: vault, domain: internal, port: 8222, upstream: 10.8.0.1:8222}]` → `vps1` builds `vault.example.com` with the allow list; `lab1` builds the same name pointing at the tunnel address (the collector does not know network reachability, so the app states the upstream the lab can reach).
- `jellyfin` on `nas1`: `proxy: [{subdomain: media, domain: internal, port: 8096}]` → `lab1` builds `media.example.com` → `nas1`'s address.
- A new second public proxy `vps2` with `serves: [public]` makes `forgejo`'s and `vaultwarden`'s `public` entries ambiguous → an error on the next plan naming them, until each says `via:`.

DNS (the split-horizon records: public to the VPS, internal to `lab1`) is the later DNS collector's job, not this role's.

### 2.4 The `collects` contract key and duplicates

The `caddy` role file carries `collects: {proxy: sites}`: "append every exposure routed to this host's `caddy` role (section 2.3) to my list option `sites` before entries are built". A role then writes one `each: sites` entry and sees manual and collected sites alike (a collected site also carries `host`, the exposing host's name, and `source`).

- Collection runs **at planning time over declared options**. It does not wait for the exposing host to be applied, so Caddy may point at an app that is not up yet (a 502 until it is). The original spec's final phase, "pending" reporting and host-to-host waits stay deferred with the capabilities step.
- Hosts that are unmanaged or not reached by the run are still scanned: the collector reads the whole inventory, not only the hosts in the run.
- One `resolve()` per other host for every host that collects; `plan_for` caches resolved hosts for the run.
- Secrets: `resolve_refs()` is not run for other hosts' values.
- **Duplicates.** The key is the **resolved hostname** (lowercased, no trailing dot), **per Caddy host**, across collected and manual sites. Two sources for one hostname on one Caddy is an error naming both sources (the exposing notes, or a note and its manual entry). There is no precedence: nothing silently wins. The same hostname on two *different* Caddies is not a duplicate (it is the split-horizon case). Wildcard overlap (`*.example.com` and `git.example.com`) is legal in Caddy and is not flagged. The site's file name derives from the hostname, so the engine's existing "two items build the same file" refusal is a second net; Caddy's own validation is a third.

Not decided here: how `collects` grows for other kinds (DNS records from the same exposures) and ordering between collectors. Recorded in the roadmap.

## 3. Sites and their defaults

A site (manual or collected) has a hostname (`name` for a manual one; `subdomain` + scope for a collected one), `upstream` (one `host:port` or a list), and the knobs:

| Knob | Caddy | Notes |
|---|---|---|
| `tls_skip_verify` | `reverse_proxy` transport `tls_insecure_skip_verify` | for HTTPS backends with a self-signed certificate |
| `allow` | a `remote_ip` matcher; others get 403 | list of addresses/CIDRs; the vaultwarden rule (home WAN IP + tunnel subnet) |
| `headers` | `header_up` per entry | map name → value |
| `encode` | `encode zstd gzip` | bool |
| `extra` | raw text inside the site block | the escape hatch |

**Inheritance.** The role has `site_defaults` with the same knob names. A site's value is: its own, else `site_defaults`'s, else nothing is written (Caddy's own default applies, so unset still means leave alone). It is resolved in the role's templating, not with a Caddy snippet: Caddy directives add up rather than override each other, so a snippet could not be overridden by a site. `false`, `0`, `""` and `[]` are values, so they override a default. Scalars and lists replace the default, `headers` merge by header name with the site winning, and `extra` is appended after the default's `extra`. Whether a site can drop an inherited value (an explicit `null`) is decided in the plan's templating task, which also fixes the exact syntax once it sees what the Jinja templating can express.

`site_defaults` is an ordinary role option, so a group note gives the home-lab proxy its own (for example `allow` = the LAN and tunnel subnets) while the VPS note differs.

**The lab lists every site.** The generated lab dashboard (`core/render.py`, `dashboard()`, embedded in the lab note) gets a **Sites** table from the same collector: hostname, scope, proxy host, upstream, and where the site comes from (the exposing host, or a manual `sites:` entry). It is regenerated like the rest of the dashboard, so the lab note always shows what is exposed where; a name collision is visible there as well as an error on the run.

## 4. The `caddy` role

Role `caddy`, `os: [arch]` for now (the apt side is deferred, D-028).

### 4.1 Options

| Option | Purpose | Default |
|---|---|---|
| `serves` | the lab scopes this Caddy answers for (section 2.3) | unset |
| `sites` | manual sites, plus the collected ones | unset |
| `site_defaults` | section 3 | unset |
| `email` | ACME account email (global block) | unset |
| `admin` | admin endpoint (`off` or an address) | unset |
| `log_level` | global log level | unset |
| `trusted_proxies` | `servers { trusted_proxies static ... }` | unset |
| `snippets` | map name → raw text, written as `(name) { ... }` blocks for hand-written config to `import` | unset |
| `extra` | raw text appended to the global block | unset |
| `dns` | section 5 | unset |

With **no options** the role documents and does exactly this: install `caddy`, manage the main `/etc/caddy/Caddyfile` (a global block that keeps the package's `admin "unix//run/caddy/admin.socket"` unless `admin` is set, so the admin API never falls back to TCP port 2019; no welcome-page `http://` site; then `import /etc/caddy/conf.d/*`, as the package's own file does), create `conf.d`, enable and start the unit, and validate before every reload (4.2). The role owns the main Caddyfile outright; `conf.d` also holds other roles' files. Each site becomes one file `/etc/caddy/conf.d/<hostname>.caddy`. Sites that disappear from the list leave their file behind (file removal is deferred; the role says so with an info check). Triggers: **Bastet never reloads or restarts Caddy without validating first** (4.2). A changed Caddyfile or site file runs one gated reload; a changed unit or drop-in runs one gated restart. Both are `on_change:` shell commands, not `reload:`/`restart:` unit triggers, and neither touches a unit that is not running.

### 4.2 Validation

A site file is a fragment, not a whole Caddyfile, and the files block's `validate:` runs a command on **one file's** temporary copy (`engine/files.py`) before it is swapped in. So:

1. **Generated site files are self-contained** (no `import`): Bastet resolves `site_defaults` itself, so a generated file needs nothing from the main Caddyfile. Each is validated alone with `validate: caddy validate --adapter caddyfile --config %s`, so a bad file never lands on disk. (Snippets exist for hand-written files; those are their owner's to validate.)
2. **The reload is gated on the whole config.** The engine runs triggers after all fixes, once per host, de-duplicated, for changed items only, and a failed trigger fails the run and stops the later triggers (`engine/run.py`). So the role does not use the `reload:` unit trigger; every file entry that should reload Caddy carries the same `on_change:` command, which the engine runs once:
   ```sh
   systemctl is-active --quiet caddy.service || exit 0
   runuser -u caddy -- env XDG_DATA_HOME=/var/lib XDG_CONFIG_HOME=/etc <validator> validate --adapter caddyfile --config /etc/caddy/Caddyfile
   systemctl reload caddy.service
   ```
   The engine runs a trigger as a script under `sh -e` as root, so a failing validation stops the script before the reload and the trigger exits non-zero. Triggers are de-duplicated by value (label and command), so every entry must carry the **same** `name:` and `run:` text for it to run once. Here `<validator>` is `caddy`, or `caddy-bastet` when `dns` is set (with the DNS env file loaded for the check, if validation needs it, 6). If validation fails, the reload is never attempted, the trigger fails, and the run reports it with Caddy's own error. The restart for a changed unit or drop-in is gated the same way (the same three lines, ending in `systemctl try-restart caddy.service`), because a restart with a bad config is an outage, not a rejected reload.
3. **A standing check** (`commands:`, read-only) runs the same whole-config validation on every run, so a config that is invalid on disk (a run that failed before, or a hand edit) is reported each time, not only when a file changes. Whether a read-only command can be written so it does not count as a change is verified in Task 1.
4. Whether `caddy validate` accepts a bare fragment with no global block, and whether validating a config that uses `{env.DNS_...}` needs the variables set, are **unverified** (plan Task 1).

## 5. The DNS-challenge build (`dns` option)

### 5.1 The option

```yaml
dns:
  provider: linode              # the caddy-dns module name: github.com/caddy-dns/<provider>
  version: latest               # latest | a tag
  secrets:                      # secret: true; written to the env file, referenced by Bastet-made names
    api_token: "secret:linode_token"
  settings: {}                  # plain provider fields, written literally
  # generic ACME DNS keys, all optional: propagation_delay, propagation_timeout, ttl, resolvers
  resolvers: [1.1.1.1]
```

Unset means none of this exists on the host. `provider` is free-form, so any `caddy-dns` module works; the three below are documented, others get an info check ("fields are passed through as given and not validated").

- `secrets` is a map of provider field → secret. Bastet writes them to `/etc/caddy/dns.env` (root-owned, 0600) as `DNS_<FIELD>` (for example `DNS_API_TOKEN`) and the Caddyfile refers to `{env.DNS_API_TOKEN}`; the owner never names environment variables.
- `settings` is a map of plain provider fields, written literally into the provider block.
- The Caddyfile gets one global block: `acme_dns <provider> { <field> {env.DNS_<FIELD>} ... <setting> <value> ... }`, only when `dns` is set. A site can still opt out with its own `tls`.
- The generic keys apply to any provider. `resolvers` matters for split-horizon: without it the lab's Caddy asks its local resolver about the public challenge record. Where these keys sit in the Caddyfile is **unverified** (plan Task 1).

**Documented providers** (from each plugin's README, 2026-10-14; the role's body carries this table and each provider as an `examples:` entry):

| | Linode | Cloudflare | Namecheap |
|---|---|---|---|
| Module | `dns.providers.linode` | `dns.providers.cloudflare` | `dns.providers.namecheap` |
| Secret fields | `api_token` (a Personal Access Token) | `api_token` (one scoped token) | `api_key` |
| Plain fields | optional `api_url`, `api_version`, `debug_logs_enabled` | none | `user` (required), optional `api_endpoint`, `client_ip` (deduced when unset) |
| Credential scope | not in the README (it points to libdns-linode); expected: Domains read/write only, **unverified** | `Zone.Zone:Read` and `Zone.DNS:Edit` on the managed zones; the separate `zone_token` exists but is deprecated | not in the README; Namecheap's API probably needs API access enabled and a whitelisted source IP, **unverified** |
| Gotchas | set a low `ttl` (for example `30s`): a TTL of 0 means Linode's default, which resolvers may cache for hours | `Invalid request headers` = the token variable does not reach Caddy (the env file or drop-in is wrong); `expected 1 zone, got 0` = the resolver cannot see public DNS, set `resolvers` | try the sandbox `api_endpoint` first |

### 5.2 Pieces, all data over existing blocks

1. **Packages:** `caddy` (always) and `go` (when `dns` is set) from the Arch repos; Go stays installed because every Caddy bump rebuilds.
2. **Build unit** `caddy-bastet-build.service` (a `files:` entry with `daemon_reload`): `Type=oneshot`, `DynamicUser=yes` (no account on disk, nothing for `accounts:`), a writable build directory as `GOCACHE`/`GOPATH`/`GOBIN` through `Environment=` (`CacheDirectory=caddy-bastet` as first written, **but executing files from it was denied on the owner's host**; the directory kind, `CacheDirectory`, `StateDirectory` or the private `/tmp`, is settled by plan Task 1), `GOTOOLCHAIN=local` (a too-old Go fails loudly instead of downloading a toolchain), network allowed, a long `TimeoutStartSec`, an optional `MemoryMax` (a small VPS). `ExecStartPre` runs `go install github.com/caddyserver/xcaddy/cmd/xcaddy@latest`; `ExecStart` runs `<cache>/bin/xcaddy build <caddy version> --with <module>[@<tag>] --output <cache>/new`. `ExecStartPost=+` (privileged) first validates the **new** binary against the current config (`<cache>/new validate ...`; a failure fails the unit and the old binary stays), then moves it atomically to `/usr/local/bin/caddy-bastet`, writes a one-line stamp of what was built (Caddy, plugin, `xcaddy` and Go versions) to the journal and next to the binary, and runs `systemctl try-restart caddy.service` (only reached after a successful validation). A failed build never reaches the move, so the previous binary keeps serving. The unit has **no access to the credentials**.
3. **Drop-in** `caddy.service.d/bastet-dns.conf`. The packaged unit (read from `caddy-2.11.7-1`) has `ExecStartPre=/usr/bin/caddy validate --config /etc/caddy/Caddyfile`, `ExecStart=/usr/bin/caddy run --config /etc/caddy/Caddyfile` and `ExecReload=/usr/bin/caddy reload --config /etc/caddy/Caddyfile --force`, runs as `User=caddy` with `XDG_DATA_HOME=/var/lib`, `XDG_CONFIG_HOME=/etc`, `MemoryDenyWriteExecute`, `ProtectSystem=strict` and `ReadWritePaths=/var/lib/caddy /var/log/caddy /run/caddy`. So the drop-in clears **all three** (`ExecStartPre=`, `ExecStart=`, `ExecReload=`) and sets each to the same line with `/usr/local/bin/caddy-bastet`; leaving `ExecStartPre` alone would validate a config containing `acme_dns` with the stock binary, which has no such directive, and the unit would never start. It also adds `EnvironmentFile=/etc/caddy/dns.env`. `AmbientCapabilities=CAP_NET_BIND_SERVICE` is in the packaged unit, so the custom binary needs no `setcap`.
4. **Triggers to build:**
   - **pacman hook** `/etc/pacman.d/hooks/caddy-bastet.hook` (a `files:` entry): after Install/Upgrade of `caddy` or `go`, run `systemctl start --no-block caddy-bastet-build.service`. `--no-block` so pacman does not hold its database lock for the length of the build. A reinstall of `caddy` also rebuilds (harmless, a brief restart). A `go` bump rebuilds on purpose: Go standard-library security fixes only reach a TLS server through a rebuild.
   - **a guarded command** in the Bastet run: `systemctl start caddy-bastet-build.service` unless both hold: the first word of `caddy-bastet version` equals that of `caddy version`, **and** the plugin version in `caddy-bastet list-modules --versions` equals the requested one (for `latest`, the version `go list -m -json github.com/caddy-dns/<provider>@latest` reports, 5.4). This catches a new plugin release, a first install, a missed hook and a failed hook build. `systemctl start` on a oneshot blocks until it ends, so a build that still fails **fails the command and the run says so**, with the journal as the hint.
   - The hook and the command start the same unit; systemd serialises them.
5. **Turning `dns` off:** Go stays (removal is deferred); the drop-in is blanked (`ExecStart` back to the packaged unit's line), not deleted. A check cannot see that `dns` was set on an earlier run, so the role's body documents this.

### 5.3 Credentials

`dns.secrets` values are `secret: true` options, so only the entries that use them are marked secret: the env file, and the Caddyfile only if a secret ever reached it (it does not: it holds `{env.DNS_...}`). Secret entries are shown as "(secret)" in the run output and diffs (confirm in Task 1 that the diff body is masked). The file is root-owned, 0600; systemd reads `EnvironmentFile=` as root before dropping to the `caddy` user, so the service reads it and nothing else does. The build unit never sees it. The residual risk is the plugin itself: its code runs inside Caddy and can read the token, which is why `version` can be pinned and why the token should be scoped to DNS only.

### 5.4 Versions

- **Caddy** is tracked by comparing the packaged binary with the built one (`caddy version` against `caddy-bastet version`, first word).
- **The plugin** is tracked by comparing the module version embedded in the built binary (`list-modules --versions`) with the requested one. `latest` is resolved with `go list -m -json <module>@latest`, which asks the Go module proxy exactly what `xcaddy` would pick (semver order, retractions, pseudo-versions for untagged modules); a `git ls-remote --tags` lookup can disagree and finds nothing for untagged plugins. `go list -m` runs no module code.
- **`xcaddy`** follows `@latest` on every build (it only drives the build; Go's checksum database verifies the content); the versions of all four are recorded in the stamp so a build is explainable afterwards. There is no pin option for `xcaddy` until someone needs one.

Known limits, stated plainly in the role's body: unreviewed upstream plugin code is built whenever its newest release changes (so a host can pin); a rebuild restarts Caddy briefly; a failed build is only reported on the next Bastet run (Bastet has no notification channel yet), and until then the older Caddy keeps serving; the first build needs about 1 GB of memory on a small VPS.

## 6. Verification before the plan's code tasks (not yet checked)

The first plan task checks each and the plan changes if one is wrong:

- the packaged `caddy.service` lines (`ExecStart`, `ExecReload`, `AmbientCapabilities`), for the drop-in and for "no `setcap` needed";
- that `go` is in the official repos (the owner says it is) and that `go install ...xcaddy@latest` works inside the sandboxed unit (`GOPATH`, `GOCACHE`, `GOBIN`, `GOTOOLCHAIN=local`, no `HOME`, network allowed);
- that `caddy list-modules --versions` shows the plugin version and `go list -m -json <module>@latest` works for the three documented plugins;
- that `caddy validate --adapter caddyfile` accepts a bare site fragment;
- where the generic ACME DNS keys (`propagation_delay`, `propagation_timeout`, `ttl`, `resolvers`) sit in the Caddyfile;
- Linode's real token scope and Namecheap's account prerequisites (API access, IP whitelist);
- that secret entries are fully masked in diffs and logs;
- that an `on_change:` command with `||`, `&&` and `exit` runs as written (the engine hands the string to a shell), is de-duplicated across entries when identical, and fails the run when it exits non-zero (read in `engine/run.py`; test it);
- whether validating a config that uses `{env.DNS_...}` fails when the variables are not set (decides whether the validator sources the env file, and whether the build unit's privileged tail has to);
- what the sandboxed Jinja templating allows for the site defaults (loops, `is not none`), which fixes the syntax in section 3;
- the exposing host's address field in the inventory, and what an unmanaged host's note holds.

## 7. Deferred (roadmap rows)

`wireguard` role (peers as `each:`, the server key a secret; the laptop and phone key and config question is open); update visibility for software outside the package manager (the newest plugin release as an info line in `check`, if the report can carry it); the collector's final phase, pending and waiting; a DNS collector (the split-horizon records); the local-package block (reviewed `PKGBUILD`) as a possible replacement for the `xcaddy` build; a notification when a background build fails; file removal for stale site files; apt support.
