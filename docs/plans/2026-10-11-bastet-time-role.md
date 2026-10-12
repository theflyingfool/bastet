# The `time` role: time zone and time sync as a Markdown role — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. In this repo, the `bastet-run-plan` skill supplies the Bastet-specific parts; the `bastet-new-role` skill holds the role checklist.

**Goal:** time zone, hardware clock and time sync (systemd-timesyncd or chrony) become a straight-Markdown role, `time`, that calls the `packages`, `files` and `systemd` blocks. It is the first role to prove the contract on real work (VPS apps, step 2). The time options leave the Python `systemd` role.

**Architecture:** `src/bastet/data/roles/time/time role.md` with options `timezone`, `rtc_local` and one grouped option `ntp_settings` with fields `service` (`timesyncd`|`chrony`|`off`, no default), `servers` and `fallback_servers`. Entries: `packages` (chrony), `files` (a timesyncd drop-in; a chrony `block` in `/etc/chrony.conf`; nothing Debian-specific yet), `systemd` (`kind: time` for zone, RTC and the "keep" sync switch; `kind: unit` for the chosen and the other service). Every entry has `when:` so that no options set emits nothing and a container only gets the time zone.

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
4. **One grouped option replaces `ntp`, `ntp_service`, `ntp_servers` and `fallback_ntp_servers`:** `ntp_settings: {service: timesyncd|chrony|off, servers: [...], fallback_servers: [...]}`. `service` has no default (unset leaves sync alone; `off` stops and disables sync). `servers` and `fallback_servers` only take effect with a daemon chosen, and `fallback_servers` only with `timesyncd`; mismatches are ignored and the option descriptions say so (the contract has no cross-option checks, and none is added). The old `keep` daemon mode goes: `service: timesyncd|chrony` installs and enables that daemon, `off` disables sync through `timedatectl`.

5. **The role installs the daemon it needs on every OS** (`chrony` package when `service: chrony`); it never relies on what the OS ships. `servers` is optional: unset, both daemons use the distro's stock servers. `servers` are added to chrony's stock pool lines; for timesyncd they take the place of the stock (fallback) servers (see 6). Arch's stock servers are confirmed by the owner. Debian and Proxmox are not targeted until Arch works (owner, 2026-10-11).
6. **All of timesyncd's settings are exposed**, under their upstream names (rule 2 of `bastet-new-role`), written to `/etc/systemd/timesyncd.conf.d/bastet.conf` section `[Time]`. `timesyncd.conf(5)` has seven keys: `NTP` (`servers`), `FallbackNTP` (`fallback_servers`), `RootDistanceMaxSec`, `PollIntervalMinSec`, `PollIntervalMaxSec`, `ConnectionRetrySec`, `SaveIntervalSec`. The implementer re-checks the list against `man timesyncd.conf` on the dev machine and the ArchWiki page the owner supplied (it stays untracked; never commit it). Only the keys that are set are written. Facts for the docs (ArchWiki): the stock servers are the distro's pool, built in as `FallbackNTP`; per-interface servers (networkd, DHCP) come first, then `NTP=`, and `FallbackNTP=` is used only if none were found, so setting `servers` stops the stock servers being used; the state file `/var/lib/systemd/timesync/clock` is written on every sync and every 60 s and can't be moved, so for SD cards or read-only roots the docs example is `PollIntervalMinSec=1d` with `SaveIntervalSec=infinity`.
7. **chrony is minimal and Arch-only for now:** install the package, add `servers` as `server <s> iburst` lines in a `bastet servers` block of `/etc/chrony.conf`, enable `chronyd.service`. No other chrony settings, no Debian/Proxmox handling (`systemd-timesyncd` package, `chrony/sources.d`, `chronyc reload sources`). The role note's docs carry a visible "needs expanding" note saying so, and the roadmap's "Planned additions" gets a row: full chrony settings, Debian and Proxmox support (chrony is Proxmox's usual daemon).

## Review Focus

- With no options set, the role emits nothing on any host type and OS (a test builds it empty on Arch and an LXC).
- On an LXC, only the time zone is applied: no packages, units, `ntp`, `rtc_local` or NTP files.
- Mismatched settings (servers with `off` or no service, fallback with chrony) emit nothing extra and never raise; the option descriptions say they are ignored. Nested unset fields (`ntp_settings.service` when only `servers` is given) evaluate cleanly in `when:`.
- Switching service stops and disables the other one (`chronyd.service` vs `systemd-timesyncd.service`), and a config change restarts the right unit.
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
| Create `tests/roles/test_time_role.py` | Entries per case, neutrality, container, ignored mismatches, `when:` skips |
| Modify existing tests that use the moved options (`grep -rn "ntp\|timezone\|rtc_local" tests`) | Move their cases to the role test or drop the moved options |
| Modify `docs/roles.md` (generated), `docs/ROADMAP.md` | Tick `time`, update VPS apps step 2 and "Planned additions" |

## Tasks

### Task 1: The `time` role note and its tests

- [ ] **Step 1: Failing tests** in `tests/roles/test_time_role.py` (see the Review Focus). Cases: empty options emit nothing (Arch, LXC); `timezone` only gives one `TimeSettings(timezone)`; `service: off` gives `TimeSettings(ntp=False)` and no packages or files; timesyncd on Arch with servers gives the drop-in `/etc/systemd/timesyncd.conf.d/bastet.conf` with `NTP=` and `FallbackNTP=`, a restart of `systemd-timesyncd.service`, `chronyd.service` disabled and down, timesyncd enabled and up; chrony gives package `chrony`, block `bastet servers` in `/etc/chrony.conf` (`server <s> iburst`), restart `chronyd.service`; LXC with `ntp_settings` and `rtc_local` gives only the time zone; mismatches are ignored without error; `parse_role` accepts the note and `accounts` is `['systemd-timesync']`.
- [ ] **Step 2: See them fail** for the right reason (role not found).
- [ ] **Step 3: Write the role note.** Use the frontmatter keys from `bastet-new-role`. The old `_systemd` time branch in `builtin.py` is the behaviour reference. Express the cases as `when:` conditions. Do not add a contract feature; if one seems needed, **stop and report** (an owner decision).
- [ ] **Step 4: Tests pass** (`uv run pytest tests/roles -q`), then commit by name.

### Task 2: Take the time options out of the `systemd` role

- [ ] **Step 1: Failing tests:** the `systemd` role refuses `timezone` etc. as unknown options (message names the key); its built batch for hostname, locale, services and drop-ins is unchanged.
- [ ] **Step 2:** remove the options and the time branch of `_systemd`, move `systemd-timesync` to the `time` role's `accounts:`, move the old time tests to `test_time_role.py` (or delete them where the new test covers the case; say which in the report).
- [ ] **Step 3:** `uv run python scripts/gen_roles_doc.py`; run `tests/roles` and any test file the grep named; `ruff check src tests`; commit by name.

### Task 3: Docs and roadmap

- [ ] **Step 1:** `docs/ROADMAP.md`: tick `time` in the roles table and in VPS apps step 2, set "Next step" to `base`, remove the `time` row from "Planned additions", and record anything the work revealed (for example a missing contract feature; the LXC `time` check on a real host stays in "Docs and tooling").
- [ ] **Step 2:** `scripts/privacy-check` clean; commit by name.

## Final steps

Final review (opus), one fix wave, the owner runs `uv run pytest -q` and says when it passed; only then ask about merging.
