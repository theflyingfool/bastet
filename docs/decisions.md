# Decisions

The owner's decisions about how Bastet works, newest first. One entry per decision: what was decided and why. A reversed decision is marked **superseded** and points at its replacement; entries are never deleted. Specs and plans cite entries by ID (`D-012`).

**Add an entry** whenever the owner decides something that is not obvious from the code: a rule, a scope cut, a naming choice, a deferral. Take the next free ID (they only go up). Keep entries to a few lines; the reasoning that needs pages belongs in a spec. `B-` entries were reconstructed from documents after the fact and are in their own table.

Status: **active** · **superseded by D-xxx** · **deferred** (decided to do later; the work is in `docs/ROADMAP.md`).

| ID | Date | Decision | Status |
|---|---|---|---|
| D-040 | 2026-10-14 | Accounts created by packages Bastet installs on purpose should be accepted automatically; until that is built each role lists its accounts | deferred |
| D-039 | 2026-10-14 | `allow` lists match on `client_ip`, so a Caddy behind a trusted proxy sees the real visitor | active |
| D-038 | 2026-10-14 | The AUR stays out for now; the open problem is validating build files, and a reviewed local `PKGBUILD` is a possible later replacement for the `xcaddy` build | active |
| D-037 | 2026-10-14 | DNS-challenge Caddy is built on the host with `xcaddy` (sandboxed build unit, pacman hook plus guarded command, systemd drop-in), latest plugin by default | active |
| D-036 | 2026-10-14 | `caddy` collects its sites from other roles' `proxy` options by default and keeps a manual `sites:` list; per-site knobs inherit `site_defaults` | active |
| D-035 | 2026-10-14 | `.serena/` is git-ignored and local; a new worktree gets a copy, and it is never committed | active |
| D-034 | 2026-10-14 | Default role notes: `packages` at the lab, `base` at the lab, every group and every host | active |
| D-033 | 2026-10-14 | `packages` and `base` reach every managed host through the type files | superseded by D-034 |
| D-032 | 2026-10-14 | First get to writing Markdown roles for the VPS; cleanup and destructive features come after | active |
| D-031 | 2026-10-14 | Remove nothing that still works; only move the old roles to `refs/` and remove the AUR | active |
| D-030 | 2026-10-14 | `packages` and `base` are shipped default roles | superseded by D-033 |
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
| B-003 | 2026-10-14 | Arch derivatives are not handled | `docs/specs/2026-10-14-bastet-package-roles-and-base-design.md` (section 3) | active |
| B-004 | 2026-10-14 | Unaccounted reports stay in each host's note, untouched | `docs/specs/2026-10-14-bastet-package-roles-and-base-design.md` (decision 10) | active |
| B-005 | 2026-10-12 | Role-defined `overrides:` replace the Debian error and the lab-wide `ntp` warning | `docs/plans/2026-10-11-bastet-time-role.md` (decision 13) | active |
| B-006 | 2026-10-12 | `time` role: loops, zone-list stamp, restart only a running unit | `docs/plans/2026-10-11-bastet-time-role.md` (Owner decisions resolved, D-1 to D-3) | active |
| B-007 | 2026-10-12 | Versioning: bump for any shipped change, roles 0.1.0 to 1.0.0 after a real-host check, bump check enforced | `docs/versioning.md`; `docs/ROADMAP.md` (Roles architecture, step 5); date approximate | active |
| B-008 | 2026-10-11 | Strict time zone validation, list refreshed only at version bumps | `docs/plans/2026-10-11-bastet-time-role.md` (Owner decisions, 1) | active |
| B-009 | 2026-10-11 | `ntp` unset leaves sync alone; Debian/Proxmox chrony not built; `rtc_local` dropped | `docs/plans/2026-10-11-bastet-time-role.md` (Owner decisions, 3, 5, 6) | active |
| B-010 | 2026-10-11 | `systemd-timesync` stays in the `systemd` role's `accounts:` | `docs/plans/2026-10-11-bastet-time-role.md` (Owner decisions, 2) | active |
| B-011 | 2026-10-11 | Who owns the always-present Arch accounts | `docs/plans/2026-10-11-bastet-account-defaults.md` (Owner decisions) | active (the `systemd-timesync` part is superseded by the entry above) |
| B-012 | 2026-10-11 | A new role note gets automatic secret references | `docs/plans/2026-10-11-bastet-account-defaults.md` (secret references task) | active |
| B-013 | 2026-10-11 | A role is data: no Python without a very good reason | `docs/plans/2026-10-11-bastet-time-role.md` (constraints) | active |
| B-014 | 2026-10-11 | VPS app order: time, base, caddy, forgejo, vaultwarden, harden split, ssh last | `docs/ROADMAP.md` (VPS apps, milestone 3c) | active |
| B-015 | 2026-10-11 | Secrets are one reference per setting for now | `docs/ROADMAP.md` (Building blocks, secrets in other blocks) | deferred |
| B-016 | 2026-10-11 | Expressions are sandboxed Jinja2 with `StrictUndefined` | `docs/plans/2026-10-11-bastet-roles-arch-2-contract-blocks.md`; `docs/specs/2026-10-10-bastet-roles-architecture-design.md` (section 8) | active |
| B-002 | 2026-10-11 | VPS apps (vaultwarden, forgejo, caddy) come first; Hugo, a host firewall and backups are held off | `docs/ROADMAP.md` | active |
| B-017 | 2026-10-10 | Run logs pulled ahead of the roles redesign | `docs/ROADMAP.md` (Now) | active |
| B-018 | 2026-10-10 | Runs produce an event stream, recorded as JSONL; SQLite deferred | `docs/specs/2026-10-10-bastet-console-output-design.md` (Decisions) | active |
| B-019 | 2026-10-10 | Run notes exist only when the command commits anyway | `docs/specs/2026-10-10-bastet-console-output-design.md` (Decisions) | active |
| B-020 | 2026-10-10 | Run log command is `bastet log`; retention is forever by default | `docs/specs/2026-10-10-bastet-console-output-design.md` (Decisions) | active |
| B-021 | 2026-10-10 | The ssh lockout guard is dropped | `docs/specs/2026-10-10-bastet-roles-architecture-design.md` (section 2) | active |
| B-022 | 2026-10-10 | Repositories belong to each package manager's role | `docs/specs/2026-10-10-bastet-roles-architecture-design.md` (section 3); `docs/plans/2026-10-10-bastet-audit-correction-plan.md` (2a) | active |
| B-023 | 2026-10-10 | The contract is a draft (`api: 0`) until about 1.0; reserved keys do nothing | `docs/specs/2026-10-10-bastet-roles-architecture-design.md` (sections 1, 2, 7) | active |
| B-024 | 2026-10-10 | Cross-host waits wait for the whole provider host | `docs/specs/2026-10-10-bastet-roles-architecture-design.md` (Across hosts) | deferred |
| B-025 | 2026-10-10 | `check` writes nothing to the vault or git by default | `docs/plans/2026-10-10-bastet-audit-correction-plan.md` (section 4, 1) | active (overlaps the run-notes entry above; the documents do not say which wins) |
| B-026 | 2026-10-10 | Broad selectors respect `gather: false`; only an exact name overrides it | `docs/plans/2026-10-10-bastet-audit-correction-plan.md` (section 4, 2) | active |
| B-027 | 2026-10-10 | Gather exits nonzero when every attempted host failed | `docs/plans/2026-10-10-bastet-audit-correction-plan.md` (section 4, 6) | active |
| B-028 | 2026-10-10 | Host names must be valid hostnames, with explicit migration | `docs/plans/2026-10-10-bastet-audit-correction-plan.md` (section 4, 3) | active |
| B-029 | 2026-10-10 | The AUR is cut (first decision) | `docs/plans/2026-10-10-bastet-audit-correction-plan.md` (C22); `docs/plans/2026-10-10-bastet-roles-arch-1-slice.md` | superseded by D-013 (same cut, now removed everywhere) |
| B-030 | 2026-10-10 | Host types renamed and ordered, with no migration | `docs/plans/2026-10-10-host-types-rename.md` | active |
| B-001 | 2026-10-10 | Roles are Markdown over Python building blocks; a host runs by phase across all roles | `docs/specs/2026-10-10-bastet-roles-architecture-design.md` | active |
| B-031 | 2026-10-07 | One `run` verb replaces gather, check and apply | `docs/plans/2026-10-07-bastet-simplify-ux.md` | active |
| B-032 | 2026-10-06 | Gathered facts live in `_bastet/facts`, never in host notes | `docs/plans/2026-10-06-bastet-roles-1-host-note-split.md`; `docs/specs/2026-10-06-bastet-roles-design.md` | active |
| B-033 | 2026-10-06 | Unset means leave upstream's default alone; removal is deferred | `docs/specs/2026-10-06-bastet-roles-design.md` (sections 3.1 and 12) | active |
| B-034 | 2026-10-01 | Bastet has its own engine in pyinfra's shape | `docs/research/2026-10-01-execution-engine-survey.md` (Recommendation); `docs/specs/2026-09-30-bastet-design.md` (section 9.2) | active |
| B-035 | 2026-09-30 | Frontmatter is plain YAML written in Obsidian's style | `docs/spikes/2026-09-30-obsidian-frontmatter.md`; `docs/specs/2026-09-30-bastet-design.md` (section 5.2) | active |
| B-036 | 2026-09-30 | Nothing is removed by absence; destruction is explicit | `docs/specs/2026-09-30-bastet-design.md` (chapter 8, section 9.0) | active |
| B-037 | 2026-09-30 | Role-managed state is not gathered; identical items merge, conflicting ones error | `docs/specs/2026-09-30-bastet-design.md` (section 9.0) | active |

