# `caddy` role, collectors and the DNS-challenge build — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. In this repo, the `bastet-run-plan` skill supplies the Bastet-specific parts and `bastet-new-role` holds the role checklist.

**Status:** draft for the owner's review (2026-10-14); no code is written. Design: `docs/specs/2026-10-14-bastet-caddy-and-collectors-design.md` (read it first). Decisions: D-036 to D-038.

**Goal:** a `caddy` role whose sites are collected from other roles' `proxy` options plus a manual `sites:` list, with inherited `site_defaults`, and an optional `dns` option that builds Caddy with a DNS-challenge plugin on the host.

**Tech stack:** Python ≥3.12, pydantic, PyYAML, Jinja2 (the existing sandbox), pytest, ruff. The role itself is Markdown with no Python; the only Python is the `collects` contract feature (Task 2).

## Global constraints

- Everything in `docs/plans/2026-10-11-bastet-time-role.md` "Global Constraints" applies (unit tests touch no real inventory, no network, `tmp_path` only, placeholder data such as `example.com` and `10.1.x.x`; unique test file names; every message through `bastet.ui.out`; version only in `pyproject.toml`; `docs/roles.md` generated; `ruff` and `scripts/privacy-check` clean; no deletion features; commit messages end with the attribution lines).
- Follow `docs/testing.md`: one layer per behaviour, parametrize, no sleeps, a small budget per feature.
- The role is data. A new contract or block feature is added only for something this role needs, with its own tests, and recorded in the roadmap.
- The AUR is not used (D-013, D-038).

## Tasks

### Task 1 — Verify the unchecked facts (spec section 6)

Read-only. Write the findings into the top of this plan under "Verified" (and fix the spec if one is wrong).

- [ ] The packaged `caddy.service` on an Arch host: `ExecStart`, `ExecReload`, `AmbientCapabilities`, user/group, config path (`pacman -Ql caddy`, `systemctl cat caddy`; or the package page).
- [ ] `go` and `caddy` are in the official repos; `go install github.com/caddyserver/xcaddy/cmd/xcaddy@latest` works inside a `DynamicUser` unit with `GOPATH`/`GOCACHE`/`GOBIN` under the cache directory and no `HOME`; `caddy list-modules --versions` shows a plugin's version; the resulting `xcaddy build <version> --with <module>@<tag> --output <path>` works there.
- [ ] The exposing host's address field in the inventory (`host_data()` in `core`, a host note's `address`/`ip`), and what an unmanaged host's note holds.
- [ ] What the sandboxed Jinja templating of a `template:` file allows (`{% for %}`, `is not none`, dict merge), by reading `engine/templates.py` and the time/pacman templates. This fixes the `site_defaults` syntax.
- [ ] Whether an `each:` entry can render a different file per item, and whether a `files:` entry with `content` can write a pacman hook and a unit with `daemon_reload` (the `time`/`pacman` roles show the forms).
- [ ] Whether `validate:` on a `files` entry can run `caddy validate --config`.

Done when: every item has a one-line finding; the owner sees any change to the spec.

### Task 2 — The `collects` contract feature

Files (expected): `src/bastet/roles/{contract,resolve,expr,declarative,builtin}.py`, `src/bastet/cli/run.py`, `src/bastet/data/docs/writing_roles.md`, tests under `tests/roles/`.

- [ ] Parse `collects: {proxy: <list option>}` in a role file; the target must be a `list` option; refuse unknown source names; `docs`/`pages` show it.
- [ ] A function `collect(inv, proxy_role_note, types, roles)` (in `roles/`), used by `plan_for`: resolve every other host (cached for the run), take each applied role's `proxy` option value, keep the ones whose domain's `proxy:` link (lab note, overridable by group/host) points at this host's role, and return exposure dicts with `host` and `address` added.
- [ ] `plan_for` passes the collected list into `HostInfo`/`builtin.batches_for` so that `declarative.build` appends it to the `sites` option before `expr.context()`.
- [ ] Errors: duplicate name on one domain (both files named), a secret field in `proxy`, an exposure with no address and no `upstream:`. A `checks:`-style warning on the exposing host when its domain has no proxy.
- [ ] Tests: collects from two hosts, filters by `proxies:` link, group override of the proxy, duplicate name, unmanaged host still scanned, nothing collected leaves `sites` as the manual list, no `collects` leaves everything unchanged (regression).

Done when: a demo role with `collects` builds sites from two fake exposing hosts in a `tmp_path` inventory.

### Task 3 — `caddy` role, plain

