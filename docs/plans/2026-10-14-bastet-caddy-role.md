# `caddy` role, collectors and the DNS-challenge build — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. In this repo, the `bastet-run-plan` skill supplies the Bastet-specific parts and `bastet-new-role` holds the role checklist.

**Status:** revision 2, draft for the owner's review (2026-10-14); no code is written. Design: `docs/specs/2026-10-14-bastet-caddy-and-collectors-design.md` (read it first). Decisions: D-036 to D-038.

**Goal:** a `caddy` role whose sites are collected from other roles' `proxy` options (routed by the Caddy's `serves` option) plus a manual `sites:` list, with inherited `site_defaults`, a Sites table in the lab dashboard, and an optional `dns` option that builds Caddy with a DNS-challenge plugin on the host, documented for Linode, Cloudflare and Namecheap.

**Tech stack:** Python ≥3.12, pydantic, PyYAML, Jinja2 (the existing sandbox), pytest, ruff. The role itself is Markdown with no Python; the only Python is the `collects` contract feature (Task 2) and the dashboard table (Task 6).

## Global constraints

- Everything in `docs/plans/2026-10-11-bastet-time-role.md` "Global Constraints" applies (unit tests touch no real inventory, no network, `tmp_path` only, placeholder data such as `example.com` and `10.1.x.x`; unique test file names; every message through `bastet.ui.out`; version only in `pyproject.toml`; `docs/roles.md` generated; `ruff` and `scripts/privacy-check` clean; no deletion features; commit messages end with the attribution lines).
- Follow `docs/testing.md`: one layer per behaviour, parametrize, no sleeps, a small budget per feature.
- The role is data. A new contract or block feature is added only for something this role needs, with its own tests, and recorded in the roadmap.
- The AUR is not used (D-013, D-038).

## Verified (repo side, 2026-10-14)

Read from the code; the host-side items are in `caddy-verify.sh` (owner runs it on an Arch host; its output is recorded here when it arrives).

- **Triggers** (`engine/run.py`, `engine/model.py`): run after all fixes, once per host, only for changed items; a `Trigger` is a frozen dataclass, so triggers are de-duplicated by value (label + command + the rest): every file entry must use the **same** `on_change` `name:` and `run:` text. A failed trigger is recorded failed, later triggers stop, and the run counts as failed. `restart`/`reload` unit triggers have an `only_if` running check; `on_change` command triggers (order 60) do not, so the command does its own `is-active` check.
- **Shell:** a trigger command is a script run as root under `sh -e` through a heredoc (`engine/script.py`), so multi-line commands work and a failing validation stops the script before the reload. `exit 0` skips the rest cleanly.
- **Templating** (`engine/templates.py`): sandboxed Jinja2 with `StrictUndefined`; `{% for %}`, `{% if x is not none %}` work; an unset option written into text is an error (`reject_none`), so every optional part sits in an `{% if %}`. A dict merge for `site_defaults` is probably `dict(defaults, **site)`; Task 4 tests it.
- **Secrets:** a secret resource's content is shown as `(secret)` in change text and its command is recorded as hidden (`engine/report.py`, `run._exec_status`); a read's output is never recorded. Secret *values* in trigger commands do not occur (the commands name the env file, not its content).
- **Host address:** `core/render.py:_address`: the host note's `ip` (unless `dhcp`), else `address`; an unmanaged host's note has the same fields, so a manual `sites:` entry or `upstream:` is needed when neither exists.

## Tasks

### Task 1 — Verify the unchecked facts (spec section 6)

Read-only. The repo-side items are done (see "Verified"); the host-side items run from `caddy-verify.sh`, and the DNS providers' own prerequisites (Linode scope, Namecheap account) are **not** validated by the owner and stay documented as unverified. Write the findings into the top of this plan under "Verified" (and fix the spec if one is wrong). Where a fact needs an Arch host with network, mark it "owner to check" and give the command.

