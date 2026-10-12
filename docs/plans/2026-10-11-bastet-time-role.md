# The `time` role: time zone and time sync as a Markdown role — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. In this repo, the `bastet-run-plan` skill supplies the Bastet-specific parts; the `bastet-new-role` skill holds the role checklist.

**Goal:** time zone and time sync become a straight-Markdown role, `time`, that calls the `systemd` and `files` blocks. **The role covers every system for the time zone, and picks the sync daemon by OS (owner, 2026-10-11): Arch uses systemd-timesyncd (built); Proxmox/Debian will use chrony (not built yet).** It is the first role to prove the contract on real work (VPS apps, step 2). The time options leave the Python `systemd` role.

**Architecture:** `src/bastet/data/roles/time/time role.md` (no `os:` limit) with options `timezone` and one grouped option `ntp_settings` with fields `enabled` (bool, no default), `servers`, `fallback_servers` and the other timesyncd keys (decision 6). Entries: `systemd` `kind: time` (time zone only; every system), and for Arch (`when: host.arch_like`, not on containers) a `files` timesyncd drop-in and a `systemd` `kind: unit` for `systemd-timesyncd.service` (enabled and up when `enabled: true`, disabled and down when `false`, which is what `timedatectl set-ntp` does anyway). No `packages:` entry: timesyncd ships in Arch's `systemd` package. Every entry has `when:`, so no options set emits nothing. Nothing is skipped silently (decision 9): the role's `warnings:` say so when time sync was asked for on a system or host type where it is not applied.

**Tech Stack:** Python ≥3.12, pydantic, PyYAML, Jinja2 (the existing sandbox), pytest, ruff.

**Spec:** `docs/specs/2026-10-10-bastet-roles-architecture-design.md`; user docs `src/bastet/data/docs/writing_roles.md`; models `roles/pacman/pacman role.md`, `roles/apt/apt role.md`. The behaviour to keep is the time part of `_systemd` in `src/bastet/roles/builtin.py`.

## Global Constraints

- **Unit tests** never touch the real inventory, `~/.config/bastet`, `~/.local/share/bastet`, `~/.ssh`, the real `~/.cache` or `$XDG_RUNTIME_DIR`; no network; `tmp_path` only; placeholder data only (10.1.x.x addresses, host names like pve1/media01).
- **Test file basenames unique across `tests/`** (no `__init__.py`).
- Every message goes through `bastet.ui.out`; no `typer.echo` in `src/`; no "spec §"/"Task N" references in `src/`.
- The version is written only in `pyproject.toml`.
- `docs/roles.md` is generated; regenerate with `uv run python scripts/gen_roles_doc.py` (a repo test checks it).
- `ruff check src tests` and `scripts/privacy-check` must pass before the final commit.
- New `edit:` types, systemd kinds or block features are added only if this role truly needs them, with their own tests, and written in the roadmap. Expectation: none are needed.
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Decisions for the owner (defaults used if not changed)

1. **Move, not copy.** The time options (`timezone`, `ntp`, `ntp_service`, `ntp_servers`, `fallback_ntp_servers`, `rtc_local`) are removed from the `systemd` role's `role.yml` (the user-facing surface only; the `systemd` block and its `kind: time` entry, which is what calls `timedatectl`, are unchanged) (which keeps hostname, locale, keymap, services, drop-ins). A note that still sets them gets the normal "unknown option" error naming the key. Cost if wrong: a one-time edit of any note using them. The roadmap says the time part "moves out of the `systemd` role".
2. **`systemd-timesync` account belongs to the `time` role's `accounts:`** (owner, 2026-10-11, as in the account-defaults plan). Consequence, documented in three places (the `users` role's description, the `systemd` role's description and the `time` role's body): `time` is not an OS default, so an Arch host without the `time` role lists `systemd-timesync` in the unaccounted-users report. The note tells how to fix it: apply the `time` role to the host, or list the account in the `users` role's `allowed`.
3. **Not an OS default.** Arch hosts do not get `time` automatically (a default would have to change nothing anyway); you add it to a lab, group or host note.
4. **One grouped option replaces `ntp`, `ntp_service`, `ntp_servers` and `fallback_ntp_servers`:** `ntp_settings: {enabled: true|false, servers: [...], fallback_servers: [...], ...}`. There is no daemon choice: the role is opinionated and the OS decides (owner, 2026-10-11): Arch uses systemd-timesyncd; Proxmox/Debian will use chrony, not built yet. `enabled` has no default (unset leaves sync alone; `false` stops and disables sync; `true` enables and starts the daemon through its systemd unit). On a container the sync entries are skipped with a warning (an LXC gets its time from the node). Every other `ntp_settings` field `requires: {enabled: true}`; a mismatch is refused by the new `requires` / `conflicts` option keys (Task 1). The old `ntp_service` choice and its `keep` mode go.