## Entries

**D-040 · 2026-10-14 · Package-created accounts should be accepted automatically.** The unaccounted-users report flagged `git` (made by the Arch `git` package that `base` installs) and would flag `caddy`. The owner wants the accounts of packages Bastet installs on purpose accepted by Bastet itself, not by hand-kept `accounts:` lines; if that is a lot of work it goes on the roadmap. It did: the row "Accepted users from packages" in `docs/ROADMAP.md` (sketch: read the `sysusers.d` files of the installed packages on Arch). Until then `base` lists `git` and `caddy` lists `caddy`.

**D-039 · 2026-10-14 · `allow` matches on `client_ip`.** The owner wants real client addresses once the home lab is up. `client_ip` equals `remote_ip` when visitors connect directly and sees the real visitor behind a proxy listed in `trusted_proxies`. Source: `docs/specs/2026-10-14-bastet-caddy-and-collectors-design.md` (section 3).

**D-038 · 2026-10-14 · The AUR stays out for now.** D-013 removed it; the reason is not "never" but that build files which cannot all be read by hand have no validation yet. A `PKGBUILD` kept in a role folder (reviewed once, checksums pinned, built by an unprivileged user, installed with `pacman -U`) is a possible later replacement for the `xcaddy` build (D-037); it needs a "local package" building block and its own spec. Clarifies D-013, does not reverse it.

