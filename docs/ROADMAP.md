# Bastet roadmap

The one place that says where Bastet stands and what comes next. The design lives in `docs/specs/`, and detailed
work in `docs/plans/`. Update this file whenever a plan lands.

**Status key:** ☑ done · ◐ partly done · ☐ not started

## Where things live

| What | Where |
|---|---|
| Main design | `docs/specs/2026-09-30-bastet-design.md` |
| Roles architecture: how roles are built, run and ordered (wins over the roles redesign spec where they differ) | `docs/specs/2026-10-10-bastet-roles-architecture-design.md` |
| Roles redesign: goals and detail (partly superseded by the architecture spec) | `docs/specs/2026-10-06-bastet-roles-design.md` |
| Current plans | `docs/plans/` |
| Research and spikes | `docs/research/`, `docs/spikes/` |
| Reference copies of old Ansible roles, old plans and specs, survey scripts | `refs/` (git-ignored, local only) |
| Plan ledgers and design-session notes | `.superpowers/` (git-ignored) |

## Now

**Run logs were pulled forward ahead of the roles redesign** (decided 2026-10-10): you need to see what a run did, in order, before more roles land, and the event tests give the roles work a regression net. The design is `docs/specs/2026-10-10-bastet-console-output-design.md`, built as three plans:
1. **Console primitives:** done and merged (colour, width-fitting tables, coloured diffs, plain when piped).
2. **Events and the JSONL record:** done (`docs/plans/2026-10-10-bastet-console-2-events.md`): events, the JSONL record, the `-vv` live view and `bastet log`.
3. **Run notes:** done (`docs/plans/2026-10-10-bastet-console-3-run-notes.md`): notes in the vault, the Runs Bases, `bastet log note` and `bastet log show`.

**Simplification and UX** (`docs/plans/2026-10-07-bastet-simplify-ux.md`) is merged: `bastet run`, selectors, `doctor`,
the hardware split, one Bastet note per object, `_templates/`, user docs in `_bastet/docs/`, type groups and the
`other` type. The memory facts key is now `memory_type`, and Tasks 7–11 have since been reviewed and their
follow-ups fixed.

**Priority (decided 2026-10-11): the VPS apps** (milestone 3c below): vaultwarden, forgejo and caddy, via the gates, secrets in files, `edit: env`, and rewriting ssh, base and harden. Hugo, a host firewall and backups are held off.