- [ ] The packaged `caddy.service` on Arch: `ExecStart`, `ExecReload`, `AmbientCapabilities`, user/group, config path (`pacman -Ql caddy`, `systemctl cat caddy`).
- [ ] `go install github.com/caddyserver/xcaddy/cmd/xcaddy@latest` works inside a `DynamicUser` unit with `GOPATH`/`GOCACHE`/`GOBIN` under the cache directory, `GOTOOLCHAIN=local` and no `HOME`; the resulting `xcaddy build <version> --with <module>@<tag> --output <path>` works there; `caddy list-modules --versions` shows a plugin's version; `go list -m -json <module>@latest` works for the Linode, Cloudflare and Namecheap plugins.
- [ ] `caddy validate --adapter caddyfile --config <fragment>` accepts a bare site block with no global block, and what it does as root (storage directories).
- [ ] An `on_change:` entry with `||`, `&&` and `exit` runs as written, is de-duplicated across entries when identical (`Trigger` equality), and a non-zero exit fails the run and stops later triggers; whether a read-only `commands:` entry can be written to run every time without counting as a change; whether `caddy validate` of a config using `{env.DNS_...}` needs the variables set.
- [ ] Where `propagation_delay`, `propagation_timeout`, `ttl` and `resolvers` sit in the Caddyfile (global `acme_dns` block or an `issuer`/`tls` block), from the plugins' docs and `caddy adapt`.
- [ ] Linode's token scope (libdns-linode README) and Namecheap's account prerequisites (API access, IP whitelist, sandbox); correct spec section 5.1.
- [ ] Secret entries are fully masked in the run output, diffs and logs (`engine/files.py`, the console/diff rendering).
- [ ] What the sandboxed Jinja templating of a `template:` file allows (`{% for %}`, `is not none`, dict merge), by reading `engine/templates.py` and the time/pacman templates. This fixes the `site_defaults` syntax.
- [ ] Whether an `each:` entry can render a different file per item, and whether a `files:` entry with `content` can write a pacman hook and a unit with `daemon_reload` (the `time`/`pacman` roles show the forms).
- [ ] The exposing host's address field in the inventory (`host_data()` in `core`, a host note's `address`), and what an unmanaged host's note holds.

Done when: every item has a one-line finding; the owner sees any change to the spec.

### Task 2 — The `collects` contract feature

Files (expected): `src/bastet/roles/{contract,resolve,expr,declarative,builtin}.py`, `src/bastet/cli/run.py`, `src/bastet/data/docs/writing_roles.md`, tests under `tests/roles/`.

- [ ] Parse `collects: {proxy: <list option>}` in a role file; the target must be a `list` option; refuse unknown source names; `docs`/`pages` show it.
- [ ] A function `collect(inv, caddy_note, types, roles)` (in `roles/`), used by `plan_for`: resolve every other host (cached for the run), read each applied role's `proxy` list, compute each exposure's hostname (`subdomain` + the scope's domain from the lab note's `domains:`; the scope optional when `domains:` has one entry) and route it by the spec's section 2.3 table (`via`, else the Caddy roles whose `serves` contains the scope). Return site dicts with `host`, `source`, the resolved upstream (`127.0.0.1` when the proxy is on the exposing host) added.
- [ ] `plan_for` passes the collected list into `HostInfo`/`builtin.batches_for` so that `declarative.build` appends it to the `sites` option before `expr.context()`.
- [ ] Errors, each naming the file and key: a scope missing from `domains:` (listing the scopes); no scope given when `domains:` has several; two or more Caddies serve the scope and there is no `via`; `via` names a non-`caddy` role; `serves` names a scope not in `domains:`; a secret field in `proxy`; an exposure with no address and no `upstream:`; a duplicate resolved hostname on one Caddy (both sources named; manual sites included; no precedence). Warning (a check on the exposing host): no Caddy serves the scope.
- [ ] Tests (parametrized where they share a shape): collects from two hosts; one scope in two exposures giving the same hostname on two Caddies (split-horizon) and an error when one Caddy serves both; `serves` set by a group note; `via` pinning and `via` with a list; each row of the routing table; optional scope; unmanaged host still scanned; nothing collected leaves `sites` as the manual list; no `collects` leaves everything unchanged (regression).

Done when: a demo role with `collects` builds sites from two fake exposing hosts and two fake Caddies in a `tmp_path` inventory.

### Task 3 — `caddy` role, plain

Files: `src/bastet/data/roles/caddy/caddy role.md`, the Caddyfile and site templates in the same folder (names fixed by Task 1), tests under `tests/roles/`.

- [ ] Role note per spec section 4: frontmatter (`name: caddy`, `version: 0.1.0`, `api: 0`, `os: [arch]`, `collects`, options incl. `serves`, `checks:`), body documenting exactly what it does with no options, a `## Changes` list.
- [ ] Entries: `packages: caddy`; main Caddyfile (template); directory `conf.d`; one self-contained file per site via `each: sites`, named after the hostname, each with `validate: caddy validate --adapter caddyfile --config %s`; **no `reload:` triggers**: every file entry carries the same gated `on_change:` reload (spec 4.2: running check, whole-config validate, then `systemctl reload`; the validator switches with `dns`); a standing read-only whole-config `commands:` validation; `systemd:` unit enabled and started.
- [ ] `checks:` info that stale site files stay (removal deferred); warning for a site with neither `upstream` nor a collected address; error for a bad hostname; error for a duplicate hostname in the list.
- [ ] Tests: no options builds exactly the documented defaults; one site; two sites; `extra`; `snippets`; a line break in a curated value refused; unset `email` writes no global line; the site entry carries `validate:`; no entry uses `reload:`/`restart:`; all file entries carry one identical `on_change` command (so it runs once); that command validates before it reloads and does nothing for a stopped unit; the standing validation entry exists.

Done when: `uv run pytest tests/roles -q` passes and the role parses.

### Task 4 — Site defaults