**D-037 · 2026-10-14 · DNS-challenge Caddy is built on the host with `xcaddy`.** The repo's `caddy` stays installed and is the version signal. A `DynamicUser` oneshot unit (which runs `go install ...xcaddy@latest` itself, so only `go` is a package) builds `/usr/local/bin/caddy-bastet`; a pacman hook (after `caddy` or `go` change) and a guarded Bastet command start it; a systemd drop-in points `caddy.service` at it. Go stays installed. The plugin follows its newest release by default (rolling release), a note can pin a tag. The `dns` option is `provider` + `secrets` + `settings`, and Linode, Cloudflare and Namecheap are documented in the role. Source: `docs/specs/2026-10-14-bastet-caddy-and-collectors-design.md` (section 5).

**D-036 · 2026-10-14 · `caddy` collects its sites; the manual list stays.** Sites come from every role's `proxy` option that targets this proxy (the original collector design, built at planning time, without the final phase), plus a manual `sites:` list for hosts Bastet does not configure. Per-site knobs inherit `site_defaults` from the `caddy` role (site value, else default, else nothing written); no lab-level defaults, but the lab dashboard lists every site. Which Caddy receives an exposure is decided by the Caddy role's `serves` option (lab scopes) and an optional `via` link, not a lab map; internal and external services share names (split-horizon), and the scope is optional when the lab has one domain. Caddy exposes a curated set of options plus raw `extra:`, not every directive. Source: `docs/specs/2026-10-14-bastet-caddy-and-collectors-design.md` (sections 2 to 4).

