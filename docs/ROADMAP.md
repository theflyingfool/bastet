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

**Simplification and UX** (`docs/plans/2026-10-07-bastet-simplify-ux.md`) is merged: `bastet run`, selectors, `doctor`,
the hardware split, one Bastet note per object, `_templates/`, user docs in `_bastet/docs/`, type groups and the
`other` type. Left from it: rename the memory facts key `type` → `memory_type` (clashes with host `type`); the
planned review of Tasks 7–11 was skipped at merge.

**Next: the roles redesign, subplan 2: role format and library** (`docs/plans/2026-10-07-bastet-roles-2-format-library.md`, written; uses `bastet doctor <dir>` for role linting).
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
| 3b | **Run logs:** an ordered record of every run, readable in Obsidian, with its own verbosity (below) | ☐ |
| 4 | Infrastructure roles: Proxmox node setup, ZFS, guest creation, firewall, container runtime | ☐ |
| 5 | Secrets part 2: rotation and rekey (once real secret-using roles exist) | ☐ |
| 6 | App roles, then proxy and DNS roles that configure themselves from the whole lab | ☐ |
| 7 | Orchestrator LXC and web UI; run logs and resilience | ☐ |

## Run logs (milestone 3b)

Needed before the Proxmox and ZFS roles, to see what a run did, in the order it did it.

- **Structured output:**
  - **One event stream:** every command emits events, not pre-formatted strings, and they're rendered three ways: the terminal (Rich, width-aware), the run note (Markdown) and the JSONL.
  - **A small shared output layer replaces raw `echo`:** tables that fit the terminal width, per-host headers, consistent status marks, coloured diffs, key/value lists.
  - **Not a terminal** (piped, or in tests): plain text, no colour, no boxes.
  - The parallel runner's host blocks hold events too.
  - Helpers are tested at several widths.

- **Raw event log** on the controller: `~/.local/share/bastet/runs/<run-id>.jsonl`. Every step as it happens: phase, host, resource, read/compare result, command, exit code, timing, triggers, hooks, reboot-plan steps. Everything goes through the secret masker.
- **A run note in the vault:** `_bastet/runs/<date time> <command>.md`.
  - **Top:** command, who ran it, hosts, changed/failed/skipped/stopped counts, duration.
  - **Then per host:** a timeline grouped by phase, in execution order.
  - **Frontmatter stays flat** (`command`, `started`, `hosts`, `changed`, `failed`, `status`) so Bases can list it.
- **Obsidian views:**
  - a Runs Base on `Homelab.md`, newest first, each row linking to its run note;
  - a per-host runs Base on each host page.
- **Log verbosity,** separate from the terminal's `-v`: `--log-level 1–4`, or `log_level:` in `bastet.yml`.
  - **1 (default):** changes and failures, with why.
  - **2:** every item checked, with before/after values.
  - **3:** every command, with exit code and timing.
  - **4:** full command output, masked; truncated per step in the note, complete in the JSONL.
- **To decide when it's planned: what goes into git.** The suggestion:
  - commit run notes for `apply` and `gather`;
  - one rolling "last check" note per host for `check`;
  - keep the JSONL only on the controller, with a retention setting.

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

