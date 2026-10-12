# The `time` role: time zone and time sync as a Markdown role — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. In this repo, the `bastet-run-plan` skill supplies the Bastet-specific parts; the `bastet-new-role` skill holds the role checklist.

**Goal:** time zone, hardware clock and time sync with systemd-timesyncd become a straight-Markdown role, `time`, that calls the `systemd` and `files` blocks. **Supported systems (owner, 2026-10-11): Arch Linux supports systemd-timesyncd only; chrony is for Proxmox only, and Proxmox is not built yet.** It is the first role to prove the contract on real work (VPS apps, step 2). The time options leave the Python `systemd` role.

**Architecture:** `src/bastet/data/roles/time/time role.md` with `os: [arch]`, options `timezone`, `rtc_local` and one grouped option `ntp_settings` with fields `service` (`timesyncd`|`off`, no default), `servers`, `fallback_servers` and the other timesyncd keys (decision 6). Entries: `files` (a timesyncd drop-in) and `systemd` (`kind: time` for zone, RTC and the sync switch; `kind: unit` for `systemd-timesyncd.service`). No `packages:` entry: timesyncd ships in Arch's `systemd` package. Every entry has `when:` so that no options set emits nothing and a container only gets the time zone.

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
2. **`systemd-timesync` account** moves from the `systemd` role's `accounts:` to the `time` role (already agreed in the account-defaults plan).
3. **Not an OS default.** Arch hosts do not get `time` automatically (a default would have to change nothing anyway); you add it to a lab, group or host note.
4. **One grouped option replaces `ntp`, `ntp_service`, `ntp_servers` and `fallback_ntp_servers`:** `ntp_settings: {service: timesyncd|off, servers: [...], fallback_servers: [...], ...}`. `service` has no default (unset leaves sync alone; `off` stops and disables sync). `chrony` is not an accepted value yet (it is documented as planned for Proxmox). Every other `ntp_settings` field `requires: {service: timesyncd}`; a mismatch is refused by the new `requires` / `conflicts` option keys (Task 1). The old `keep` mode goes: `timesyncd` enables the service, `off` disables sync.