**D-035 · 2026-10-14 · `.serena/` stays git-ignored and local.** `scripts/privacy-check` rejects it when committed. Because a worktree does not have ignored files, CLAUDE.md says to copy `.serena/` (and `.privacy-patterns` when the check is to run) into a new worktree, and never to commit either.

**D-034 · 2026-10-14 · Default role notes.** The lab gets `packages` and `base` role notes; every group (machine type, OS, custom) and every host gets a `base` note. A role is assigned the normal way, as a note in `_roles/`. They are written when the lab, host or copied group is created (`bastet init`, `bastet add host`, the gather group copy), from the role's `starter:`, and never overwrite an existing note. No migration. Replaces D-033 and D-030.

**D-033 · 2026-10-14 · `packages` and `base` reach every managed host through the type files.** *Superseded by D-034:* it was a new mechanism the owner did not ask for; the owner wants the roles assigned as notes at each level.

**D-032 · 2026-10-14 · First get to writing Markdown roles so the VPS can run; then clean up and add the destructive features.** The single biggest push is reaching the point where roles can be written in Markdown and the VPS comes up. Afterwards: go back through the current roles, clean up, and start adding the possibly destructive things (removal and the like) before going much further. Work not on that path is deferred or lowest priority.

**D-031 · 2026-10-14 · Remove nothing that still works.** Apart from moving the unconverted roles to `refs/` and removing the AUR, working code is left alone; leftovers are listed in the roadmap as cleanup debt, not deleted. If a change needs a removal, ask first.

**D-030 · 2026-10-14 · `packages` and `base` are shipped default roles.** *Superseded by D-033:* the owner did not want a new `defaults.yml`. Original text: a new file listed the roles every managed host gets, at a rank below the OS defaults.

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

**D-015 · 2026-10-14 · Bastet is opinionated but respects users' defaults.** A role may do something with no options when its own docs list exactly what; a note can turn it off. Supersedes the old rule that a default must change nothing (CLAUDE.md, `bastet-new-role` and `bastet-run-plan` were amended 2026-10-14).

**D-014 · 2026-10-14 · `packages` is the building block.** Building blocks are roles too, the special ones that stay Python (`packages`, `users`, `files`, `systemd`); every other role is Markdown. There is no separate "packages block" and "packages role".

**D-013 · 2026-10-14 · The AUR is removed everywhere,** including roles table item 8; a note with `aur` is refused by the unknown-key error.

**D-012 · 2026-10-14 · Test guardrails live in `docs/testing.md`,** linked from CLAUDE.md (moved from a stray `4CLAUDE.md`). A test audit is a roadmap row.

**D-011 · 2026-10-14 · Decisions are tracked in this file.**

**D-010 · 2026-10-12 · Clean up the unconverted roles before rebuilding them.** Fewer errors and less to cross-check while building the corrected roles. Recorded in `docs/ROADMAP.md` at the VPS apps step 3. *(Extended by D-026.)*

## Backfilled entries

Reconstructed from documents; not reviewed by the owner yet. Status is in the table above.

**B-003 · 2026-10-14 · Arch derivatives are not handled.** Only Arch proper and Proxmox are run, so OS `match` is exact on the OS id and derivatives are not handled this round. The owner says this may change. Source: docs/specs/2026-10-14-bastet-package-roles-and-base-design.md.

**B-004 · 2026-10-14 · Unaccounted reports stay in each host's note, untouched.** Each host's Markdown note keeps one unaccounted section with a subsection per kind (packages, users, files, services). They work today and are not touched this round. Reason not recorded. Source: docs/specs/2026-10-14-bastet-package-roles-and-base-design.md.

**B-005 · 2026-10-12 · Role-defined `overrides:` replace the Debian error and the lab-wide `ntp` warning.** A role file may carry its own `overrides:` for its own options, with an `info` note when it changes a value that was set, so a skip is never silent. It supersedes time-role decisions 5 (Debian error) and 12 (lab-wide warning). Source: docs/plans/2026-10-11-bastet-time-role.md.

**B-006 · 2026-10-12 · `time` role: loops, zone-list stamp, restart only a running unit.** The owner chose to include `each:` loops (caddy sites, mounts, jails and peers will need them), to stamp the zone list at version bumps, and that restart/reload act only on a running unit, leaving failed units to a `Unit` entry. Source: docs/plans/2026-10-11-bastet-time-role.md.

