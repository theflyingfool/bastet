# Roles Redesign — Roadmap (the overall plan)

**Spec:** `docs/specs/2026-10-06-bastet-roles-design.md` (wins over the main spec where they differ).

The redesign is one plan made of six subplans, run in order. Each subplan:
- is written out in full task detail only when it's next, against the code as it stands then;
- ends with merged, working software;
- has its exit criteria checked before the next one starts.

**Status key:** ☐ not started · ◐ in progress · ☑ merged.

| # | Subplan | Status | Depends on | Spec |
|---|---|---|---|---|
| 1 | Host-note split | ☑ | — | §2, §2.1, §8.3 (reports note location) |
| 2 | Role format and library | ☐ | — | §3, §4, §13 (`role check`), §14 |
| 3 | Execution model | ☐ | 2 (and 4's power control for the reboot plan) | §6, §7 |
| 4 | New and expanded blocks | ☐ | 3 | §8, §9, §10 |
| 5 | Presets, boards, guided `add role` | ☐ | 2, 3 | §5, §5.1 |
| 6 | Convert the nine existing roles | ☐ | 2, 3, 4 | §3, §8, §9 |

## 1. Host-note split

**Delivers:**
- Gathered facts move to `_bastet/facts/<host> facts.md`, written only by Bastet.
- Automatic commands (gather, refresh, check, apply, init's host-key pin) never write host notes.
- Fact keys left on a host note are ignored and reported.
- Everything that reads facts reads them through one host view.
- The security note moves to `_bastet/reports/<host> reports.md`.

**Done when:**
- a full gather leaves every `hosts/*.md` byte-for-byte unchanged;
- summaries, dashboard, cabling, roles and connect all work from facts notes;
- an old host note with `os:` on it gets a "remove this" problem line and still behaves correctly.

## 2. Role format and library

**Delivers:**
- The `.md` role contract parser: frontmatter contract, the generated `<!-- bastet:options -->` section, `api`, `version`, the per-OS map form, `vars`, shared options.
- Role sources: bundled, `~/.config/bastet/roles`, a configured folder.
- The inventory copy in `_roles/library/<role>/` with `source`/`source_hash`.
- `bastet role update` (contract diff, then check with the new version, then copy).
- `bastet role check` (the lint list).
- A role's page is its own `.md`, and the roles index is a Base over the library.
- Existing roles keep running through the old builders, wrapped, until subplan 6.

**Done when:**
- a role written as `.md` loads, validates and copies;
- `role update` shows a diff and a check;
- `role check` reports the lint list;
- the generated options section renders with linkable headings.

## 3. Execution model

**Delivers:**
- One merged desired state per host, from all roles.
- Building-block phases replace role `ORDER`.
- Phase hooks with `changed` / `always` / `check:` modes and `changed_exit`, including `before_reboot` / `after_reboot` (a failed `before_reboot` cancels that host's reboot).
- The reboot plan: dependents found through needs/provides are shut down and powered on again with power control, or unmounted and remounted, or Bastet asks (spec §7.6).
- Contributions (`contributes` / `collects`), merged at planning time.
- Same-host needs/provides by kind.
- Compatibility checks (`os`, `os_min`, `types`, `requires`), with the gather warning and the per-host check/apply error.

**Done when:**
- two roles contributing firewall ports produce one file written once;
- hooks run per their mode;
- an incompatible role errors only its host;
- `ORDER` is gone.

## 4. New and expanded building blocks

**Delivers:**
- Templates (Jinja2: `StrictUndefined`, includes limited to the role's own folder, plain data, `toyaml`).
- The systemd block expanded: timers, `.mount` units, sysctl.d, modules-load.d, tmpfiles.d.
- Hardening drop-ins generated from `access`, with `hardening` / `hardening_overrides`, and exposure scores in check.
- JSON state (http or command, find, subset compare with normalising, create/update/delete, write-only fields, async waits, secret auth, pinned TLS, `on: host|controller`).
- Reports (role report options into `_bastet/reports/<host> reports.md`).
- Power control (IPMI, Redfish, Wake-on-LAN; on, off, status), used by the reboot plan.
- Install methods and versions (`install`, container tag, upstream pin, distro hold).
- Secrets rules for files (world-readable secret files are an error).

**Done when:** each block has unit tests, plus a contract test where podman can host it.

## 5. Presets, boards, guided `add role`

**Delivers:**
- `preset:` in role files.
- Shipped and your own presets, with your preset winning on a name clash.
- Origins shown in check.
- Generated kanban Bases, one per role that has presets.
- The guided `add role` (targets → compatible roles → preset → required options → offered providers → diff), with the argument form kept.

**Done when:**
- dragging a card changes what `check` reports;
- `add role` filters by compatibility and offers unmet needs.

## 6. Convert the nine existing roles

**Delivers:** base, packages, pacman, proxmox, users, files, ssh, harden and systemd as `.md` roles. They're declarative where possible, with `role.py` for the guards and logic (ssh lockout guard, microcode, the proxmox nag patch). The old builders and `role.yml` files are removed.

**Done when:**
- every existing test passes against the converted roles;
- check output on a real host is unchanged apart from origins and phase order.

## Deferred (not in this roadmap)

- Removal (`state: absent`, `purge`, the "no longer managed" record).
- The `role.py` trust prompt.
- Proxy and DNS roles that run last.
- Secret rotation (secrets part 2).
- Guest creation (spec §11): a specific role, built on these blocks after the roadmap.