5. **Supported systems, written into the role's body as a "Supported systems" section and `os: [arch]` in the frontmatter:** Arch Linux supports systemd-timesyncd only. chrony is for Proxmox only and is not built yet; Debian-like handling (the `systemd-timesyncd` package, `chrony/sources.d`) from the old code is dropped from this role and recorded in the roadmap. `servers` is optional: unset, timesyncd uses the distro's stock servers (Arch's confirmed by the owner); for timesyncd they take the place of the stock (fallback) servers (see 6).
6. **All of timesyncd's settings are exposed**, under their upstream names (rule 2 of `bastet-new-role`), written to `/etc/systemd/timesyncd.conf.d/bastet.conf` section `[Time]`. `timesyncd.conf(5)` has seven keys: `NTP` (`servers`), `FallbackNTP` (`fallback_servers`), `RootDistanceMaxSec`, `PollIntervalMinSec`, `PollIntervalMaxSec`, `ConnectionRetrySec`, `SaveIntervalSec`. The implementer re-checks the list against `man timesyncd.conf` on the dev machine and the ArchWiki page the owner supplied (it stays untracked; never commit it). Only the keys that are set are written. Facts for the docs (ArchWiki): the stock servers are the distro's pool, built in as `FallbackNTP`; per-interface servers (networkd, DHCP) come first, then `NTP=`, and `FallbackNTP=` is used only if none were found, so setting `servers` stops the stock servers being used; the state file `/var/lib/systemd/timesync/clock` is written on every sync and every 60 s and can't be moved, so for SD cards or read-only roots the docs example is `PollIntervalMinSec=1d` with `SaveIntervalSec=infinity`.
7. **chrony is documented, not built:** the role's body says chrony is for Proxmox only and is not implemented yet, with a visible "needs expanding" note. The roadmap's "Planned additions" gets a row: chrony (all settings, drop-in or block edit per OS, Proxmox) and Debian-like timesyncd/chrony handling.
8. **Starter and drop-ins.** The role note carries `starter: {timezone: UTC}`, so `bastet add role time` writes a time zone into the new note (the user then changes it). A `starter:` is only copied into a new note; it is not a default, so a host with the role but no `timezone` still changes nothing. timesyncd always gets `/etc/systemd/timesyncd.conf.d/bastet.conf`, never an edit of `timesyncd.conf`.

## Review Focus

- With no options set, the role emits nothing on any host type (a test builds it empty on Arch and an LXC).
- On an LXC, only the time zone is applied: no packages, units, `ntp`, `rtc_local` or NTP files.
- Mismatched settings (any `ntp_settings` field other than `service` without `service: timesyncd`) are refused with an error naming both options and the file. Nested unset fields (`ntp_settings.service` when only `servers` is given) evaluate cleanly in `when:`. `service: chrony` is refused as not a valid choice.
- A change to the drop-in restarts `systemd-timesyncd.service`; `service: off` stops and disables it.
- `service: off` yields the `time` entry with `ntp: false` and installs nothing.
- No option value with a line break reaches a config file (`single_line: true` on the server options, or each server as a list item).
- `docs/roles.md` is current; the `systemd` role no longer lists the moved options; the old tests for them moved to the role, not deleted.

---

## File structure

| File | Responsibility |
|---|---|
| Create `src/bastet/data/roles/time/time role.md` | The role: frontmatter (options, `accounts: [systemd-timesync]`, `examples`, entries) and docs body with `## Changes` |
| Modify `src/bastet/data/roles/systemd/role.yml` | Remove the six moved options and `systemd-timesync` from `accounts` |
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

### Task 2: The `time` role note and its tests

- [ ] **Step 1: Failing tests** in `tests/roles/test_time_role.py` (see the Review Focus). Cases: empty options emit nothing (Arch, LXC); `timezone` only gives one `TimeSettings(timezone)`; `service: off` gives `TimeSettings(ntp=False)` and the unit disabled and down, no files; `service: timesyncd` with servers and the other keys gives the drop-in `/etc/systemd/timesyncd.conf.d/bastet.conf` (`[Time]`, only the keys set), a restart of `systemd-timesyncd.service`, the unit enabled and up; LXC with `ntp_settings` and `rtc_local` gives only the time zone; the mismatches above are refused; `service: chrony` is refused; `parse_role` accepts the note, `os` is `['arch']` and `accounts` is `['systemd-timesync']`.
- [ ] **Step 2: See them fail** for the right reason (role not found).
- [ ] **Step 3: Write the role note,** using `requires`/`conflicts` for the option rules. Use the frontmatter keys from `bastet-new-role`. The old `_systemd` time branch in `builtin.py` is the behaviour reference. Express the cases as `when:` conditions. The body documents the role and has a "Supported systems" section (Arch: systemd-timesyncd only; chrony: Proxmox only, not built yet, needs expanding). The only contract change is Task 1; for anything else **stop and report** (an owner decision).
- [ ] **Step 4: Time zone list in the role body.** Plain Markdown, no script: the note's body (its documentation) carries a collapsible `<details><summary>Valid time zones</summary>` section listing the IANA zone names, one per line in a code block. The implementer produces the list once with a throwaway command (for example `timedatectl list-timezones`, run from `$CLAUDE_JOB_DIR/tmp`, nothing committed) and pastes it into the note. It is a snapshot; the section says so and says the host's `timedatectl list-timezones` is the authority. The `timezone` option is not validated against the list (`timedatectl` refuses an unknown name at run time). A test (`tests/roles/test_time_zone_list.py`) checks only the shape: the `<details>` block exists, the list is non-empty and sorted, and every name loads with `ZoneInfo` (skipped if the machine has no tz data). Check that `scripts/gen_roles_doc.py`, `bastet doctor` and the vault note viewer accept the `<details>` block; if the generated `docs/roles.md` copies the body, keep the list out of it.
- [ ] **Step 5: Tests pass** (`uv run pytest tests/roles -q`), then commit by name.

### Task 3: Take the time options out of the `systemd` role

- [ ] **Step 1: Failing tests:** the `systemd` role refuses `timezone` etc. as unknown options (message names the key); its built batch for hostname, locale, services and drop-ins is unchanged.
- [ ] **Step 2:** remove the options and the time branch of `_systemd`, move `systemd-timesync` to the `time` role's `accounts:`, move the old time tests to `test_time_role.py` (or delete them where the new test covers the case; say which in the report).
- [ ] **Step 3:** `uv run python scripts/gen_roles_doc.py`; run `tests/roles` and any test file the grep named; `ruff check src tests`; commit by name.

### Task 4: Docs and roadmap

- [ ] **Step 1:** `docs/ROADMAP.md`: tick `time` in the roles table and in VPS apps step 2, set "Next step" to `base`, remove the `time` row from "Planned additions", add the chrony row from decision 7, and record anything the work revealed (for example a missing contract feature; the LXC `time` check on a real host stays in "Docs and tooling").
- [ ] **Step 2:** `scripts/privacy-check` clean; commit by name.

## Final steps

Final review (opus), one fix wave, the owner runs `uv run pytest -q` and says when it passed; only then ask about merging.