**B-007 · 2026-10-12 · Versioning: bump for any shipped change, roles 0.1.0 to 1.0.0 after a real-host check, bump check enforced.** Bastet is `0.X.Y`, written only in `pyproject.toml`, no git tags. Roles are versioned on their own, start at 0.1.0 and become 1.0.0 once checked on a real host; `scripts/version-bump --check` fails when a role changed since the last bump. This supersedes the architecture spec's "no tooling enforces bumps". Reason not recorded. Source: docs/versioning.md; docs/ROADMAP.md; date approximate.

**B-008 · 2026-10-11 · Strict time zone validation, list refreshed only at version bumps.** The `time` role checks zones against a list from `timedatectl list-timezones`, regenerated by `scripts/version-bump`, not per commit or run. Reason not recorded. Source: docs/plans/2026-10-11-bastet-time-role.md.

**B-009 · 2026-10-11 · `ntp` unset leaves sync alone; Debian/Proxmox chrony not built; `rtc_local` dropped.** `ntp` unset changes nothing, `true` writes settings and enables, `false` only stops and disables (never deletes config). Debian and Proxmox sync (chrony) is not built yet. `rtc_local` is dropped from the role because the owner has no dual-boot hosts. Source: docs/plans/2026-10-11-bastet-time-role.md.

**B-010 · 2026-10-11 · `systemd-timesync` stays in the `systemd` role's `accounts:`.** An OS-provided account is recognised whether or not an optional role is applied. This reverses the account-defaults plan, which said it moves to the `time` role when that exists. Source: docs/plans/2026-10-11-bastet-time-role.md.

**B-011 · 2026-10-11 · Who owns the always-present Arch accounts.** `alpm` belongs to the `pacman` role, the six `systemd-*` accounts to the `systemd` block role, the rest to the Arch OS file. `root` and `bastet` are default entries of the `users` role, not a hidden allowance, and the `bastet` lockout guard still applies to them. Debian is ignored for now. Reason not recorded. Source: docs/plans/2026-10-11-bastet-account-defaults.md.

**B-012 · 2026-10-11 · A new role note gets automatic secret references.** Any role with a value that is likely required and should be secret has the reference written into the new note's frontmatter, so `secret set` works right away. Source: docs/plans/2026-10-11-bastet-account-defaults.md.

**B-013 · 2026-10-11 · A role is data: no Python without a very good reason.** New roles are Markdown. Python in a role needs a very good reason; repo tooling such as the time zone list is not role code. Reason not recorded. Source: docs/plans/2026-10-11-bastet-time-role.md.

**B-014 · 2026-10-11 · VPS app order: time, base, caddy, forgejo, vaultwarden, harden split, ssh last.** The roles come in that order. `harden` is split into small roles (fail2ban, sysctl, sudo, reports) plus a thin meta role; `ssh` goes last because it can lock you out. Source: docs/ROADMAP.md.

**B-015 · 2026-10-11 · Secrets are one reference per setting for now.** A `secret:<path>` reference as a whole option value is enough for the VPS apps. Secrets embedded in larger strings, and templates seeing secrets, wait until a role needs them. Source: docs/ROADMAP.md.

**B-016 · 2026-10-11 · Expressions are sandboxed Jinja2 with `StrictUndefined`.** `{{ }}` values and `when:` use Jinja2 over option values and the host and lab facts. An unset option drops the field rather than writing `None`. This settled the open question on how rich `when:` may be. Source: docs/plans/2026-10-11-bastet-roles-arch-2-contract-blocks.md; docs/specs/2026-10-10-bastet-roles-architecture-design.md.

**B-017 · 2026-10-10 · Run logs pulled ahead of the roles redesign.** You need to see what a run did, in order, before more roles land, and the event tests also give the roles work a regression net. Source: docs/ROADMAP.md.

**B-018 · 2026-10-10 · Runs produce an event stream, recorded as JSONL; SQLite deferred.** Renderers consume events instead of rendering after the fact. The JSONL record is always at full detail and masked; SQLite is a later derived index. `run` and `refresh` emit events; other commands use the console primitives only. Reason not recorded. Source: docs/specs/2026-10-10-bastet-console-output-design.md.

