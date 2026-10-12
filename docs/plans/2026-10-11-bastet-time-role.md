# Contract hardening and the `time` role — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. In this repo, the `bastet-run-plan` skill supplies the Bastet-specific parts; the `bastet-new-role` skill holds the role checklist.

**Status:** revised 2026-10-11 after an independent audit of the contract code (`src/bastet/roles/*.py`, `src/bastet/engine/{run,model,systemd,files}.py`) and the owner's decisions. **Owner decisions D-1 to D-3 received 2026-10-12; awaiting the owner's final read; no code is written yet.**

**Goal:** finish the Markdown role contract now so the next role is boring to write (options, supported systems, compose blocks, conditions, docs, tests), then write the `time` role on it as the first real proof. Preserve the architecture: Markdown roles over Python blocks, blocks do the work and report changes, the contract only describes and sequences.

**Tech Stack:** Python ≥3.12, pydantic, PyYAML, Jinja2 (existing sandbox), pytest, ruff.

**Spec / docs:** `docs/specs/2026-10-10-bastet-roles-architecture-design.md`; `src/bastet/data/docs/writing_roles.md`; models `roles/pacman/pacman role.md`, `roles/apt/apt role.md`.

## Global Constraints

- **Unit tests** never touch the real inventory, `~/.config/bastet`, `~/.local/share/bastet`, `~/.ssh`, the real `~/.cache` or `$XDG_RUNTIME_DIR`; no network; `tmp_path` only; placeholder data only (10.1.x.x addresses, host names like pve1/media01). Tests are focused on behaviour; no padding.
- **Test file basenames unique across `tests/`** (no `__init__.py`).
- Every message goes through `bastet.ui.out`; no `typer.echo` in `src/`; no "spec §"/"Task N" references in `src/`.
- The version is written only in `pyproject.toml`.
- `docs/roles.md` is generated (`uv run python scripts/gen_roles_doc.py`); a repo test checks it.
- `ruff check src tests` and `scripts/privacy-check` pass before the final commit.
- Nothing in Bastet deletes notes, records or host files yet; this plan adds no deletion.
- A role is data: no Python in a role without a very good reason (the time zone list tooling is repo tooling, not role code).
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` and the `Claude-Session:` line.

## Owner decisions (2026-10-11, supersede earlier plan text)

1. **Strict time zone validation** with `choices_from:`; the list is regenerated from `timedatectl list-timezones` at version bumps (Task 8), not per commit or run.
2. **`systemd-timesync` stays in the `systemd` role's `accounts:`** (an OS-provided account is recognised whether or not an optional role is applied). Recognised accounts (OS file, role `accounts:`, `allowed`) stay distinct from accounts Bastet manages (`User` entries); the audit found both already represented (A-17). No notes about unaccounted users are needed.
3. **NTP:** `ntp` unset = leave sync alone; `true` = write applicable settings and enable/start; `false` = stop/disable only. Disabling never deletes or rewrites managed config. No file-removal feature is invented here.
4. **Reload classes are separate:** `daemon-reload` only for unit definitions and unit drop-ins; restart/reload for application config; enable/disable and start/stop are the `Unit` resource. `/etc/systemd/timesyncd.conf.d/bastet.conf` needs a service restart, not a daemon-reload.
5. **Platforms:** Arch = systemd-timesyncd (built). Debian/Proxmox = chrony, one item, **not built**; `ntp: true` (or any timesyncd key, which require it) there is an **error**, not a skip; `ntp: false` there is an **info** note ("not applied on this system yet; nothing changed"), never an error, because stopping sync is not something Bastet can do there yet and asking for it off is harmless. LXC = time sync is delegated to the node: an **info** message, never a warning, and the role never claims it configured sync. The time zone applies wherever `timedatectl` works. An unknown OS is treated like Debian, never as supported.
6. `rtc_local` is dropped from the role (owner has no dual-boot hosts); the `systemd` block keeps the field.
7. The time options leave the Python `systemd` role (its `role.yml`); the `systemd` block and its `kind: time` entry stay.
8. **Loops over list options are included** (`each:`, Task 6): caddy sites, mounts, fail2ban jails, sudoers and WireGuard peers will need them.
9. **Triggers restart or reload only a running unit.** A unit that has *failed* is not restarted by a trigger either (a role that wants it up says so with a `Unit` entry `state: up`, which starts it). Known, accepted exception.
10. **Opting a host or group out of an inherited option (Task 2b).** An explicit `null` in a note is kept as an ordinary value while the levels merge, so the usual rules decide: the highest-ranked note wins (a host that sets `ntp: false`, or any real value, beats a lab `null` or `true` as it does today), and two notes of the same rank that disagree still clash. **Only after the merge finished** is a winning `null` turned into "unset" (the option then falls back to its default, or to nothing). Nothing is removed during merging, so the result never depends on the order of the notes. Today the resolver drops `None` before merging (`contract.check_values`), so the only override is another real value. Example: the lab sets `ntp: true`; the Debian group sets `ntp: null`; its hosts get the time zone and no sync error. The `time` role's lab-wide warning names this way out.
11. **Conditional overrides in role notes (`overrides:`, Task 2c; contract, not role).** A role note (lab, group, type or host) may carry `overrides:`, a list of `{when: <expression over host and lab facts>, <option>: <value>, …}`. For a host where `when` is true the entry's values replace that same note's own values, at that note's rank (so a lab note can say "`ntp: true`, except `ntp: null` (blank, so unset) where `not host.arch_like`" without a separate group or type note, while a higher-ranked note still wins as usual). Values may be `null` (decision 10). This is the lab-wide override mechanism for any partly cross-system role.
12. **Lab-wide warning:** `checks:` can see where an option's value came from (`applied.origin.<option>`: `lab`, `group <name>`, `host <name>`, …). The `time` role uses it to warn when `ntp` is set from the lab note. The check (`bastet run` without applying) already shows the per-host Debian/Proxmox error.

## Audit: what the contract does today

Verified by reading the code (not assumed). ✔ implemented and covered by tests in `tests/roles/`; ◐ implemented, thin tests or a flaw; ✗ missing.

| # | Area | Finding |
|---|---|---|
| A-1 | Option types | ✔ `string int number bool list map object any`; `required` (object fields, secrets), `default`, `min/max`, `single_line`, `choices`, `shorthand`, `merge_default`; lenient `"yes"/"true"`/numeric text for bool/int/number (`contract._lenient`); unknown options refused with a did-you-mean (`check_values`). |
| A-2 | Unset vs false | ◐ Unset is `None` (`check_values` skips `None`); `false`, `0`, `""`, `[]` survive. But `when: ntp` is plain truthiness, so authors must write `ntp is not none`. Needs documentation and tests of `false`/`0`/`""`/`[]` through `when:`. Defaults merge before entries are built, so a default is indistinguishable from a note value there (fine, but `requires` must check the pre-default values). |
| A-3 | `requires` / `conflicts` | ✗ no cross-option validation in Markdown roles; only the Python builders do it (`builtin._systemd`, `_packages`). |
| A-4 | `choices` | ✔ small enumerations. `choices_from` ✗. |
| A-5 | Expressions | ✔ sandboxed Jinja; `when:` on packages, users, systemd, files, commands; facts `host.{name,type,os_id,arch_like,debian_like,container,physical,cpu}` and `lab`. Parse time checks syntax and that names are options or `host`/`lab` ✔. ◐ it does **not** check the attribute (`host.arch_likee` fails only when the role is first built for a host). |
| A-6 | Composition | ✔ entries from several blocks in one role, deterministic order by block slot (`packages, users, files, systemd, commands`) plus `before:`/`after:`. ✗ no way to group entries under one condition (`sections:`). |
| A-7 | Role-level checks | ✗ no way to warn or stop from a role; the only channel is the engine's `Unsupported` ("skipped with this reason"). |
| A-8 | Silent drops | ✗ `entries._systemd` silently strips `ntp`/`rtc_local` for `kind: time` on containers and silently emits nothing for `kind: hostname` on containers. Contradicts "never silently ignore". (The Python `builtin._systemd` has its own container handling and is untouched.) |
| A-9 | Change-triggered actions | ✔ `restart:`/`reload:` unit lists on `files` entries (File, Line, Block and `edit: ini` Settings via `entries.triggers`) become `Resource.on_change` triggers; run once per host after all fixes, de-duplicated, ordered (`daemon-reload` order 10 before restarts 50), only for resources that actually changed, none for failed or skipped items, `restart` has an is-active check with retries, recorded in `run.triggers` and as `trigger_fired` events. `systemd` `kind: dropin` adds `daemon-reload` + restart. ◐ thin tests of ordering/de-duplication/no-op. ✗ no `daemon_reload` flag or generic command trigger on a `files` entry (needed for Quadlet files, sysctl.d, CA certs); `packages`/`commands` entries cannot trigger anything. |
| A-10 | Trigger semantics | ✗ **flaw:** `restart` and `reload-or-restart` start a unit that is stopped. A trigger running after a `Unit` stop (or for a disabled service) would bring it back up. |
| A-11 | Unit lifecycle | ✔ enable/disable and start/stop compare current state and are idempotent; a missing unit counts as already disabled/down; no systemd = `Unsupported`. ◐ enabling a missing unit gives a raw `systemctl` failure; the message should say the unit does not exist (package missing?). |
| A-12 | Failure handling | ✔ after the first failed item the rest of that host is skipped with the reason; triggers of changed items still run. |
| A-13 | `edit: ini` | ✔ managed block per section, originals commented, idempotent, creates the file and section when absent (read in `Settings.wanted`). ◐ not tested for a **new file in a new directory** (the drop-in case) or for mode/owner (Settings carries none). Only top-level options with `key:`/`section:` feed it, not `object` fields. |
| A-14 | Value safety | ✔ `single_line`, and `_keyed`/`_entry_values` refuse line breaks in keyed values. |
| A-15 | Validation timing | ◐ role parsing and note value checks happen at load; entry resolution errors happen at build. Not proven by a test that a bad role stops a run before any host command. |
| A-16 | Generated docs | ◐ `scripts/gen_roles_doc.py` and `roles/pages.py` render options; they must learn `requires`, `conflicts`, `choices_from` (collapsed long lists), `checks`, `sections`. |
| A-17 | Accounts | ✔ `accounts:` on roles (recognised) vs `User` entries (managed) vs OS file vs `allowed`; hidden only when the role is applied (`test_role_accounts.py`, `test_expected_accounts.py`). `systemd-timesync` is already in the `systemd` role. |
| A-18 | Block independence | ✔ blocks are engine classes (`Unit`, `TimeSettings`, `Settings`, …); a Markdown role calls them directly; the Python `systemd` role is not involved. A test must pin that the `time` role builds with no other role applied. |
| A-19 | File removal | ✗ not implemented; roadmap marks removal deferred. |
| A-20 | Version bump | ✗ no workflow: the version lives only in `pyproject.toml` ("bump at each milestone, no tags"). |

## Confirmed gaps → changes

| Gap | Change | Task |
|---|---|---|
| A-2, A-13, A-15, A-18 | pinning tests for behaviour that exists but is thinly tested | 1 |
| A-3 | `requires` / `conflicts` option keys | 2 |
| A-4 | `choices_from:` | 3 |
| A-5, A-7, A-8 | notes channel + role `checks:` (info/warning/error); container drops become visible notes; parse-time check of `host.<fact>` | 4 |
| A-6 | `sections:` | 5 |
| loops (decision 8) | `each:` on entries | 6 |
| A-9, A-10, A-11 | `daemon_reload` and `on_change` on `files` entries; restart/reload only act on a running unit; clearer missing-unit error | 7 |
| A-20 | version-bump script that refreshes and validates the time zone list; a test that fails when the list was not refreshed for the version | 8 |
| A-16 | docs and generators | 10 |

## Forward-looking gap analysis (from `docs/ROADMAP.md`; the role list is not invented)

| Role / area | Expressible after this plan? | Missing shared capability? | Reusable? | Do now? |
|---|---|---|---|---|
| base | Yes: packages with `when: host.physical` for microcode, per-OS names via `sections:` | No | – | – |
| caddy | Yes: package, `files` with `validate:`, `reload:`, unit, `directory` for `conf.d`; several sites via `each:` | Restart semantics (A-10) | yes | Tasks 6, 7 |
| forgejo / vaultwarden | Yes: package, `edit: ini` (flat keyed options), systemd drop-in, secrets as whole values | `edit: env` is a **files-block** feature the roadmap already assigns to vaultwarden | block work | with that role |
| docker / podman | Quadlet files + `daemon-reload` + units: yes once `daemon_reload` exists | `daemon_reload` on files (A-9); rootless **user-scope** units (`systemctl --user`, linger) | daemon_reload yes; user units need block design | daemon_reload now (Task 7); user units deferred (no near role needs them) |
| WireGuard (not on the roadmap; judged from your table) | Yes: secret key as whole value, mode `0600`, `wg-quick@` unit, restart on change, sysctl via file + `on_change` | generic command trigger (A-9) | yes | Task 7 |
| monitoring (grafana, glances, …) | Yes: packages, templates, units, multi-component | A loop over a list option (one file/entry per item) | yes (caddy sites, mounts, fail2ban jails, sudoers, WireGuard peers) | Task 6 (`each:`) |
| Proxmox / LXC | Host-type conditions and info/error checks: yes | JSON `api` block for guest lifecycle is a **block**, not contract | block | later |
| storage / ZFS | Report-first roles: yes | More host facts (disks) and destructive-operation safeguards: the facts list is extensible (`expr.context`), safeguards are block/design | facts: cheap later | later |
| fetch / git | A new block needs a new entry list in the contract (`ROLE_NOTE_KEYS`, a `parse_*`, an `entries` builder) | Adding a **block** touches the contract by design; acceptable | – | when the block is built |
| users / accounts | Yes (A-17) | No | – | – |

## Contract vs blocks (kept)

Contract: option schemas and validation, conditions, composition and sections, ordering, change-trigger *declarations*, messages. Blocks: doing the work, detecting change, idempotency, platform execution, reporting. The additions below only declare or validate; none adds block-specific behaviour.

## The final contract additions

All keys are optional and change nothing for existing roles.

- **`requires` / `conflicts` (option keys).** `requires: [a, b]` (this option set ⇒ `a`, `b` set), `requires: {a: true}` or `{a: [x, y]}` (and `a` has that value), `conflicts: [a]`. "Set" = not `None` in the note's values before defaults, so `false`, `0`, `""`, `[]` count as set. Inside an `object` the names are sibling fields. Refused when the role is read if a name does not exist; the error names role, file and both options.
- **`overrides:` in role notes.** `overrides: [{when: "not host.arch_like", ntp: null}, …]`. `when` sees `host` and `lab` facts only (options are what is being decided, so they are not visible), is checked when the note is read (syntax, fact names, option names, value types, each through the option's normal checks, naming the note and key), and is evaluated per host in `resolve` before the notes are merged. Matching entries apply in listing order over the note's own values, at the note's rank. `overrides` becomes a reserved note key. `applied.origin.<option>` shows `lab (override)` etc. so a check can tell.
- **Clearing an inherited option (`key: null`).** `check_values` keeps an explicit null instead of dropping it. `resolve` merges nulls like any value (rank decides, same-rank disagreement clashes, also for fields inside map and object options), and a single final pass after all ranks are merged turns the winning nulls into unset before `with_defaults`. A null with nothing inherited does nothing. `applied.origin.<option>` is empty for a cleared option. Caveat: a bare `key:` line in a note is also YAML null, so it now clears an inherited value instead of being ignored (the audit finds no shipped role or starter that writes a bare key; Task 2b checks that and the `bastet add role` output).
- **`choices_from: <file>`.** One value per line in a file in the role's folder; blank lines and `#` comments ignored. Values are checked like `choices`; the file is checked when the role is read (exists, non-empty, no duplicates, not together with `choices`). Generated docs show lists longer than about twenty in a collapsed `<details>`.
- **`checks:`.** Role-level list of `{name?, when, level: info|warning|error, message}`. `when` sees options and `host`/`lab` facts (**planning-time only; it cannot test remote state**; run-time safeguards remain `validate:`, `unless:` and trigger `check`s). `error` stops that host's build with a message naming role and file; `info` and `warning` become **notes** on the build, shown through `bastet.ui.out` in `bastet run` and the check workflow, once per host and message. `info` = intentionally delegated or informational; `warning` = probably unintended; `error` = cannot be done.
- **`sections:`.** `sections: [{name?, when?, packages, users, files, systemd, commands}]`. A section's `when` is ANDed with each entry's own `when`; a section without `when` only organises. Several sections and top-level lists coexist; order is still by block then listing; nesting is refused; no new execution semantics.
- **`each:`.** On any entry (packages, users, files, systemd, commands, also inside a section): `each: <option name>` where the option is a list or a map. One entry is built per item; `{{ item }}` (and `{{ key }}` for a map) are available in the entry's values and `when:`; the section's and the entry's `when:` are evaluated per item. Only an option name is allowed (not an expression) so the role can be checked when it is read, and `item`/`key` are accepted as names only inside an entry that has `each:`. An unset or empty option builds nothing. Two items that build the same file path, unit or user are refused with the item numbers. Errors name role, file, entry and item number. There is deliberately no index variable: entries are identified by what they build (path, unit, user), so reordering the list changes nothing on the host; only the order they are applied in. An item removed or renamed leaves its old file behind (no deletion yet); the docs say so.
- **Where an option's value came from (`applied`).** `checks:` (and `when:` in checks) can use `applied.origin.<option>`: the label of the note that set the option (`lab`, `group <name>`, `type <name>`, `host <name>`, `OS default (<os>)`), empty when unset. Backed by `Applied.origins`, which `resolve` already records.
- **`files` entry triggers.** Existing `restart:` / `reload:` plus `daemon_reload: true` (unit definitions, Quadlet files) and `on_change: [{name, run}]` (a command run once after the host's fixes when the entry changed something). Triggers only run for entries that changed, are de-duplicated, `daemon-reload` first and then the rest in listing order. `restart:`/`reload:` act only when the unit is running, so they never start a stopped, disabled or failed service.

## The `time` role

`src/bastet/data/roles/time/time role.md`, no `os:` limit, `starter: {timezone: UTC, ntp: true}`, no `accounts:`.

- **Options (flat, upstream names):** `timezone` (string, `choices_from: time zones.txt`); `ntp` (bool, no default); `ntp_servers` → `NTP`, `ntp_fallback_servers` → `FallbackNTP`, `root_distance_max_sec`, `poll_interval_min_sec`, `poll_interval_max_sec`, `connection_retry_sec`, `save_interval_sec` (all seven keys of `timesyncd.conf(5)`; each `key:`, `section: Time`, `single_line`, `requires: {ntp: true}`). The implementer re-checks the key list against `man timesyncd.conf` and the ArchWiki page the owner supplied (untracked; never commit it).
- **Entries:** `systemd` `kind: time` with `timezone` only (never `ntp` or `rtc_local`), everywhere. A `sections:` group `when: host.arch_like and not host.container`: `files` `edit: ini` on `/etc/systemd/timesyncd.conf.d/bastet.conf` with `when: ntp` and `restart: [systemd-timesyncd.service]`; `systemd` `kind: unit` `systemd-timesyncd.service` with `enabled: "{{ ntp }}"`, `state: "{{ 'up' if ntp else 'down' }}"`, `when: ntp is not none`. So `ntp: false` writes no settings, touches no files and restarts nothing.
- **Checks:** `warning` when `ntp` is true and `applied.origin.ntp` starts with `lab` ("time sync is only implemented for Arch; setting `ntp` lab-wide makes every Debian/Proxmox host fail. Set `ntp` on an Arch group instead, or add an `overrides:` entry (`when: not host.arch_like`, `ntp: null`) to the lab note, or write `ntp: null` in the Debian/Proxmox group's note."); `info` when container and `ntp is not none` ("time sync on a container is provided by its host; only the time zone is applied"); `error` when not container, not `arch_like` and `ntp` is true ("time sync is implemented for systemd-timesyncd on Arch only; chrony for Debian/Proxmox is planned"); `info` when not container, not `arch_like` and `ntp` is false ("`ntp: false` is not applied on this system yet; nothing changed").
- **Docs (role body):** Supported systems (Arch: systemd-timesyncd; Debian/Proxmox: chrony planned, one item, not built, with a visible "needs expanding" note; LXC: delegated); the time zone list is a snapshot refreshed at version bumps; the reload classes in plain words (changing the drop-in restarts the service, no daemon-reload); the stock servers are `FallbackNTP` and stay when `NTP=` is set; `ntp: false` leaves the drop-in in place; the SD-card example `PollIntervalMinSec=1d` with `SaveIntervalSec=infinity`.
- **Behaviour tests:** no options emits nothing on Arch, Debian and LXC; `timezone` only gives one `TimeSettings(timezone)`; an invalid zone is refused; `ntp: true` gives the drop-in, the restart trigger and the unit enabled/up and **no daemon-reload**; an unchanged drop-in gives no trigger; `ntp: false` gives the unit disabled/down only; a key without `ntp: true` is refused; Debian with `ntp: true` gives the error and with `ntp: false` only the info (zone applied); LXC gives the info plus the zone only; the role builds with no other role applied.

## Version-bump workflow

There is none today. Add `scripts/version-bump X.Y.Z` (repo tooling, Python like `scripts/gen_roles_doc.py`): writes the version in `pyproject.toml`; reads `timedatectl list-timezones`, strips, sorts, refuses empty output, duplicates or names `ZoneInfo` cannot load; rewrites `src/bastet/data/roles/time/time zones.txt` only if the zone lines changed; updates a first-line stamp `# refreshed for bastet X.Y.Z` (the only line that changes when the list is unchanged); prints added and removed zones for review; runs `scripts/gen_roles_doc.py`. `--check` validates without writing. A test fails when the stamp differs from the version in `pyproject.toml`, so a bump without a refresh is caught. Documented in the roadmap's versioning line and a short note in `docs/`.

## Review Focus

- Existing roles keep their behaviour except the intended restart-only-if-running fix (A-10) and the container notes (A-8); the existing role tests run unchanged.
- `requires`/`conflicts` use pre-default values; `false`/`0`/`""`/`[]` count as set.
- `checks:` and entry skips never fail silently; `info` is not shown as a warning; errors name role and file.
- Sections combine conditions with AND and never reorder blocks.
- A trigger never starts a stopped unit, never fires for an unchanged or failed entry, and `daemon-reload` is only used for unit definitions.
- `ntp: false` writes nothing and leaves the drop-in alone.
- `each:` builds nothing for an unset or empty option, refuses duplicate results, and `item`/`key` are rejected outside an `each:` entry.
- A lab note with `ntp: true` and `overrides: [{when: "not host.arch_like", ntp: null}]` configures Arch hosts and shows no sync message at all on Debian/Proxmox hosts (the value is blank, so unset; the time zone still applies).
- Setting `ntp` in the lab note shows the lab-wide warning and a Debian host in that lab with `ntp: true` still gets its error, unless its group or host note sets `ntp: null`, which gives it the time zone and no sync message.
- The version-bump script writes nothing when the zone lines are unchanged apart from the stamp.

---

## File structure

| File | Responsibility |
|---|---|
| `src/bastet/roles/contract.py`, `declarative.py`, `entries.py`, `expr.py` | `requires`/`conflicts`, `choices_from`, `checks`, `sections`, file triggers, `host.<fact>` check |
| `src/bastet/engine/systemd.py`, `run.py`, `model.py` | restart/reload only if running, clearer missing-unit error, build notes |
| `src/bastet/data/roles/time/time role.md`, `time zones.txt` | The role and its list |
| `src/bastet/data/roles/systemd/role.yml`, `roles/builtin.py` | Remove the moved options and the time branch |
| `scripts/version-bump`, a note in `docs/` | Version-bump workflow |
| `src/bastet/data/docs/writing_roles.md`, `docs/roles.md`, `docs/ROADMAP.md`, `scripts/gen_roles_doc.py`, `roles/pages.py` | Documentation |
| new tests in `tests/roles/` (unique names): `test_contract_pinning.py`, `test_option_requires.py`, `test_choices_from.py`, `test_role_checks.py`, `test_role_sections.py`, `test_option_clear.py`, `test_role_overrides.py`, `test_role_each.py`, `test_file_triggers.py`, `test_time_role.py`, `test_time_zone_list.py` | |

## Tasks (order and dependencies)

Every task reads the plan sections it names and the Global Constraints. Order: 1, 2a, 2b, 2c, 3, 4, 5, 6, 7, 8, 9, 10. Tasks 2a to 8 are independent of each other after Task 1 (Task 6 builds on Task 5's entry plumbing, so do 5 before 6; 2c builds on 2b's null handling). Task 9 needs 2a to 8. Task 10 is last. Each task is TDD: failing tests first, see them fail for the right reason, then implement, then document in `writing_roles.md`.

### Task 1: Pin existing behaviour

`test_contract_pinning.py`: `false`/`0`/`""`/`[]` through `when:`; `edit: ini` creating a new file in a new directory; trigger de-duplication, ordering, no trigger when unchanged or failed; the `time` entries build with no other role; a bad role stops before any host command (audit A-2, A-13, A-15, A-18). Fix what the tests reveal, each fix a failing test first.

### Task 2a: `requires` / `conflicts`

Option keys as specified in "The final contract additions". Tests in `test_option_requires.py`, implement in `contract.py` (`OPTION_KEYS`, `Option`, `_option`, the check in `check_values` on pre-default values), document.

### Task 2b: Clearing an inherited option

Tests in `test_option_clear.py`: null at host/group/type clears a lab value only after the merge (a host `false` beats a group `null`, a group `null` beats a lab `true`, the order of notes never matters, same-rank `null` vs `true` clashes); null inside a map/object field; null with nothing inherited is a no-op; required options and defaults behave (a cleared option falls back to its default); the starter and `bastet add role` output contain no bare keys. Implement in `resolve.py` / `contract.check_values`, document.

### Task 2c: `overrides:` in role notes

Tests in `test_role_overrides.py`: a matching entry replaces the note's own value; a non-matching one does nothing; listing order decides between two matching entries; a higher-ranked note beats a lab override; `null` values work after the merge (Task 2b); `when` using an option name, a bad fact, bad syntax, an unknown option or a wrong value type is refused when the note is read, naming file and key; the origin label says override. Implement in `resolve.py` / `contract.py`, document with the lab-wide `ntp` example.

### Task 3: `choices_from`

Tests in `test_choices_from.py`, implement in `contract.py` (`OPTION_KEYS`, `Option`, `check_value`), docs rendering (long lists collapsed in `scripts/gen_roles_doc.py` and `roles/pages.py`).

### Task 4: Notes and `checks:`

The build notes channel, `info|warning|error`, display in run and check, de-duplication per host and message, the `applied.origin` fact, container drops (A-8) become notes, `host.<fact>` parse check. Tests in `test_role_checks.py`. If the display hook is large, **stop and report**.

### Task 5: `sections:`

Tests in `test_role_sections.py`, implement, document with the Arch example.

### Task 6: `each:`

Tests in `test_role_each.py` (list, map, empty, unset, duplicates refused, `item` outside `each:` refused, `when:` per item, inside a section, secrets), implement, document with a caddy-sites example.

### Task 7: File triggers and restart semantics

`daemon_reload`, `on_change`, **restart/reload only if running** (a failed unit is left alone too), a clearer missing-unit error. Tests in `test_file_triggers.py`. Document the four reload classes in `writing_roles.md`.

### Task 8: Version-bump script and zone list tests

`scripts/version-bump`, `time zones.txt` handling and `test_time_zone_list.py`, as in "Version-bump workflow". The list file itself is made once from `timedatectl list-timezones` (a throwaway command from `$CLAUDE_JOB_DIR/tmp`, nothing committed except the file).

### Task 9: The `time` role

The role as in "The `time` role", removing the time options from the `systemd` role (`role.yml`, `builtin.py`), tests in `test_time_role.py` (move the old time tests, say which in the report), regenerate docs.

### Task 10: Documentation and roadmap

`writing_roles.md` (every new key, `is none` guidance, the reload classes, checks versus runtime protection, `each:`, `applied`, `overrides:`, clearing with null), generated docs, `docs/ROADMAP.md` (tick `time`, next is `base`, log deferred items with reasons, the versioning line), `scripts/privacy-check`, `ruff`.

Final: opus review, one fix wave, scoped re-review, the owner runs `uv run pytest -q` and says when it passed, then ask about merging.

## Owner decisions resolved (2026-10-12)

- **D-1:** include loops (`each:`, Task 6).
- **D-2:** zone list stamp: yes.
- **D-3:** restart/reload only act on a running unit; failed units are left to a `Unit` entry (decision 9).
- **Added:** the lab-wide warning for `ntp` (decision 12), clearing with `null` (decision 10) and `overrides:` (decision 11).

## Deferred (with reasons)

File removal (destructive, needs its own design; the roadmap says deferred); `needs`/`uses`/cross-role contributions (roadmap: can wait, each app role drops its own file); user-scope systemd units (no near role needs them); `supports:` (`checks:` covers today's need); a `running:` unit shortcut (the expression is small); chrony and Debian/Proxmox sync (owner: not yet); `edit: env` and `edit: sshd` (files-block work for their roles); more host facts for storage (added when ZFS is designed); `api`/`fetch`/`git` blocks (blocks, not contract).
