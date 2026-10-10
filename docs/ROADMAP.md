# Bastet roadmap

The one place that says where Bastet stands and what comes next. The design lives in `docs/specs/`, and detailed
work in `docs/plans/`. Update this file whenever a plan lands.

**Status key:** ☑ done · ◐ partly done · ☐ not started

## Where things live

| What | Where |
|---|---|
| Main design | `docs/specs/2026-09-30-bastet-design.md` |
| Roles redesign (wins over the main spec where they differ) | `docs/specs/2026-10-06-bastet-roles-design.md` |
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

**Next: the roles redesign, subplan 2: role format and library** (`docs/plans/2026-10-07-bastet-roles-2-format-library.md`, written and updated after an independent audit on 2026-10-10: library copies join the command's one commit, a role with no builder fails its host with a clear marker, `role update` lists changed files; uses `bastet doctor <dir>` for role linting).
Subplan 1, the host-note split, is merged: gathered facts live in `_bastet/facts/<host> facts.md`, and automatic
commands never write host notes.
Its six subplans are tracked in `docs/plans/2026-10-06-bastet-roles-roadmap.md`. After the redesign, roles are
built in the order of the roles table below.

## Milestones

| | Milestone | Status |
|---|---|---|
| 1 | See your lab: inventory files, gather (incl. hardware, UniFi), views, dashboard, maps | ☑ |
| 2 | Desired state and the engine: resources, check/apply, roles, the first native roles | ☑ |
| — | Hardening round (external audit fixes) | ☑ |
| — | Secrets part 1: age-encrypted secret notes, unlock/lock, upstream-change gate | ☑ |
| — | Parallel hosts: gather/check/apply in parallel, apply asks once | ☑ |
| 3 | **Roles redesign:** Markdown roles, building-block execution, presets, host-note split | ◐ in progress |
| 3b | **Run logs:** an ordered record of every run, readable in Obsidian, with its own verbosity (below). All three plans done | ☑ |
| 4 | Infrastructure roles: Proxmox node setup, ZFS, guest creation, firewall, container runtime | ☐ |
| 5 | Secrets part 2: rotation and rekey (once real secret-using roles exist) | ☐ |
| 6 | App roles, then proxy and DNS roles that configure themselves from the whole lab | ☐ |
| 7 | Orchestrator LXC and web UI; run logs and resilience | ☐ |

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

**Left from the plan 3 review (small):** a failure that emits no event (a reboot failure, "its node failed", a host that never started) makes the run note's status `failed` but its host heading still reads `ok` with no reason; the note's wait for the event queue is capped at 2 seconds; a git error after the note is written can leave an untracked note; doctor keeps flagging an explicit `"bases": false` and a running Obsidian may undo its fix. Checked in a real Obsidian (2026-10-10): the Runs table and the board render from the generated Bases, so the `kanban` view type and the formula grouping are accepted. Still unverified: the `sort:` key, `hosts.contains(this.host)` on a host's facts note, whether the board refuses drags, the Bases core plugin id `bases`, and "Obsidian 1.14 or later".

**Left from the plan 2 review (small):** live `-vv` lines from other hosts can land inside a host's report when hosts run in parallel (needs a display queue); `bastet log` times are UTC with no marker; two runs in the same second can sort the wrong way for `latest` and pruning; the recorded command leaves out `-y`, `-j`, `--updates` and `--accept-new-hostkey`; command output in a record isn't size-capped; values that aren't text, lists or dicts aren't masked (nothing emits them yet).

**Later (detail board):** a board of runs by detail, dragged to change a note's detail, with the note holding all levels as folds. Decided against for now.

**Later:** a SQLite index built from the JSONL files for cross-run queries and the ARA replacement (JSONL stays the record); every command, not only the run-type ones, emitting events; `refresh` and gather's individual commands emitting events; `hook_ran` and `reboot_step` events once roles subplan 3 adds hooks and the reboot plan.

## Building blocks

Generic mechanisms every role is assembled from (roles spec §8). Roles never implement these themselves.

| | Block | What it does | Missing |
|---|---|---|---|
| ◐ | packages | Repositories and signing keys, installs, updates, reboot-needed marking | `hold` (pinning distro packages), install-method support (`native`/`container`) |
| ☑ | users | Users, groups, authorized keys, sudoers drop-ins | |
| ☑ | files | Whole files, directories, symlinks, lines, blocks; owner/mode; validate before swap | |
| ◐ | templates | Files rendered with Jinja2 (`StrictUndefined`) | Role-folder includes only, plain-data context, `toyaml` |
| ◐ | systemd | Units, drop-ins, hostname, locale, time | Timers, `.mount` units, sysctl.d, modules-load.d, tmpfiles.d, hardening drop-ins from `access` |
| ☐ | JSON state | APIs and JSON-speaking CLIs: read, find, compare a subset, create/update/delete; on the host or the controller | Everything |
| ◐ | commands | A command with a check | Phase hooks (`changed` / `always` / `check:`) |
| ◐ | reports | Read-only information: lynis, listening ports, service exposure, vulnerable and unaccounted packages | Report options any role can offer, the per-host reports note |
| ☐ | power control | On, off and status through IPMI, Redfish or Wake-on-LAN | Everything |

**End-of-run phases** (not blocks):
- ☑ triggers (restart/reload once);
- ◐ reboot: policy and need detection done; missing `before_reboot`/`after_reboot` hooks and the reboot plan for dependent hosts (roles spec §7.6).

## Roles

In the order we currently expect to build them. The finished ones use the old `role.yml` format and are converted
in roles-redesign subplan 6.

| | # | Role | What it does | Notes |
|---|---|---|---|---|
| ☑ | — | systemd | Time, NTP, hostname, locale | Friendly menu over the systemd block |
| ☑ | — | packages | Installs, updates and reboot policy per host | |
| ☑ | — | base | Admin tools everywhere; CPU microcode on physical hosts | |
| ☑ | — | pacman | Every `pacman.conf` option | Arch |
| ☑ | — | proxmox | No-subscription repositories, the subscription-notice patch, libguestfs-tools | Grows into node setup (1) |
| ☑ | — | users | Users, groups, keys, sudoers | |
| ☑ | — | files | Files you want on a host | |
| ☑ | — | ssh | Every sshd option, with the lockout guard | |
| ☑ | — | harden | fail2ban, arch-audit / debsecan, lynis | |
| ☐ | 1 | Proxmox node setup | Bridges (VLAN-aware, applied with a rollback timer), storage, API user and token; shuts guests down cleanly before a reboot and starts them again after (reboot hooks) | Later: IOMMU, clustering, maybe backups |
| ☐ | 2 | zfs | Report first, then datasets, scrubs and snapshots (sanoid or timers, undecided), NFS exports, pools gated on blank disks | |
| ☐ | 3 | Proxmox guests | The node creates LXCs/VMs described by their host notes; first contact and the bastet user; never recreates | Roles spec §11 |
| ☐ | 4 | qemu_guest_agent | Guest agent in VMs | Pointless until guests are created |
| ☐ | 5 | firewall | nftables, built from the ports other roles contribute | |
| ☐ | 6 | podman | Container runtime (Quadlet), rootless where possible | The default runtime |
| ☐ | 7 | mounts | NFS shares and data disks as `.mount` units | Friendly menu over the systemd block |
| ☐ | 8 | aur repository | A local, signed pacman repository built with aurutils; reports AUR updates | Design session first |
| ☐ | 9 | docker | Alternative container runtime | Only where docker must stay |
| ☐ | — | App roles, unordered | caddy, gitea, hugo, lldap or kanidm, grafana, jellyfin, pi_hole, rustdesk, sunshine, glances, unifi, vaultwarden | Native first, podman otherwise |
| ☐ | — | Old docker_* roles, undecided | arr, frigate, homepage, mealie, nextcloud, paperless, uptime, … | See `refs/old-homelab-ansible-roles/` |
| ? | — | Goals unclear | dev_env, pacman_api | Don't port blind |

## Deferred

- **Removal:** `state: absent`, `purge`, the "no longer managed" record.
- **A SQLite index over the run records** (derived from the JSONL, rebuildable) for queries across runs and the ARA replacement.
- **Turning git off:** a setting for an inventory that isn't a git repository. Needs a design first: no commits, no upstream-secrets alert or confirmed-commit baseline, no history behind run notes, and a loud warning that secrets safety is weaker.
- **The trust prompt** for third-party `role.py`.
- **Proxy and DNS roles** that run last.
- **Drift resolution:** accept reality or restore it (main spec §7b).
- **The internal DNS provider:** Pi-hole, the UniFi gateway or a local server.
- **Snapshots, and the UniFi controller key:** undecided.
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