- [ ] `site_defaults` option and the inheritance in the template/entries per the syntax Task 1 settled: site value, else default, else nothing; `false`/`0`/`""`/`[]` override; `headers` merge by name; `extra` appended; decide whether a site can drop an inherited value (`null`).
- [ ] Tests (parametrized): each knob with the site unset/set/falsy, headers merge, a group note's defaults reaching one proxy and not the other.

### Task 5 — `dns` option, the build and the provider documentation

- [ ] Option `dns` per spec 5.1: `provider` (required, free-form), `version` (default `latest`), `secrets` (a `secret: true` map of provider field → value), `settings` (plain map), and the optional generic keys `propagation_delay`, `propagation_timeout`, `ttl`, `resolvers`. A check errors on an empty `provider`; an info check for a provider outside the documented three.
- [ ] Entries behind `when: dns is not none`: package `go`; the build unit (with `ExecStartPre` doing `go install ...xcaddy@latest`, `GOTOOLCHAIN=local`, `ExecStartPost` validating the new binary before the move, then the stamp, `daemon_reload`); the drop-in (its change triggers a gated restart, not a plain `restart:`); `/etc/caddy/dns.env` (0600, secret, `DNS_<FIELD>` names); the pacman hook (`caddy` and `go` targets, `--no-block`); the guarded `systemctl start` command (guard per spec 5.2, `latest` resolved with `go list -m -json`); the global `acme_dns <provider> { ... }` block.
- [ ] The role's body gets a "DNS providers" section with the spec's table (Linode, Cloudflare, Namecheap: module, secret and plain fields, scope, gotchas, updated by Task 1), the credentials and versions notes, and the known limits; the frontmatter `examples:` carries one `dns` example per documented provider (Linode first) with `secret:` references.
- [ ] A check cannot see that `dns` was set on an earlier run, so what happens when it is turned off (Go stays, the drop-in is blanked) is documented in the body instead.
- [ ] Tests: no `dns` emits none of this; `dns` emits exactly the listed entries; the env file is the only secret-marked entry and the Caddyfile holds only `{env.DNS_...}`; the build unit has no `EnvironmentFile`; the guard text contains both comparisons; the build unit validates before moving; `version: <tag>` pins; each documented provider's example builds the expected provider block; unit and hook content snapshots (small).
- [ ] The real build is **not** run in the test suite (needs network and Go); the owner checks it on a host.

### Task 6 — Sites table in the lab dashboard

Files (expected): `src/bastet/core/render.py` (`dashboard()`), the collector from Task 2, tests under `tests/`.

- [ ] A **Sites** table in the lab dashboard (the generated part of the lab note): hostname, scope, proxy host, upstream, source (the exposing host, or a manual `sites:` entry). Built from the Task 2 collector over every `caddy` role in the inventory; absent when no site exists. A name collision shows in the table as well as being the run error.
- [ ] Tests: two exposing hosts and one manual site give three rows; the split-horizon name appears once per Caddy; an inventory without `caddy` renders no Sites section (regression).

### Task 7 — Docs, version, roadmap

- [ ] `uv run python scripts/gen_roles_doc.py`; commit `docs/roles.md`.
- [ ] `docs/ROADMAP.md`: tick `caddy` (VPS apps step 4, roles table V1), add the deferred rows from spec section 7, update "Next session starts here".
- [ ] `scripts/version-bump` to the next Y (0.4.0: new contract feature and a new role); role hashes recorded; `--check` passes.
- [ ] `ruff check src tests`; `scripts/privacy-check` (copy `.privacy-patterns` into the worktree first, delete after).

### Task 8 — Owner's checks (give him the commands; the controller never merges before "passed")

- `uv run pytest -q` (full suite).
- On a real Arch host: `bastet run -c <host>` shows the diff for the plain role; apply; then add a `dns` note (Linode) and check the build unit, the hook (`pacman -S caddy` reinstall triggers a build), the drop-in, `caddy-bastet list-modules --versions` and the certificate issue for a name.
- On the VPS and the lab proxy: the generated `conf.d` files for the same name on both, and the lab note's Sites table.

## Decided by the owner (2026-10-14)

1. Restart on every rebuild: the default stands (`try-restart` after the move) and the role's body says so.
2. The exposure option is **`proxy`**, a list; routing is by the Caddy's **`serves`** option and an optional **`via`** (no lab map, no `proxies:`).
3. **No lab-level site defaults**; the lab note **lists every site** (Task 6).
4. `xcaddy` comes from `go install ...@latest` in the build unit, not from a package; `GOTOOLCHAIN=local`; the built versions are recorded.
5. Internal and external services use the **same names** (split-horizon); the scope is optional when the lab has one domain.
6. DNS providers are documented in the role (Linode, Cloudflare, Namecheap), and the `dns` option is `provider` + `secrets` + `settings`.

## Ledger

(Filled in when `bastet-run-plan` starts.)
