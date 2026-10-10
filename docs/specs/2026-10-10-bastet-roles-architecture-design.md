# Roles architecture, revisited

**Status:** design, agreed in conversation 2026-10-10, for your review. Nothing in the roadmap or the existing plans has been changed yet.

**Relationship to earlier documents:** this keeps the goals of `2026-10-06-bastet-roles-design.md` (the roles redesign spec) and changes **how it is built and in what order**. Where the two differ, this one wins. It replaces the six-subplan order in `docs/plans/2026-10-06-bastet-roles-roadmap.md`. The audited plan `docs/plans/2026-10-07-bastet-roles-2-format-library.md` is not discarded: its library, update, lint and pages tasks move to the end (section 5).

## 1. Why revisit

- **Two migrations.** The old order converts all nine roles' contracts to Markdown (subplan 2), then converts them again to declarative bodies (subplan 6). The contract would be frozen on nine roles before anything proves it.
- **Roles are still run one after another.** Today `run_host` applies one role's batch, fires that batch's triggers, then moves to the next role. Identical items already merge across roles, but ordering and triggers are per role, with a hard-coded role order list.
- **The blocks already exist.** The engine has resource classes for packages and repositories, files, directories, links, lines and blocks, systemd units, hostname and locale, users, groups and keys, commands, and reports. What roles do today is Python that maps option values onto those resources (`system.py`, `builtin.py`, about 780 lines).

## 2. Decisions

| Decision | Choice |
|---|---|
| Building blocks | Python, stay. Packages (with repositories), users, files (with settings, Jinja2 templates and format checking), systemd, commands, api when a role needs it, reports |
| Roles | Straight Markdown, about 99% of the time: a contract that hands entries to the blocks. `role.py` is a rare escape hatch (well under 1% of roles). Logic lives in the Markdown contract and in the blocks, not in role Python |
| Direct use of a block | Stays easy. A role file may carry block entries directly (the thin `packages`, `users` and `files` roles stay): installing one package on a host is one short role file |
| Config-file settings | A feature of the `files` block, not a new block. The block always validates the new file (`sshd -t` for sshd) before swapping it in |
| ssh lockout guard | Dropped (2026-10-10): if someone configures it wrong, they own it. The syntax check stays; the ssh role adds a few quick `warn` rules for the obvious cases. The old guard and its tests are removed when ssh is converted |
| Execution | By phase across all roles, not role by role. Triggers run once, at the end |
| Role calls role | Reserved (`uses:`), not built. No concrete case yet |
| Capabilities | `wants` (soft, block side) in the first slice. Hard `needs`, cross-host `needs`/`provides` and `contributes` are designed (section 4, "Across hosts") and built with the first role that needs them |
| Migration order | One role at a time, pacman first, evaluate after each |
| Contract | Draft (`api: 0`) until real roles have shaken it out; promised at 1.0 |
| Versioning | Light (section 6) |

## 3. The shape

- **A role is a Markdown file.** Its frontmatter is the contract: options and the entries it hands to the blocks. Its body is the documentation. Optional `role.py` (`validate()` and `build()`, as in the earlier spec §3.4) exists as an escape hatch for the rare case nothing else covers; needing it is a sign a block or the contract is missing something.
- **Every option of the thing a role manages is exposed**, named as upstream names it (the earlier spec §3.1). An option carries `key:` (the upstream name), `section:` and, for config lines, `as: flag|value`.
- **The `files` block gains settings.** An entry says `edit: ini` (later `kv`, `sshd`, and so on): every option with a `key:` that is set becomes a line in that file, and unset options leave the file's defaults alone. This replaces the Python that maps options to lines today (`PACMAN_SETTINGS`, `_sshd_line`).
- **The `files` block checks content before swapping it in.** By format: YAML, JSON, TOML and INI are parsed on the controller, so a mistake (including one a template caused) is caught at check time before any host is touched; tool-based checks run on the host against the new file before it replaces the old one: `visudo -cf` for sudoers, `sshd -t` for sshd, `systemd-analyze verify` for units, and more as roles need them. A role can also give its own `validate:` command. A failed check refuses that edit and shows the file and the tool's message. Checkers are added as roles need them, not all up front: ini first (pacman), then sshd, sudoers and yaml.
- **Templates are Jinja2 and belong to the `files` block.** A files entry can render its content from a template in the role's folder: the full language, with `StrictUndefined`, includes limited to the role's own folder, plain data in the context, and the `toyaml`, `tojson` and `quote` filters (earlier spec §3.3). The whole of Jinja2 is available; whoever needs a feature gets it, and bundled roles are kept simple by convention.
- **Where logic lives, so roles need no Python:**
  - **Conditions and computed values** are `when:` conditions, per-OS maps (`{arch: …, debian: …, default: …}`) and short expressions in the frontmatter: microcode by CPU vendor, the Debian suite from the OS string, which NTP service to use.
  - **Validation** is contract rules: `min`/`max`, `choices`, a text type that forbids newlines, `os:`, and `validate:` expressions that carry their own message and a `level` of `error` (refuses the apply) or `warn` (shown in check, never blocks).
  - **Safety and mechanics are built into the blocks**, so every role gets them: the `sshd` settings format validates the new config with `sshd -t` before it is swapped in (a syntax error always refuses the edit); `packages` knows the AUR bootstrap and update and reboot policy; `files` can replace text with a check before swapping the file in (the Proxmox patch); an ini renderer covers fail2ban.