**B-019 · 2026-10-10 · Run notes exist only when the command commits anyway.** A run gets a vault note only if its command makes a commit anyway; a clean check gets no note and no commit. The note is level 1 unless `runs.note_detail` raises it (capped at 3), and the JSONL is never committed. Reason: output must never reach git. Source: docs/specs/2026-10-10-bastet-console-output-design.md.

**B-020 · 2026-10-10 · Run log command is `bastet log`; retention is forever by default.** `log` lists runs; `export`, `show` and `note` act on one run. It is not called `runs` because that is too close to `run`. `runs.keep_runs` and `runs.keep_days` limit retention, and `init` asks. Source: docs/specs/2026-10-10-bastet-console-output-design.md.

**B-021 · 2026-10-10 · The ssh lockout guard is dropped.** If someone configures ssh wrong, they own it. The syntax check stays and the ssh role adds a few `warn` rules for the obvious cases. Source: docs/specs/2026-10-10-bastet-roles-architecture-design.md.

**B-022 · 2026-10-10 · Repositories belong to each package manager's role.** `apt` declares `.sources` files and `pacman` declares `bastet repo` blocks; `packages` has no `repositories` option. The `proxmox` role is deleted (the `proxmox` host type stays; a new role comes later). Reason: a repository is that manager's own setting. Source: docs/specs/2026-10-10-bastet-roles-architecture-design.md; docs/plans/2026-10-10-bastet-audit-correction-plan.md.

**B-023 · 2026-10-10 · The contract is a draft (`api: 0`) until about 1.0; reserved keys do nothing.** Real roles shake the contract out before it is promised. `uses`, `needs`, `provides`, `contributes` and `collects` are parsed and ignored until a real role needs them. Roles are converted one at a time, pacman first, evaluating after each. Reason: freezing nine roles' contracts before anything proves it was the problem. Source: docs/specs/2026-10-10-bastet-roles-architecture-design.md.

**B-024 · 2026-10-10 · Cross-host waits wait for the whole provider host.** A role that `needs` something from another host waits until that host finishes apply and verify; a failed provider skips the dependent. Check stays parallel. Designed, not built. Reason not recorded. Source: docs/specs/2026-10-10-bastet-roles-architecture-design.md.

**B-025 · 2026-10-10 · `check` writes nothing to the vault or git by default.** The earlier behaviour (security notes and run notes, one commit) was by design but is changed. A local run record outside the vault stays, and a check can be kept on request. Reason not recorded. Source: docs/plans/2026-10-10-bastet-audit-correction-plan.md.

**B-026 · 2026-10-10 · Broad selectors respect `gather: false`; only an exact name overrides it.** `@lab`, types and globs honour the opt-out; naming a host exactly overrides it, and the output says so before connecting. Reason not recorded. Source: docs/plans/2026-10-10-bastet-audit-correction-plan.md.

**B-027 · 2026-10-10 · Gather exits nonzero when every attempted host failed.** Partial failure still exits 0, a strict flag fails on any failure, and a host-note exclusion (C23) keeps expected-down hosts out of the count. Reason not recorded. Source: docs/plans/2026-10-10-bastet-audit-correction-plan.md.

**B-028 · 2026-10-10 · Host names must be valid hostnames, with explicit migration.** Existing invalid names get a `doctor` warning and an explicit migration, never a silent rename. Reason not recorded. Source: docs/plans/2026-10-10-bastet-audit-correction-plan.md.

**B-029 · 2026-10-10 · The AUR is cut (first decision).** The `aur` option, its bootstrap and its sudoers file go, ending a root-equivalent sudoers rule. The roles-arch-1 plan had left the AUR out of scope for that slice only. Source: docs/plans/2026-10-10-bastet-audit-correction-plan.md; docs/plans/2026-10-10-bastet-roles-arch-1-slice.md.

**B-030 · 2026-10-10 · Host types renamed and ordered, with no migration.** `laptop` becomes `computer`, `unknown` becomes `undefined`, the three UniFi types merge into `unifi`, and `add host` offers a fixed order. The owner starts a fresh vault, so an old name is just an unknown type. Source: docs/plans/2026-10-10-host-types-rename.md.