5. **Supported systems, written into the role's body as a "Supported systems" section:** the time zone works on every system. Time sync: Arch Linux uses systemd-timesyncd only. Proxmox/Debian will use chrony, one item, not built yet; there is no option to choose the daemon, the OS decides. On a Debian-like host `ntp_settings` is not applied and a warning says so. The old Debian handling in `_systemd` (the `systemd-timesyncd` package, `chrony/sources.d`) is dropped here and recorded in the roadmap. `servers` is optional: unset, timesyncd uses the distro's stock servers (Arch's confirmed by the owner); set, they are tried first and the stock servers stay in place as the fallback (see 6).
6. **All of timesyncd's settings are exposed**, under their upstream names (rule 2 of `bastet-new-role`), written to `/etc/systemd/timesyncd.conf.d/bastet.conf` section `[Time]`. `timesyncd.conf(5)` has seven keys: `NTP` (`servers`), `FallbackNTP` (`fallback_servers`), `RootDistanceMaxSec`, `PollIntervalMinSec`, `PollIntervalMaxSec`, `ConnectionRetrySec`, `SaveIntervalSec`. The implementer re-checks the list against `man timesyncd.conf` on the dev machine and the ArchWiki page the owner supplied (it stays untracked; never commit it). Only the keys that are set are written. Facts for the docs (ArchWiki): the stock servers are the distro's pool, built in as `FallbackNTP`; per-interface servers (networkd, DHCP) come first, then `NTP=`, and `FallbackNTP=` is used only if none were found, so a drop-in that sets `NTP=` replaces nothing: the stock servers stay as `FallbackNTP` and are used only when none of the `NTP=` ones answer (set `fallback_servers` to change them); the state file `/var/lib/systemd/timesync/clock` is written on every sync and every 60 s and can't be moved, so for SD cards or read-only roots the docs example is `PollIntervalMinSec=1d` with `SaveIntervalSec=infinity`.
7. **chrony is documented, not built:** the role's body says chrony is for Proxmox/Debian and is not implemented yet, with a visible "needs expanding" note. The roadmap's "Planned additions" gets a row: chrony (all settings, drop-in or block edit per OS) for Proxmox/Debian.
8. **Starter and drop-ins.** The role note carries `starter: {timezone: UTC, ntp_settings: {enabled: true}}`, so `bastet add role time` writes them into the new note (the user then changes the zone). A `starter:` is only copied into a new note; it is not a default, so a host with the role but no options still changes nothing. timesyncd always gets `/etc/systemd/timesyncd.conf.d/bastet.conf`, never an edit of `timesyncd.conf`.
9. **Nothing is skipped without a warning** (owner guideline, 2026-10-11), unless the setting itself says skip (`enabled: false` is a request, not a skip). This needs a small contract addition, Task 2: a role-level `warnings:` list of `{when: <expression>, message: <text>}`, evaluated when the role is built for a host and shown through `bastet.ui.out`.
10. **`rtc_local` is dropped.** It only exists for dual-booting with Windows (Windows keeps the hardware clock in local time, Linux in UTC); the owner has no such system. Cost: none now; a later role option if a host needs it. The `systemd` block's `kind: time` keeps the field.
11. **Why Arch has the `systemd` role by default:** only for its accounts (the `systemd-*` system users every Arch install has), not for any setting; with no options it changes nothing. Task 4 writes that into `src/bastet/data/oses/arch.yml` (comment), the `systemd` role's description and the OS-defaults paragraph of `writing_roles.md`.

## Review Focus

- With no options set, the role emits nothing on any host type (a test builds it empty on Arch, Debian and an LXC).
- On an LXC, only the time zone is applied: no units or NTP files (and a warning).
- Mismatched settings (any `ntp_settings` field other than `enabled` without `enabled: true`) are refused with an error naming both options and the file. Nested unset fields (`ntp_settings.enabled` when only `servers` is given) evaluate cleanly in `when:`.
- On a Debian-like host or an LXC, asking for sync (`ntp_settings` set) applies nothing and shows the warning; the time zone still applies. A role with no `warnings` entry matching shows nothing.
- A change to the drop-in restarts `systemd-timesyncd.service`; `enabled: false` stops and disables it.
- No `TimeSettings` the role builds ever carries `ntp`; sync is only ever the unit.
- No option value with a line break reaches a config file (`single_line: true` on the server options, or each server as a list item).
- `docs/roles.md` is current; the `systemd` role no longer lists the moved options; the old tests for them moved to the role, not deleted.

---

## File structure

| File | Responsibility |
|---|---|
| Create `src/bastet/data/roles/time/time role.md` | The role: frontmatter (options, `starter`, `examples`, `warnings`, entries) and docs body with `## Changes` |
| Modify `src/bastet/data/roles/systemd/role.yml` | Remove the moved options (six, including `rtc_local`); description says why Arch has it by default |
| Modify `src/bastet/roles/builtin.py` | `_systemd` drops the time/NTP code; keeps hostname, locale, services, drop-ins |
| Create `tests/roles/test_time_zone_list.py` | Checks the shape of the collapsible time zone list in the role body |
| Create `tests/roles/test_time_role.py` | Entries per case, neutrality, container, refused mismatches, `when:` skips |
| Modify existing tests that use the moved options (`grep -rn "ntp\|timezone\|rtc_local" tests`) | Move their cases to the role test or drop the moved options |
| Modify `docs/roles.md` (generated), `docs/ROADMAP.md` | Tick `time`, update VPS apps step 2 and "Planned additions" |

## Tasks

### Task 1: `requires` and `conflicts` on options (contract change, owner-approved 2026-10-11)

- [ ] **Step 1: Failing tests** in `tests/roles/test_option_requires.py`. Syntax: `requires: [other]` (if this option is set, `other` must be set), `requires: {other: value-or-list}` (and `other` must have one of those values), `conflicts: [other]` (can't both be set). Inside an `object` option the names are sibling fields; at top level, other top-level options. Cases: each form passes when satisfied and is refused otherwise; an unset option checks nothing; an option set to its default counts as set only if the note set it; the error names both options (with the parent for fields) and the file; `parse_role` refuses a `requires`/`conflicts` that names an unknown option or field, or has the wrong shape.
- [ ] **Step 2: See them fail**, then implement in `src/bastet/roles/contract.py` (`OPTION_KEYS`, `Option`, `_option`, and the check in `check_values`). Update `src/bastet/data/docs/writing_roles.md` (an "Options that need or exclude each other" section with the example) and the generated docs if they list option keys.
- [ ] **Step 3:** `uv run pytest tests/roles -q`, `ruff check src tests`, commit by name. ROADMAP: note the feature; `needs`/`uses` (role dependencies) stay reserved.

### Task 2: `warnings:` on roles (contract change, owner-approved 2026-10-11)

- [ ] **Step 1: Failing tests** in `tests/roles/test_role_warnings.py`: a role-level `warnings:` list of `{when, message}` (both required; `when` is an expression over options and `host`/`lab` facts, `message` may use `{{ }}`); building the role for a host returns the messages whose `when` is true; none when false; a bad entry or unknown name is refused when the role is read, naming file and key; the messages reach the user through `bastet.ui.out` in `bastet run` / check output (find where build results are shown and add the smallest hook; no new output channel).
- [ ] **Step 2: See them fail**, implement in `src/bastet/roles/contract.py` (`ROLE_NOTE_KEYS`, parse), `declarative.py` / `expr.py` as needed, and the display hook; document in `writing_roles.md` (a short "Warning instead of skipping silently" section: the guideline, the example).
- [ ] **Step 3:** `uv run pytest tests/roles -q`, `ruff check src tests`, commit by name. If the display hook turns out to be large, **stop and report**.

### Task 3: The `time` role note and its tests

- [ ] **Step 1: Failing tests** in `tests/roles/test_time_role.py` (see the Review Focus). Cases: empty options emit nothing (Arch, Debian, LXC); `timezone` only gives one `TimeSettings(timezone)`; `enabled: false` gives the unit disabled and down, no `TimeSettings(ntp=...)` and no files; `enabled: true` with servers and the other keys gives the drop-in `/etc/systemd/timesyncd.conf.d/bastet.conf` (`[Time]`, only the keys set), a restart of `systemd-timesyncd.service`, the unit enabled and up; a Debian-like host and an LXC with `ntp_settings` get only the time zone plus the warning from `warnings:`; the mismatches above are refused; `parse_role` accepts the note and the `starter`; `accounts` is `['systemd-timesync']`.
- [ ] **Step 2: See them fail** for the right reason (role not found).
- [ ] **Step 3: Write the role note,** using `requires`/`conflicts` for the option rules. Use the frontmatter keys from `bastet-new-role`. The old `_systemd` time branch in `builtin.py` is the behaviour reference. Express the cases as `when:` conditions. The body documents the role and has a "Supported systems" section (Arch: systemd-timesyncd only; chrony: Proxmox only, not built yet, needs expanding). The only contract change is Task 1; for anything else **stop and report** (an owner decision).
- [ ] **Step 4: Time zone list in the role body.** Plain Markdown, no script: the note's body (its documentation) carries a collapsible `<details><summary>Valid time zones</summary>` section listing the IANA zone names, one per line in a code block. The implementer produces the list once with a throwaway command (for example `timedatectl list-timezones`, run from `$CLAUDE_JOB_DIR/tmp`, nothing committed) and pastes it into the note. It is a snapshot; the section says so and says the host's `timedatectl list-timezones` is the authority. The `timezone` option is not validated against the list (`timedatectl` refuses an unknown name at run time). A test (`tests/roles/test_time_zone_list.py`) checks only the shape: the `<details>` block exists, the list is non-empty and sorted, and every name loads with `ZoneInfo` (skipped if the machine has no tz data). Check that `scripts/gen_roles_doc.py`, `bastet doctor` and the vault note viewer accept the `<details>` block; if the generated `docs/roles.md` copies the body, keep the list out of it.
- [ ] **Step 5: Tests pass** (`uv run pytest tests/roles -q`), then commit by name.

### Task 4: Take the time options out of the `systemd` role

- [ ] **Step 1: Failing tests:** the `systemd` role refuses `timezone` etc. as unknown options (message names the key); its built batch for hostname, locale, services and drop-ins is unchanged.
- [ ] **Step 2:** remove the options (including `rtc_local`) and the time branch of `_systemd`, remove `systemd-timesync` from its `accounts:` (it moves to the `time` role), add the unaccounted-user note (decision 2) to the `systemd` and `users` role descriptions, add the "why Arch has this role by default" text (decision 11) to `arch.yml` as a comment, the role description and `writing_roles.md`, move the old time tests to `test_time_role.py` (or delete them where the new test covers the case; say which in the report).
- [ ] **Step 3:** `uv run python scripts/gen_roles_doc.py`; run `tests/roles` and any test file the grep named; `ruff check src tests`; commit by name.

### Task 5: Docs and roadmap

- [ ] **Step 1:** `docs/ROADMAP.md`: tick `time` in the roles table and in VPS apps step 2, set "Next step" to `base`, remove the `time` row from "Planned additions", add the chrony row from decision 7, and record anything the work revealed (for example a missing contract feature; the LXC `time` check on a real host stays in "Docs and tooling").
- [ ] **Step 2:** `scripts/privacy-check` clean; commit by name.

## Final steps

Final review (opus), one fix wave, the owner runs `uv run pytest -q` and says when it passed; only then ask about merging.