- **Old and new run side by side.** A role with a Markdown body uses one generic builder. A role without one keeps its Python builder. Each role is converted once, contract and body together. The old format and the dual path are deleted when the last role is converted.

### Example: pacman, Markdown-only (draft)
```yaml
name: pacman
os: [arch]
provides: [package-manager]
options:
  parallel_downloads: {type: int, min: 1, key: ParallelDownloads, section: options}
  color:              {type: bool, key: Color, section: options, as: flag}
files:
  - path: /etc/pacman.conf
    edit: ini
```

## 4. How a host runs

One plan per host: every role's entries join one desired state, each entry belonging to a block. Identical entries merge (their origins are listed); conflicting ones are an error naming both roles.

**Phases, in order**
1. **Plan:** resolve values, validate, merge, find conflicts.
2. **Check:** read everything, show the plan, confirm.
3. **Repositories and keys**, then **packages** (installs, holds, updates).
4. **Users:** groups, users, keys, sudoers.
5. **Files:** files, directories, links, settings edits, templates.
6. **Systemd:** `daemon-reload` once if unit files changed, then drop-ins, units, timers, sysctl, modules, tmpfiles, enable and start.
7. **Commands and API calls**, which need services up.
8. **Triggers:** each restart or reload once, then a **health check** that a restarted unit is running.
9. **Verify:** read again and compare.
10. **Reboot** per policy, with before and after hooks (the reboot plan and power control stay with the infrastructure roles).

An entry can move itself with `before:` or `after:` (below). The first failed step stops that host; other hosts continue.

**As built (first slice).** The contract keys are `before`/`after`; on a resource they are the fields `run_before`/`run_after` (and `provides`). Failure rules: the first failed step skips every later item on that host with "earlier failure on this host: <what>"; triggers still run for what changed before the failure; a failed trigger stops the remaining triggers; verify still runs. The health check runs only after restarts (`restart(unit, check=False)` opts out). daemon-reload is a trigger that runs before the restarts.

**Ordering knobs**
- **`wants` (block side).** A block lists capabilities it wants done first. The packages block declares `wants: package-manager`; roles that configure a package manager tag themselves `provides: package-manager`. Their entries run just before the block's own entries. If nothing provides it, nothing happens, which fits settings that are mostly optional. The knowledge "package manager config comes before installs" lives once, in the block.
- **`before:` / `after:` (entry side)** names a block: the entry runs in the slot just before or after that block's normal slot. It works on an entry of any block, and it says why in words you already use. Example: a user created by hand before packages that would create it is `users: [{name: svc, before: packages}]`. The slots are totally ordered, so it can never create a cycle.
- **Long-term goal: infer the order from references.** Bastet should work out most orderings from what entries mention (a file owned by `svc` implies the user first; a service `Requires=` another). `before:`/`after:` then remain as the explicit override. Not built in the first slice.
- **No ordering inside a phase.** Starting an app unit pulls in the units it `Requires=`, so systemd already orders services. Revisit only if restart order turns out to matter.

