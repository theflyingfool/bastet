# Decisions

The owner's decisions about how Bastet works, newest first. One entry per decision: what was decided and why. A reversed decision is marked **superseded** and points at its replacement; entries are never deleted. Specs and plans cite entries by ID (`D-012`).

**Add an entry** whenever the owner decides something that is not obvious from the code: a rule, a scope cut, a naming choice, a deferral. Take the next free ID (they only go up). Keep entries to a few lines; the reasoning that needs pages belongs in a spec. `B-` entries were reconstructed from documents after the fact and are in their own table.

Status: **active** · **superseded by D-xxx** · **deferred** (decided to do later; the work is in `docs/ROADMAP.md`).

| ID | Date | Decision | Status |
|---|---|---|---|
| D-032 | 2026-10-14 | First get to writing Markdown roles for the VPS; cleanup and destructive features come after | active |
| D-031 | 2026-10-14 | Remove nothing that still works; only move the old roles to `refs/` and remove the AUR | active |
| D-030 | 2026-10-14 | `packages` and `base` are shipped default roles | active |
| D-029 | 2026-10-14 | Bastet assumes SSH port 22 for now | active |
| D-028 | 2026-10-14 | Debian and apt changes are deferred | deferred |
| D-027 | 2026-10-14 | The pacman lock check is deferred | deferred |
| D-026 | 2026-10-14 | `ssh` and `harden` are removed now, rebuilt last, with no Python in the roles | active |
| D-025 | 2026-10-14 | `sshd -t` is the files block's `validate:`, no `edit: sshd` | active |
| D-024 | 2026-10-14 | sysctl belongs to the `systemd` building block | active |
| D-023 | 2026-10-14 | Generated groups are copied into a user folder; user copy wins | active |
| D-022 | 2026-10-14 | `base` keeps the old role's behaviour for now and will grow | active |
| D-021 | 2026-10-14 | Optional dependencies as dependencies, on by default | deferred |
| D-020 | 2026-10-14 | Reflector is a stopgap in the `pacman` role | active |
| D-019 | 2026-10-14 | `mirrorlist` goes into `NoExtract` while reflector is on | active |
| D-018 | 2026-10-14 | Arch installs always use `pacman -Syu` | active |
| D-017 | 2026-10-14 | A manager role supersedes `packages` options with `supersedes:` | active |
| D-016 | 2026-10-14 | Manager roles come with each OS through the OS file | active |
| D-015 | 2026-10-14 | Bastet is opinionated but respects users' defaults | active |
| D-014 | 2026-10-14 | `packages` is the building block; building blocks are roles and stay Python | active |
| D-013 | 2026-10-14 | The AUR is removed everywhere | active |
| D-012 | 2026-10-14 | Test guardrails live in `docs/testing.md` | active |
| D-011 | 2026-10-14 | Decisions are tracked in this file | active |
| D-010 | 2026-10-12 | Clean up the unconverted roles before rebuilding them | active |

## Backfilled decisions

Reconstructed from documents after the fact, ordered by date (not interleaved with the `D-` numbers). Each cites its source; the original reason may be missing.

| ID | Date | Decision | Source | Status |
|---|---|---|---|---|
| B-002 | 2026-10-11 | VPS apps (vaultwarden, forgejo, caddy) come first; Hugo, a host firewall and backups are held off | `docs/ROADMAP.md` | active |
| B-001 | 2026-10-10 | Roles are Markdown over Python building blocks; a host runs by phase across all roles | `docs/specs/2026-10-10-bastet-roles-architecture-design.md` | active |

## Entries

**D-032 · 2026-10-14 · First get to writing Markdown roles so the VPS can run; then clean up and add the destructive features.** The single biggest push is reaching the point where roles can be written in Markdown and the VPS comes up. Afterwards: go back through the current roles, clean up, and start adding the possibly destructive things (removal and the like) before going much further. Work not on that path is deferred or lowest priority.

**D-031 · 2026-10-14 · Remove nothing that still works.** Apart from moving the unconverted roles to `refs/` and removing the AUR, working code is left alone; leftovers are listed in the roadmap as cleanup debt, not deleted. If a change needs a removal, ask first.

**D-030 · 2026-10-14 · `packages` and `base` are shipped default roles.** A new `data/defaults.yml` lists the roles every managed host gets, with no options, at a rank below the OS defaults (`Bastet default`). Lab, group and host notes add to them. Not `bastet init`: the owner re-initialises their own lab and does not want to rerun it. Spec section 3.

**D-029 · 2026-10-14 · Bastet assumes SSH port 22 for now.** With the `ssh` role gone, nothing else tells Bastet a host's port. A host-note `ssh_port` field, which the rebuilt `ssh` role would write sshd's `Port` from so the two cannot disagree, is a roadmap item.