**The contract and the blocks are built (2026-10-11)** — see `docs/plans/2026-10-11-bastet-roles-arch-2-contract-blocks.md`. A Markdown role file can now carry `packages:`, `systemd:`, `users:`, `files:` and `commands:` entries that call the building blocks (blocks never call each other; roles call blocks), with `when:` on any entry. **Contract hardening is built too (2026-10-12)** (`docs/plans/2026-10-11-bastet-time-role.md`): option `requires`/`conflicts`, clearing an inherited option with `null`, `overrides:` in role notes and in a role file itself (the role's own, per host), `choices_from:` (long value lists), role `checks:` (info, warning, error, with `applied.origin`), `sections:`, `each:` (one entry per list item or map pair), and file triggers (`daemon_reload`, `on_change`, with `restart`/`reload` acting only on a running unit). The `time` role is the first role written on it. **Next step: the `base` role** (VPS apps, step 3). Blocks are filled in only as the next role needs them, and what is planned is in the "Planned additions" table. The old role-format work (library, update, lint, pages) stays on hold until the end.

**Audit increment 1 (make the shipped roles safe) is built** on branch `audit-inc-1` (`docs/plans/2026-10-10-audit-inc-1-shared-roles-safe.md`; reviews pending). `edit: ini` writes a section-scoped managed block, so pacman can no longer touch a repository's settings; `as: entries` and `commands:` entries let the apt and pacman roles own their repositories as data; the proxmox role, the Repository resource and the packages `repositories` option are removed. The next step is the owner's `run -c` diff on a real Arch host, then the next increments of `docs/plans/2026-10-10-bastet-audit-correction-plan.md`; role conversion resumes after increments 1 to 3.

## Milestones

| | Milestone | Status |
|---|---|---|
| 1 | See your lab: inventory files, gather (incl. hardware, UniFi), views, dashboard, maps | ☑ |
| 2 | Desired state and the engine: resources, check/apply, roles, the first native roles | ☑ |
| — | Hardening round (external audit fixes) | ☑ |
| — | Secrets part 1: age-encrypted secret notes, unlock/lock, upstream-change gate | ☑ |
| — | Parallel hosts: gather/check/apply in parallel, apply asks once | ☑ |
| 3 | **Roles architecture:** Markdown roles over Python building blocks, phase execution, one role converted at a time (host-note split done) | ◐ in progress |
| 3b | **Run logs:** an ordered record of every run, readable in Obsidian, with its own verbosity (below). All three plans done | ☑ |
| 3c | **VPS apps:** vaultwarden, forgejo and caddy on the VPS, reached by finishing the gates, the secrets and `edit: env` block work, and rewriting ssh, base and harden (below) | ☐ next |
| 4 | Infrastructure roles: Proxmox node setup, ZFS, guest creation, firewall, container runtime (set aside until a Proxmox system is up) | ☐ |
| 5 | Secrets part 2: rotation and rekey (once real secret-using roles exist) | ☐ |
| 6 | App roles, then proxy and DNS roles that configure themselves from the whole lab | ☐ |
| 7 | Orchestrator LXC and web UI; run logs and resilience | ☐ |

## Roles architecture (milestone 3)

Design: `docs/specs/2026-10-10-bastet-roles-architecture-design.md`. Each step ends with merged, working software, and the next is planned only when it is next.

1. ☑ **First slice** (`docs/plans/2026-10-10-bastet-roles-arch-1-slice.md`; apt is included, and we stop for hard testing afterwards): draft contract (`api: 0`), the generic builder next to the old Python builders, `files` settings (`edit: ini`), `before:`/`after:` on entries, `wants`/`provides`, the phase engine across all roles (triggers once at the end, daemon-reload, health check), and **pacman as Markdown-only**. Done when pacman has no Python, every existing pacman test passes unchanged, and `check` output on an Arch host is identical. Built: pacman is Markdown-only; apt is a new Markdown-only role (curated, incomplete option list); the engine runs entries from all roles by block slot and each trigger once per host. **Next gate: hard testing** (the full suite, `BASTET_CONTRACT=1 uv run pytest tests/contract -q`, real runs, failure cases, Ctrl-C, `-vv`), and no more roles are converted until it is done. Known risk: the AUR (roles table item 8) is out of scope and may break on Arch hosts in the new order.
2. ☐ **Contract, then one role at a time, evaluating after each** (the contract first: `docs/plans/2026-10-11-bastet-roles-arch-2-contract-blocks.md`; then the order in the VPS apps milestone: time, base, caddy, forgejo, vaultwarden, harden split up, ssh last; then the rest): `users`, `files`, `packages` and `systemd` are the blocks' own roles and stay Python. Each role adds only the block or contract features it needs.
3. ☐ **Capabilities and contributions** beyond `wants`, when a real role needs them: the firewall (same-host), then the Git forge (a host waits for the whole provider host; guests already wait for their node).
4. ☐ **Stabilize:** the library, `role update`, `doctor <dir>` and role pages (the audited old subplan 2), then presets, boards and the guided `add role`.
5. ◐ **Versioning:** ☑ version 0.2.0 (run logs done), written only in `pyproject.toml`; bump at each milestone; no git tags for now. `scripts/version-bump X.Y.Z` bumps the version and refreshes the time zone list of the `time` role; `scripts/version-bump --check` verifies it (see `docs/versioning.md`). Roles use semver plus the content hash; the contract stays a draft until about 1.0.

## VPS apps (milestone 3c)

Goal (decided 2026-10-11): vaultwarden, forgejo and caddy running on the VPS as soon as possible. This is pulled ahead of the Proxmox and ZFS work and of the rest of "one role at a time" (roles architecture step 2). All four apps are in the Arch repos, so each is a native role over the existing blocks. Each step ends with merged, working software, and the next is planned only when it is next.

1. ☑ **Finish the contract and expose the blocks** (`docs/plans/2026-10-11-bastet-roles-arch-2-contract-blocks.md`): role-file entries that call `packages`, `systemd` and `users`, `when:` on every entry. Gates cleared (2026-10-11): the `packages` role is tested. Built: `packages:`, `systemd:` and `users:` entries; `files:` forms `content`, `template`, `directory`, `link`, `line` and `block`; `when:` on every entry and `{{ }}` values over options and the host and lab facts (sandboxed Jinja2); plain-text passwords from secrets hashed in the host's own scheme; the unaccounted-users report, now fed by roles' `accounts:` and shipped OS defaults (Arch). An end-to-end test runs a demo role through the engine in block order. Not yet hard-tested on real hosts.
2. ☑ **`time` role** (`docs/plans/2026-10-11-bastet-time-role.md`): the time zone everywhere and systemd-timesyncd on Arch, written entirely as Markdown with no Python. It proved the contract (options with `requires`, `choices_from`, `sections:`, `checks:`, file triggers) and that a role needs no Python. Not yet checked on a real host.
3. ☐ **`base`** in Markdown, with `when:` for microcode.
   **Decided 2026-10-12 (owner): clean up first.** The plan for this step starts with its own branch and a first task that removes the roles that are not converted yet (`base`, `ssh`, `harden`: the Python builders in `roles/system.py` and `BUILDERS` in `roles/builtin.py`, their `role.yml` files, docs and tests) from `src/`, moving them to `refs/` (git-ignored, local only) as reference for the rewrites, and cleans the tests and other technical debt that only existed for them. Then each role is rebuilt in Markdown on the finished contract, so there is less to cross-check while building. The blocks' own roles (`users`, `files`, `packages`, `systemd`) stay. The plan must first list what depends on the old roles and decide each (examples to check: `HostInfo.ssh_ports` and the fail2ban jail, the package baselines, type and OS default roles that name `base`/`ssh`/`harden`, `bastet add role` and doctor lists, `docs/roles.md`, the lockout guard for ssh and what protects a host meanwhile). The cost to weigh in the plan: until `ssh` and `harden` are rebuilt, Bastet does not manage sshd or hardening.
4. ☐ **`caddy`:** package, service, and a Caddyfile that imports a `conf.d` directory. Automatic TLS, so no certificate block. Cross-role contributions can wait; each app role drops its own vhost file.
5. ☐ **`forgejo`:** package, config with `edit: ini`, secrets as whole setting values, service through a systemd drop-in, a Caddy vhost.
6. ☐ **`vaultwarden`:** as forgejo, plus `edit: env` (`KEY=value` files with the systemd quoting rule), the first role that needs it.
7. ☐ **`harden`** split into small roles (fail2ban, sysctl, sudo, reports) plus a thin meta role that bundles them. Missing blocks (timers, sysctl.d and so on) are built here, as needed.
8. ☐ **`ssh`** last, with `edit: sshd` (`sshd -t` check, a few `warn` rules, no lockout guard); it can lock you out, so it goes after hardening and just before expanding the current roles.

Then expand pacman and apt (low priority). Blocks are only built out when a role needs them; each block's "Missing" column and docs record what is planned.

**Held off for now:** hugo (and with it the `fetch` block, which stays planned), a host firewall (the VPS uses the provider's firewall) and backups.

## Run logs (milestone 3b)

Needed before the Proxmox and ZFS roles, to see what a run did, in the order it did it. Design:
`docs/specs/2026-10-10-bastet-console-output-design.md`. Built as three plans.

**Plan 1, console primitives: done.** One `bastet.ui` console for every command (`out.echo`/`secho`/`diff`/`table`/`block`/`reveal`): colour, width-fitting tables, coloured diffs, status marks. It is plain text (byte-identical to the old output) when piped, under test, or when `NO_COLOR` is set. Secrets are masked inside it.

**Plan 2, events and the JSONL record: done** (`docs/plans/2026-10-10-bastet-console-2-events.md`).
- **Events:** the engine and `run` emit events (phase, item checked, command with exit code and timing, trigger, host started/finished/skipped, notes). Output is masked once, in one place.
- **The JSONL record:** every run, always at full detail, in `~/.local/share/bastet/runs/<run-id>.jsonl` (mode `0600`), kept forever unless limited (`runs.keep_runs`, `runs.keep_days`; `bastet init` asks, and Enter keeps everything). `bastet log` lists past runs and `bastet log export` prints one.
- **`-v` counts:** `-v` shows compliant items as before; `-vv` live events; `-vvv` commands with exit code and timing; `-vvvv` their output.
- A read script's output is never recorded (it holds file contents), and a `secret` resource's command and output are hidden.

**Plan 3, run notes: done** (`docs/plans/2026-10-10-bastet-console-3-run-notes.md`).
- **A run gets a short note in the vault when its command makes a commit anyway** (`_bastet/runs/<date time> <mode> <id suffix>.md`). A check that writes nothing is not a real run for the vault: no note, no commit (it is still in `bastet log`). The note is part of the command's one commit.
- **The note is level 1 by default** (changes and failures); `runs.note_detail` (1 to 3) raises it, and command output never goes into a note. Deeper detail is read from the record: `bastet log show <run> -vvv` replays it in the terminal; `bastet log note <run>` makes the note of any run. Nothing is deleted.
- **Obsidian views:** a Runs Base in the dashboard and a per-host one in each host's facts note (so none of your notes is edited), newest first, with Changes (the default), Checks, Failures and All runs views. Directly below each table, a board by `status` (Obsidian's built-in Kanban view).
- **Git:** an automatic note never causes a commit that would not otherwise happen; the JSONL is never committed.
- **Reliability:** the note is best-effort (a failure warns and the command still commits), a failed host's reason is in the note, and an interrupted run's note says so.
- **Obsidian setup:** `bastet init` and `doctor --fix` enable the Bases core plugin (needs Obsidian 1.14 or later); the status board is read-only.

**Left from the simplification review (small):** the shipped docs are titled "Using roles" and "Using secrets" where the plan said "Roles" and "Secrets", and an `add role` file's body embeds the options (`![[role#Options]]`) where the plan asked for a link — decide which is right and make plan and code agree; the secret-word tab completion (`complete_secret_words`) is only tested with a hand-built context, not through Click's real completion path; and `bastet run` can record one run per process only (`events._active` is a module global), which is fine today.

**Left from the plan 3 review (small):** a failure that emits no event (a reboot failure, "its node failed", a host that never started) makes the run note's status `failed` but its host heading still reads `ok` with no reason; the note's wait for the event queue is capped at 2 seconds; a git error after the note is written can leave an untracked note; doctor keeps flagging an explicit `"bases": false` and a running Obsidian may undo its fix. Checked in a real Obsidian (2026-10-10): the Runs table and the board render from the generated Bases, so the `kanban` view type and the formula grouping are accepted. Still unverified: the `sort:` key, `hosts.contains(this.host)` on a host's facts note, whether the board refuses drags, the Bases core plugin id `bases`, and "Obsidian 1.14 or later".

**Left from the plan 2 review (small):** live `-vv` lines from other hosts can land inside a host's report when hosts run in parallel (needs a display queue); `bastet log` times are UTC with no marker; two runs in the same second can sort the wrong way for `latest` and pruning; the recorded command leaves out `-y`, `-j`, `--updates` and `--accept-new-hostkey`; command output in a record isn't size-capped; values that aren't text, lists or dicts aren't masked (nothing emits them yet).

**Later (detail board):** a board of runs by detail, dragged to change a note's detail, with the note holding all levels as folds. Decided against for now.

**Later:** a SQLite index built from the JSONL files for cross-run queries and the ARA replacement (JSONL stays the record); every command, not only the run-type ones, emitting events; `refresh` and gather's individual commands emitting events; `hook_ran` and `reboot_step` events once roles subplan 3 adds hooks and the reboot plan.

## Building blocks

Generic mechanisms every role is assembled from (roles spec §8). Roles never implement these themselves.

| | Block | What it does | Missing |
|---|---|---|---|
| ◐ | packages | Installs, updates, reboot-needed marking. Callable from a Markdown role (each package manager's role owns its repositories; `packages` has no `repositories` option) | `hold` (pinning distro packages), install-method support (`native`/`container`), AUR bootstrap and update/reboot policy as block options (today in the role), `wants: package-manager` |
| ☑ | users | Users, groups, authorized keys, sudoers drop-ins. Callable from a Markdown role; reports unaccounted accounts, those nothing expects: users the role manages (the default `root` and `bastet` included), accounts an applied role declares (`accounts:`), the OS defaults, and the `allowed` list. `bastet` is a system account on new hosts (the first real run decides what is left) | Roles call it. Blocks do not call each other (the role that needs both calls both), so `users` never calls `systemd` |
| ◐ | files | Callable from a Markdown role. Whole files, directories, symlinks, lines, blocks; owner/mode; validate before swap; Jinja2 templates (below). Section settings: `edit: ini` writes a managed block per section, originals commented `#bastet: `, off and empty supported, removal deferred; `backup: true` keeps the original once as `<path>.bastet-orig`. Also apt's `render: apt` and `as: entries` (`deb822`, `ini_section`), `before:`/`after:` (`run_before`/`run_after`) | More `edit:` types, added only when a role needs them and listed in the files docs as planned (`env` for vaultwarden, `sshd` for ssh; `sysctl`-style `key = value` later); format checking (YAML, JSON, TOML, INI parsed on the controller; `visudo -cf`, `sshd -t`, `systemd-analyze verify` on the host; a role's own `validate:`); replace-with-check |
| ◐ | templates (part of files) | Files rendered with Jinja2 (`StrictUndefined`) | The full language; role-folder includes only, `toyaml`/`tojson`/`quote`. The context should see every variable, across hosts too (for cross-host setups); not used by any role yet, so built when a role needs it |
| ◐ | systemd | Units, drop-ins, hostname, locale, time. Callable from a Markdown role | Planned, built only when a role needs them: timers (cron-style schedules belong here, so `systemd` covers all of systemd), `.mount` units, sysctl.d, modules-load.d, tmpfiles.d, hardening drop-ins from `access` |
| ◐ | secrets in other blocks | A `secret:<path>` reference works today as the whole value of any role option (decrypted in memory, masked in reports and the run record) | Checked 2026-10-11: enough for the VPS apps (one secret per setting). Secrets embedded inside a larger string, and templates seeing secrets, are deferred until a role needs them |
| ☐ | api (JSON state) | Common JSON API interaction, and JSON-speaking CLIs: read, find, compare a subset, create/update/delete; on the host or the controller | Everything. Not needed for the VPS apps |
| ☐ | fetch | Remote files, wherever they are: the machine running Bastet, a git repository at a given point, curl/ftp-style sources | Everything. Held with hugo |
| ? | git | Git as managed state (clone, pull, commit, deploy keys), apart from `fetch` pulling a repo at a point | Maybe its own block later |
| ? | wait / probe | Health checks, port or HTTP readiness, waiting after reboots | To investigate; may feed phase ordering. Network checks (ping and the like) may live here |
| ? | storage | Mounts, disks and the ZFS work, if it goes the block route | Decide when ZFS is picked up |
| ◐ | commands | A command with a check; callable from a Markdown role: role files can declare `commands:` entries (`name`, `run`, `unless`, optional `when`, `before`/`after`) | Phase hooks (`changed` / `always` / `check:`) later |
| ◐ | reports | Read-only information: lynis, listening ports, service exposure, vulnerable and unaccounted packages, unaccounted users | Report options any role can offer, the per-host reports note. Done: a provider's stock-image packages (Linode Arch) are allowed in the unaccounted report from shipped baselines |
| ☐ | power control | On, off and status through IPMI, Redfish or Wake-on-LAN | Everything |

Other ideas judged to be roles, not blocks: network config (covered by `systemd` and `files`), kernel settings, certificates. Containers (podman) are files plus `systemd` (Quadlet); a role that needs `commands` should first be checked for whether a new block is really required.

**Execution (not blocks):**
- ☑ the phase engine (first slice): entries from all roles ordered by block, `before:`/`after:` on an entry (the resource fields are `run_before`/`run_after`), `wants` on a block, daemon-reload once before restarts, a health check after restarts (`restart(unit, check=False)` opts out). The first failed step skips every later item on that host ("earlier failure on this host: ..."); triggers still run for what changed before the failure; a failed trigger stops the remaining triggers; verify still runs.
- ☑ triggers: each restart/reload once per host, at the end;
- ◐ reboot: policy and need detection done; missing `before_reboot`/`after_reboot` hooks and the reboot plan for dependent hosts (roles spec §7.6).

## Roles

In the order we currently expect to build them. The finished ones use the old `role.yml` format and Python builders;
the ones that can be are converted one at a time to straight Markdown (roles architecture spec §5): ssh, base, harden and a new proxmox role. `users`, `files`, `packages` and `systemd` are the building blocks' own roles and stay Python. pacman and apt are done.

Rows marked ⏸ (the Proxmox and ZFS infrastructure roles) are set aside until a Proxmox system is up again; they are not removed.

| | # | Role | What it does | Notes |
|---|---|---|---|---|
| ☑ | — | systemd | Hostname, locale | Python: the systemd block's own role. The time options moved to the `time` role; `systemd-timesync` stays in this role's `accounts:` (an OS-provided account is recognised whether or not the `time` role is applied). Changed with account defaults: it leaves things alone by default (`manage_hostname` false), so a note that relied on the old defaults must set them |
| ☑ | — | packages | Installs, updates and reboot policy per host | Python: the packages block's own role. No `repositories` option; each manager's role owns them |
| ◐ | — | base | Admin tools everywhere; CPU microcode on physical hosts | Works in the old format; to be rewritten in Markdown (VPS apps, step 3) |
| ☑ | — | pacman | Every `[options]` setting as a managed block in `pacman.conf` (originals commented `#bastet: `, one-time backup); repositories as `bastet repo <name>` blocks | Arch. Markdown-only, no Python (the proof) |
| ☑ | — | apt | Curated apt options, written to `/etc/apt/apt.conf.d/90-bastet`; repositories as `.sources` files; `modernize_sources` | Debian. New, Markdown-only; the option list is curated and incomplete (full list generated later) |
| ✗ | — | proxmox | The role was removed (audit increment 1). The apt role owns repositories now; the subscription-notice patch and the tools it installed are gone. The `proxmox` host type stays and applies no baseline roles | A new Proxmox role is to be designed (see Proxmox node setup, 1) |
| ☑ | — | time | Time zone, time sync, NTP | Markdown-only. The time zone is applied everywhere `timedatectl` works; `ntp` and the seven `timesyncd.conf` settings use systemd-timesyncd on Arch. Debian/Proxmox (chrony) is planned, not built: the role's own `overrides:` entry ignores `ntp` and the timesyncd options there with one info note, so a lab-wide `ntp: true` works; LXC leaves sync to the node. The allowed zones are in `time zones.txt`, a snapshot the version bump refreshes |
| ☑ | — | users | Users, groups, keys, sudoers | Python: the users block's own role |
| ☑ | — | files | Files you want on a host | Python: the files block's own role |
| ◐ | — | ssh | Every sshd option, with the lockout guard | Works in the old format; rewritten last in the VPS apps milestone (step 8, `edit: sshd`) |
| ◐ | — | harden | fail2ban, arch-audit / debsecan, lynis | Works in the old format; to be split into small roles plus a meta role and rewritten in Markdown (VPS apps, step 7) |
| ⏸ | 1 | Proxmox node setup | Bridges (VLAN-aware, applied with a rollback timer), storage, API user and token; shuts guests down cleanly before a reboot and starts them again after (reboot hooks) | Later: IOMMU, clustering, maybe backups |
| ⏸ | 2 | zfs | Report first, then datasets, scrubs and snapshots (sanoid or timers, undecided), NFS exports, pools gated on blank disks | |
| ⏸ | 3 | Proxmox guests | The node creates LXCs/VMs described by their host notes; first contact and the bastet user; never recreates | Roles spec §11 |
| ⏸ | 4 | qemu_guest_agent | Guest agent in VMs | Pointless until guests are created |
| ☐ | 5 | firewall | nftables, built from the ports other roles contribute | Held: the VPS uses the provider's firewall |
| ☐ | 6 | podman | Container runtime (Quadlet), rootless where possible | The default runtime |
| ☐ | 7 | mounts | NFS shares and data disks as `.mount` units | Friendly menu over the systemd block |
| ☐ | 8 | aur repository | A local, signed pacman repository built with aurutils; reports AUR updates | Design session first. The AUR is out of scope for the first slice and may break on Arch hosts in the new order |
| ☐ | 9 | docker | Alternative container runtime | Only where docker must stay |
| ☐ | V1 | caddy | Web server and reverse proxy; Caddyfile importing a `conf.d` directory, automatic TLS | VPS apps, step 5 |
| ☐ | V2 | vaultwarden | Native package, env file, `ADMIN_TOKEN` secret, Caddy vhost | VPS apps, step 6 |
| ☐ | V3 | forgejo | Native package, `app.ini` settings, secrets, Caddy vhost | VPS apps, step 6. Forgejo chosen over gitea |
| ☐ | — | App roles, unordered | hugo (held, needs `fetch`), lldap or kanidm, grafana, jellyfin, pi_hole, rustdesk, sunshine, glances, unifi | Native first, podman otherwise |
| ☐ | — | Old docker_* roles, undecided | arr, frigate, homepage, mealie, nextcloud, paperless, uptime, … | See `refs/old-homelab-ansible-roles/` |
| ? | — | Goals unclear | dev_env, pacman_api | Don't port blind |

## Planned additions

One row per building block or role: what we know it still needs. Nothing here is built until a role needs it; when one is built, delete its row (or the part of it) and tick the block or role above.

| Block or role | Planned | Needed by |
|---|---|---|
| packages (block) | `hold` (pinning distro packages); install method (`native`/`container`); AUR bootstrap and update/reboot policy as block options (today in the role); `wants: package-manager` | harden, app roles |
| users (block) | An explicit way to clear a password; the `bastet` account refusal also checking names that come from options; what to do with system accounts the report still lists (after the first real run) | users role, hardening |
| files (block) | `edit: env` (`KEY=value`, systemd quoting rule); `edit: sshd` (with `sshd -t`); `sysctl`-style `key = value` edits; format checking (YAML, JSON, TOML, INI parsed on the controller; `visudo -cf`, `systemd-analyze verify` on the host); replace-with-check; a secret embedded in a larger string | vaultwarden, ssh, harden |
| templates (files) | `toyaml`/`tojson`/`quote` filters; cross-host variables in the template context; a place to keep templates next to a role (also for roles under `_roles/`) | the first role that uses a template |
| systemd (block) | Timers (cron-style schedules); `.mount` units; `sysctl.d`, `modules-load.d`, `tmpfiles.d`; hardening drop-ins from `access` | harden, mounts |
| commands (block) | Phase hooks (`changed` / `always` / `check:`) | roles that need an action after a change |
| reports (block) | Report options any role can offer; the per-host reports note | harden |
| secrets | Secrets inside a larger string and visible to templates; rotation and rekey (milestone 5) | forgejo (maybe), later roles |
| api, fetch, power control, git, wait/probe, storage | Everything (see the block table above) | later milestones |
| pacman, apt (roles) | More options (low priority); apt's full option list generated rather than curated | after the VPS apps |
| chrony, Debian and Proxmox time sync (`time` role) | Time sync on Debian-like hosts with chrony, one item, all chrony settings. **When it lands, remove the `time` role's `overrides:` entry (`when: not host.arch_like`) that ignores the sync settings with a note.** The old Python role's handling of the Debian `systemd-timesyncd` package and of `chrony/sources.d` was dropped with it | Proxmox hosts, Debian hosts |
| base (role) | Markdown rewrite with `when:` for microcode | VPS apps, step 3 |
| harden (role) | Split into small roles (fail2ban, sysctl, sudo, reports) plus a thin meta role | VPS apps, step 7 |
| ssh (role) | Markdown rewrite with `edit: sshd`, `warn` rules, no lockout guard | VPS apps, step 8 |
| caddy, forgejo, vaultwarden (roles) | New roles over the blocks | VPS apps, steps 4 to 6 |
| Proxmox node setup, zfs, Proxmox guests, qemu_guest_agent (roles) | See the roles table (set aside until a Proxmox system is up) | milestone 4 |
| UniFi devices (gather, roles) | Circle back to gather: the Debian gateway (UXG Fiber, `bastet` login works, root-equivalent) can probably use the normal collection; switches and APs run OpenWrt with BusyBox (no sudo, systemd, python or package manager) and stay on `mca-dump`. Gather's UniFi path should use the Bastet key and a configurable username; an `os` fact for UniFi devices; revisit `managed` per device kind; a role-compatibility marker so roles opt in for UniFi. Probe: `scripts/unifi-probe HOST` (read-only) | after vaultwarden (VPS apps step 6): gather, later UniFi roles |
| Contract, not built (time role plan) | **File removal** (a file a role stopped managing, or an `each:` item that was removed, stays on the host): destructive, needs its own design. **Role dependencies** `needs`/`uses`/cross-role contributions: each app role drops its own file, so they wait. **Provider conflicts and cross-role forcing** (two programs need one kind of thing, one accepts providers C and D, the other only D, so something must force D): roles declare the providers they accept or force (via `provides:`/`needs:`, or `overrides:` entries naming another role with a conflict error when two roles force different values), never inferred from package-manager error output; not now, design with the capabilities step. **User-scope systemd units** (`systemctl --user`, linger): needed by rootless podman. A declared per-OS **`supports:`**: `checks:` covers today's need. A **`running:`** shortcut for unit entries: the expression is short. **Duplicate detection across different `each:` entries** (it is per entry today). An option named `item` or `key` is shadowed inside an `each:` entry (so avoid those names). **Build errors number entries across flattened sections**, not within the section. The **only_if probe** cannot tell a failed command from a lost connection (either skips the trigger). A **trigger restart after a unit was started in the same run** restarts it once more. **More host facts for storage** (disks), added when ZFS is designed. Smaller: a requires/conflicts error names the last contributing note, not the one that set the option; override errors count from 0 (`overrides[0]`); `check_relations` has an unused `where` parameter; a secret used only in a plain `when:` does not mark entries secret; `{{ }}` in a `commands:` entry is filled in only with `each:`; `overrides:` `when:` refuses the `applied` fact; `bastet add role` has no CLI test for bare keys; the real `timedatectl` path of the bump script and `tests/contract` for the time role were not run | roles that need them |
| Account defaults | The Proxmox guests role (LXCs and VMs created on demand) reuses a role's `starter:`, so a new guest's `users` note starts with `root` and its password secret and the guest's root password is set when it is generated; Debian OS defaults and accounts; `systemd-timesync` stays in the `systemd` role's accounts; provenance ("which package owns this account") as an optional explain feature; an existing host's `bastet` uid is not changed; a null map entry like a bare `root:` could be made lenient; a rename command that re-seals secrets when a host is renamed; `defaults_for` re-reads the OS files on each call | Proxmox guests, `time`, Debian hosts |
| Contract plan leftovers | Scanning included/imported templates for secret options; replacing the private jinja call in `expr._expression`; `commands:` entries are not marked secret (they are literal text today); the extra `login_defs` read per user; `example.net` in older apt and repository tests (the example data says `example.com`) | when touched |
| `bastet add role` | Target first: list lab, groups, types and hosts, then offer roles that are not assigned to that target and are compatible with it (a role's `os:` against the host's gathered OS; for a group, type or the lab, compatible with at least one member; unknown OS offered; roles without `os:` always offered). Keep `add role X --to Y` and `-y` | after vaultwarden (VPS apps step 6) |
| Generated note layout (very low priority) | Tidy the notes Bastet generates: the Bastet guide link appears twice on every host note and on the lab note, so show it once; show the groups on the lab note; on a host note the role links should go only to that host's own role file (`_roles/hosts/<host>/<role>.md`), and that file links back to the role itself, so the host note does not mix two kinds of link; every section of every generated note gets a proper heading so the outline is useful | polish |
| Docs and tooling | The options table's Default column showing the config file's own default; a check on a real LXC host that `time` entries behave in a container | after the contract plan |

## Deferred

- **Removal:** `state: absent`, `purge`, the "no longer managed" record.
- **Role calls role (`uses:`):** reserved, not built; no concrete case yet.
- **Inferring order from references** (a file owned by `svc` implies the user first): the long-term replacement for most `before:`/`after:`.
- **Hard `needs` and cross-host `needs`/`provides`:** designed in the architecture spec, built with the first role that needs them (the Git forge).
- **A SQLite index over the run records** (derived from the JSONL, rebuildable) for queries across runs and the ARA replacement.
- **Turning git off:** a setting for an inventory that isn't a git repository. Needs a design first: no commits, no upstream-secrets alert or confirmed-commit baseline, no history behind run notes, and a loud warning that secrets safety is weaker.
- **The trust prompt** for third-party `role.py`.
- **Proxy and DNS roles** that run last.
- **Drift resolution:** accept reality or restore it (main spec §7b).
- **The internal DNS provider:** Pi-hole, the UniFi gateway or a local server.
- **Snapshots, and the UniFi controller key:** undecided.
- **`bastet add network`** (VLANs): asks for name, VLAN ID and subnet and writes the `networks:` entry in the lab note's properties, after showing the diff. Today the entry is written by hand. Not a quick addition: it edits the lab note's frontmatter in place, so it needs a safe writer that leaves the rest of the note alone.
- **Clean-install baselines and modified-config reporting.**
- **Ansible import and the Ansible backend.** May not be needed now that roles are native.

## Working rules

- **Unit tests never touch real data:** your inventory, `~/.config/bastet`, `~/.local/share/bastet`, `~/.ssh`, the real `~/.cache` or `$XDG_RUNTIME_DIR`. No network; placeholder data only.
- **Container (contract) tests** run only when asked: `BASTET_CONTRACT=1`.
- **Commits:** stage files by name; never `git commit -a`.
- **Docs and placeholders:** nothing with real lab details (domains, addresses, keys, host names) goes into tracked files. Use placeholders; reference material stays in `refs/`.

### Example data

Everything in tracked files (docs, role examples, tests, fixtures) uses these, never real lab details:

| Kind | Use | Never |
|---|---|---|
| Addresses | `10.1.0.0/24` (lan), `10.1.20.0/24` (servers), `10.1.30.0/24` (trusted)…; hosts like `10.1.0.15` | real addresses |
| Host names | `pve1`, `pve2` (nodes), `media01`, `git1`, `nas1`, `vps1`, `laptop1`, `gw1`, `sw1`, `ap1` | real host names |
| Users | `admin`, `alice` | real user names |
| Domain | `example.com`, `lab.example.com` | the real domain |

`scripts/privacy-check` enforces the "never" column, using patterns from the git-ignored `.privacy-patterns`.