### Across hosts
A role that `needs` something another host provides, such as an app that needs a database on another machine, waits for that whole host. This builds on what exists: the parallel runner can already make one host wait for another (guests wait for their node).
- **Resolution.** `needs: database` is matched to the host whose assigned roles `provide: database`. The match becomes a host-level dependency. Two providers is an ambiguity: the role asks for an explicit choice (an option naming the host). No provider is an error naming the role and the host that needs it (or an offer from `add role`).
- **The wait is for the whole host.** The dependency host must get all the way through apply and verify, successfully, before the dependent host starts applying. If it failed or was skipped, the dependent is skipped with a reason such as "its database host db1 failed" (as guests are today). Independent hosts still run in parallel.
- **Check stays parallel.** It only reads, so every host checks at once; a dependent whose provider has not been built yet reports that plainly.
- **Cycles** (a needs b, b needs a) are found before anything runs and reported, as `runs_on` cycles are today.
- **Information flows too.** The dependent reads what the provider exposes (address, port, a generated credential) as `needs.database.host` and so on, taken from the provider's resolved options, so nothing is typed twice.
- **A guest always goes after its host system.** This comes from `runs_on`, not from `needs`/`provides`, is the same whole-host wait, and already works. It applies when both machines are in the same run: running just the guest does not wait for a node you did not select, which is assumed to be built already.
- **Reboots are a separate problem, parked.** A node reboot takes its guests (and anything that needs it) down with it. That is the reboot plan (earlier spec §7.6) and stays with the infrastructure roles, not this work.
- **Not built in the first slice.** The `needs`/`provides` keys are reserved and ignored. The existing guest-after-node wait keeps working untouched. A finer wait (the app continues until the step that needs the database) is possible later and is not needed.

## 5. Roadmap

1. **First slice:** the draft contract, the generic builder, `files` settings (`edit: ini`), `before:`/`after:`, `wants`/`provides`, the phase engine with `daemon-reload` and the health check, and pacman as Markdown-only. Done when pacman has no Python, every existing pacman test passes unchanged, and `check` output on an Arch host is identical. Replaces subplan 3, parts of 2 and 4, and the pacman part of 6.
2. **Evaluate**, then convert **one role at a time**, every one as straight Markdown. Suggested order: ssh (many options; `edit: sshd` with its `sshd -t` check, and a few `warn` rules for obvious ways to lose access, such as turning off key logins), base (`when:` for microcode), harden, systemd (time, hostname, locale), the thin `users` and `files` roles, `packages` (the heavy one: AUR, updates and reboot policy become block features), proxmox (repositories, tools and the file patch through the blocks). Each conversion adds only the block or contract features it needs (`when:`, `validate:`, templates, timers, `edit: kv`/`sshd`, and so on).
3. **Capabilities and contributions** beyond `wants`, when a real role needs them: the firewall (same-host contributions), then the Git forge (cross-host: database, runner, proxy). The reserved keys `uses`, `needs`, `provides`, `contributes` are parsed and ignored until then.
4. **Stabilize last:** the library, `role update`, `doctor <dir>` and role pages (the audited subplan 2 tasks 2 to 6), then presets, boards and the guided `add role` (subplan 5).
5. **Unchanged:** infrastructure roles (Proxmox node setup, ZFS, guests, firewall, podman) and the reboot plan and power control that go with them; secrets part 2; app roles; the orchestrator; removal; the trust prompt; turning git off.

## 6. Versioning

- **Bastet releases:** `0.x`, written in one place (`pyproject.toml`; `bastet --version` reads it) and bumped at each milestone. No git tags and no release machinery for now. Pre-1.0, a minor bump may break things. 0.2.0 marks run logs done.
- **Role versions:** semver per role in its contract. Major means an option was renamed or removed or behaviour needs attention; minor adds options; patch is fixes and docs. The content hash (`source_hash`) is the machine signal that something changed, so the version is only the human one and no tooling enforces bumps.
- **Contract version:** `api: N`, an integer that changes only for a breaking change to the role format or engine API. It is `0` (a draft, no promise) until the first outside role exists, which is about 1.0. After that, Bastet supports the current and the previous number for one release, with a warning from `doctor`.
- **Inventory format** is a fourth axis, and stays unversioned until 1.0 ("Bastet isn't stable", no migrations).

## 7. Reserved and deferred

**Reserved keys are provisional.** `uses`, `needs`, `provides`, `contributes` and `collects` are accepted in a role's contract but have **no effect** until they are implemented, and their names and shape may still change. They are not enforced or validated beyond being readable, so a role that sets one behaves as if it had not. (The one exception in the first slice: `wants`, and the same-host `provides` tag it reads, such as pacman's `provides: package-manager`, are built and active. Cross-host `provides` and `needs` are not.) No code should rely on a reserved key until its feature lands.

Role calls role (`uses:`), hard `needs`, cross-host `needs`/`provides`, `contributes`/`collects`, ordering inside a phase, backups of replaced files, removal, the `role.py` trust prompt, proxy and DNS roles.

## 8. Open questions, to settle during the first slice
- Which format checkers and `edit:` formats the first slice needs beyond `ini` (ssh will need `sshd` with `Match` blocks).
- How rich the expression language in `when:` and `validate:` is allowed to be (a small Jinja subset over option values and facts is the starting point).
- Whether the thin `users`, `files` and `packages` roles stay once three or more roles are converted.
- Whether restart order ever needs more than systemd's own dependencies.