**D-028 · 2026-10-14 · Debian and apt changes are deferred.** `debian.yml`, the `apt` role's options, optional dependencies on apt and the `non-free-firmware` note wait. Only what is needed to build the Markdown roles is in this round. The `base` role still lists Debian microcode packages (one table, no Debian code).

**D-027 · 2026-10-14 · The pacman lock check is deferred.** A stale `/var/lib/pacman/db.lck` after a timed-out `-Syu` is real (seen on the VPS) but not needed for the roles. When built: a live pacman stops the run; a stale lock is removed only with the owner's say-so, with `-y`. Roadmap row "pacman lock".

**D-026 · 2026-10-14 · `ssh` and `harden` are removed now and rebuilt last, with no Python in the roles.** They relied on far too much Python. Copies go to `refs/` first. Whatever they did in Python is provided by a building block when they are rebuilt. Spec section 12.

**D-025 · 2026-10-14 · `sshd -t` is the files block's `validate:`.** No `edit: sshd` file type is needed for the check.

**D-024 · 2026-10-14 · sysctl belongs to the `systemd` building block.** `sysctl.d` and `modules-load.d` are `systemd` block features, planned in the roadmap, not something a hardening role does in Python. `harden`'s code in `refs/` is the reference.

**D-023 · 2026-10-14 · Generated groups are copied into a user folder; the user's copy wins.** `_bastet/` cannot be edited by the user, so generated OS and type groups move to `groups/` and are never overwritten. `init` generating them, a prompt with a remembered "no" and `bastet add group` are deferred.

**D-022 · 2026-10-14 · `base` keeps the old role's behaviour for now and will grow.** Tool list and microcode as they are today; `tools` replaces its default list, `extra_tools` adds on top; `baseline` is a reserved option for later per-host-kind baselines. No firmware, fwupd, smartd or sensors options yet.

**D-021 · 2026-10-14 · Optional dependencies as dependencies, on by default.** In both package-manager roles (pacman `--asdeps`, apt recommends), settable per package. Deferred.

**D-020 · 2026-10-14 · Reflector is a stopgap in the `pacman` role.** It installs reflector and enables its timer, nothing more; its configuration is a later fix. On by default.

**D-019 · 2026-10-14 · `etc/pacman.d/mirrorlist` goes into `NoExtract` while reflector is on,** so a `pacman-mirrorlist` update cannot overwrite the list reflector wrote.

**D-018 · 2026-10-14 · Arch installs always use `pacman -Syu`,** never `-Sy` alone (a partial upgrade). `refresh: false` keeps plain `-S` with a loud warning on every run.

**D-017 · 2026-10-14 · A manager role supersedes `packages` options with `supersedes: packages.<option>`.** Same key names, shown unset on the manager role with the effective value and its origin. Rank first; a tie goes to the role with `supersedes`; it runs before a role's own `overrides:`. Any role may use the key on any other role.

**D-016 · 2026-10-14 · Manager roles come with each OS through the OS file** (`pacman` with Arch, the way `systemd` does). A new host has none until its first gather.

**D-015 · 2026-10-14 · Bastet is opinionated but respects users' defaults.** A role may do something with no options when its own docs list exactly what; a note can turn it off. Supersedes the old rule that a default must change nothing (CLAUDE.md and the `bastet-new-role` skill are amended in the plan's Task 1).

**D-014 · 2026-10-14 · `packages` is the building block.** Building blocks are roles too, the special ones that stay Python (`packages`, `users`, `files`, `systemd`); every other role is Markdown. There is no separate "packages block" and "packages role".

**D-013 · 2026-10-14 · The AUR is removed everywhere,** including roles table item 8; a note with `aur` is refused by the unknown-key error.

**D-012 · 2026-10-14 · Test guardrails live in `docs/testing.md`,** linked from CLAUDE.md (moved from a stray `4CLAUDE.md`). A test audit is a roadmap row.

**D-011 · 2026-10-14 · Decisions are tracked in this file.**

**D-010 · 2026-10-12 · Clean up the unconverted roles before rebuilding them.** Fewer errors and less to cross-check while building the corrected roles. Recorded in `docs/ROADMAP.md` at the VPS apps step 3. *(Extended by D-026.)*

## Parked

Open or deferred items that are not decisions yet; the work itself is in `docs/ROADMAP.md`.

- How the baseline that fills `base`'s `tools` is selected (for example LXC against the rest).
- Whether `init` should generate groups for all host types.
- Reflector configuration; unaccounted services and files; the SSH port field.