Files: `src/bastet/data/roles/caddy/caddy role.md`, `.../caddy/Caddyfile.j2` (names fixed by Task 1), tests under `tests/roles/`.

- [ ] Role note per spec section 4: frontmatter (`name: caddy`, `version: 0.1.0`, `api: 0`, `os: [arch]`, `collects`, options, `checks:`), body documenting exactly what it does with no options, a `## Changes` list.
- [ ] Entries: `packages: caddy`; `files:` main Caddyfile (template, `validate:` with `caddy validate`, `reload: [caddy.service]`); directory `conf.d`; one file per site via `each: sites`; `systemd:` unit enabled and started.
- [ ] `checks:` info that stale site files stay (removal deferred); warning for a site with neither `upstream` nor a collected address; error for a bad name.
- [ ] Tests: no options builds exactly the documented defaults; one site; two sites; `extra`; `snippets`; a line break in a curated value refused; unset `email` writes no global line.

Done when: `uv run pytest tests/roles -q` passes and the role parses.

### Task 4 — Site defaults

- [ ] `site_defaults` option and the inheritance in the template/entries per the syntax Task 1 settled: site value, else default, else nothing; `false`/`0`/`""`/`[]` override; `headers` merge by name; `extra` appended.
- [ ] Tests (parametrized): each knob with the site unset/set/falsy, headers merge, a group note's defaults reaching one proxy and not the other.

### Task 5 — `dns` option and the build

- [ ] Option `dns` (`provider` required, `version` default `latest`, `env` secret map) with a check that errors on an empty `provider`.
- [ ] Entries behind `when: dns is not none`: package `go`; the build unit file (with `ExecStartPre` doing `go install ...xcaddy@latest`; `daemon_reload`), the drop-in, the credentials file (0600, secret), the pacman hook, the guarded `systemctl start` command (guard per spec section 5, `latest` resolved with `git ls-remote --tags --refs`), the global `acme_dns` line.
- [ ] A check cannot see that `dns` was set on an earlier run, so what happens when it is turned off (Go stays, the drop-in is blanked) is documented in the role's body instead.
- [ ] Tests: no `dns` emits none of this; `dns` emits exactly the listed entries; the credentials file is the only secret-marked entry; the guard text contains both comparisons; `version: <tag>` pins; unit and hook content snapshots (small).
- [ ] The real build is **not** run in the test suite (needs network and Go); the owner checks it on a host.

### Task 6 — Sites table in the lab dashboard

Files (expected): `src/bastet/core/render.py` (`dashboard()`), the collector from Task 2, tests under `tests/`.

- [ ] A **Sites** table in the lab dashboard (the generated part of the lab note): name, domain, proxy host, upstream, source (the exposing host, or a manual `sites:` entry). Built from the Task 2 collector over every `caddy` role in the inventory; absent when no site exists.
- [ ] Tests: two exposing hosts and one manual site give three rows; a name collision shows in the table and is also the run error; an inventory without `caddy` renders no Sites section (regression).

### Task 7 — Docs, version, roadmap

- [ ] `uv run python scripts/gen_roles_doc.py`; commit `docs/roles.md`.
- [ ] `docs/ROADMAP.md`: tick `caddy` (VPS apps step 4, roles table V1), add the deferred rows from spec section 7, update "Next session starts here".
- [ ] `scripts/version-bump` to the next Y (0.4.0: new contract feature and a new role); role hashes recorded; `--check` passes.
- [ ] `ruff check src tests`; `scripts/privacy-check` (copy `.privacy-patterns` into the worktree first, delete after).

### Task 8 — Owner's checks (give him the commands; the controller never merges before "passed")

- `uv run pytest -q` (full suite).
- On a real Arch host: `bastet run -c <host>` shows the diff for the plain role; apply; then add a `dns` note and check the build unit, the hook (`pacman -S --needed caddy` reinstall triggers a build), the drop-in and `caddy-bastet list-modules --versions`.
- On the VPS with two exposing hosts (or one plus a manual `sites:` entry), check the generated `conf.d` files and a certificate issue.

## Decided by the owner (2026-10-14, answers to the open questions)

1. Restart on every rebuild: not asked again; the default stands (`try-restart` after the move) and the role's body says so.
2. The exposure option is **`proxy`**; the lab note's map is `proxies:`.
3. **No lab-level site defaults**; the lab note **lists every site** (Task 6).
4. `xcaddy` comes from `go install ...@latest` in the build unit, not from a package.

## Ledger

(Filled in when `bastet-run-plan` starts.)