**B-031 · 2026-10-07 · One `run` verb replaces gather, check and apply.** Fewer commands and concepts: `add hardware`, attribution and `--take` go, hardware notes get the same split as hosts, one Bastet note per object, every command makes at most one commit, and `doctor` is added. `proxmox-node` becomes `proxmox` with only an error message as migration. Decided with the owner 2026-10-07. Source: docs/plans/2026-10-07-bastet-simplify-ux.md.

**B-032 · 2026-10-06 · Gathered facts live in `_bastet/facts`, never in host notes.** Automatic commands never write host notes; fact keys left on a host note are ignored and reported. This supersedes the main spec on where facts go. Reason not recorded. Source: docs/plans/2026-10-06-bastet-roles-1-host-note-split.md; docs/specs/2026-10-06-bastet-roles-design.md.

**B-033 · 2026-10-06 · Unset means leave upstream's default alone; removal is deferred.** A contract `default:` is only for Bastet's own decisions. Removing a role never uninstalls anything and reports "no longer managed, left in place"; explicit removal is later work. Reason not recorded. Source: docs/specs/2026-10-06-bastet-roles-design.md.

**B-034 · 2026-10-01 · Bastet has its own engine in pyinfra's shape.** Facts are gather probes and a resource compares and fixes with before/after reporting. Logic may be ported from pyinfra (MIT); Ansible modules are reference only (GPLv3); Fabric is skipped. Ansible import is deferred and the first roles are native. Reason: reuses the runner gather already proved, with no second SSH stack. Source: docs/research/2026-10-01-execution-engine-survey.md; docs/specs/2026-09-30-bastet-design.md.

**B-035 · 2026-09-30 · Frontmatter is plain YAML written in Obsidian's style.** No comments, anchors or tags, because Obsidian rewrites the whole frontmatter block on any edit; Bastet writes block style with minimal quoting and appends new keys. Source: docs/spikes/2026-09-30-obsidian-frontmatter.md; docs/specs/2026-09-30-bastet-design.md.

**B-036 · 2026-09-30 · Nothing is removed by absence; destruction is explicit.** Deleting a role or host file never uninstalls or destroys; check reports it as left in place. Destroying a guest needs `state: destroyed` and typing its hostname. Reason not recorded. Source: docs/specs/2026-09-30-bastet-design.md.

**B-037 · 2026-09-30 · Role-managed state is not gathered; identical items merge, conflicting ones error.** What a role controls is read live and never stored in host files, so there are never two copies. Items are matched by identity and merged with origins listed; conflicting desired state is an error naming both roles. Source: docs/specs/2026-09-30-bastet-design.md.

## Parked

Open or deferred items that are not decisions yet; the work itself is in `docs/ROADMAP.md`.

- How the baseline that fills `base`'s `tools` is selected (for example LXC against the rest).
- Whether `init` should generate groups for all host types.
- Tests should derive expectations from the data (a role's accounts, option lists, role sets) instead of copying it as literals; the owner is auditing the testing method. Example: the pinned `systemd` account set in `tests/roles/test_role_accounts.py` needed an edit for every new Arch account.
- Contract tests: Debian is not a concern for now (`test_roles_contract` fails on both users). The Arch contract image has no systemd and no network, so the three `pacman` contract tests (reflector timer) and `test_arch_updates_reported` fail there; fix the tests or the image, not the roles.
- `full_upgrade` without `install:` is an error; on Arch it is now redundant (`-Syu` is the default), so it could become a no-op there.
- Reflector configuration; unaccounted services and files; the SSH port field.
- Caddy review leftovers (2026-10-14, none block): the collector scan catches only `BastetError` (another exception would break every host's planning and the refresh); a manual site name is not normalised for case or a trailing dot in the site address; `build install` and the first-apply order need a systemd test (the owner's host checks cover them); `via` accepts only a host/role link, not a bare role link; `upstream` has no line-break check.
- Provider details the owner does not validate: Linode's token scope and Namecheap's account prerequisites stay documented as unverified in the `caddy` role.
- After the 0.4.0 merge the owner's full-suite run had failures; the same head gave 2088 passed on the dev box, so they depend on the owner's machine or setup. The failing test names never arrived; on 2026-10-14 the owner said to assume his checks are complete.
- The `bastet-run-plan` Finish section merges with `git push origin <branch>:main`; a background session cannot push to `main`, so it opens a draft PR and the owner merges (see the skill proposals in the session report).
