# Bastet roles redesign

**Status:** design, approved in conversation 2026-10-06. To be audited independently before planning.

**Relationship to the main spec** (`2026-09-30-bastet-design.md`): this document wins where they differ. It replaces:
- §9.1, the role contract in `role.yml`, the curated options + `settings` pass-through tier, and the `roles/<name>/{ansible,native}` layout;
- §9.4's role-based execution order within a host;
- the parts of §5.3 and §7 that put gathered facts in host notes, and the attribution machinery that existed for that;
- §8's description of guest creation through "the existing Proxmox creation roles".

It keeps:
- desired state first (§9.0);
- precedence (§5.4);
- cross-host dependencies and exposure (§9.3);
- versions and update policy (§9.5, §9.6), refined below;
- secrets (§15);
- the rule that removal is explicit and later work.

Everything here is v1 unless marked **deferred**.

## 1. Goals

- **Anyone can write a role,** in Markdown, with optional Python. Roles contributed upstream can be bundled.
- **A role exposes every option** of the thing it manages, named the way upstream names them.
- **Adding a role is trivial,** because shared behaviour lives in generic building blocks: versions, hardening, OS differences, secrets, ordering.
- **A lab's inventory is self-contained:** the roles it uses are copied into it.
- **Readable in Obsidian:**
  - role pages are documentation;
  - presets can be assigned on kanban boards;
  - host notes hold only what you decide;
  - gathered facts live in Bastet's own notes.

## 2. Where things live

| What | Where | Written by |
|---|---|---|
| Host identity (type, address, groups, `runs_on`, location, `connection`, `gather`, guest settings) and your notes | `hosts/<host>.md` | you |
| Gathered facts | `_bastet/facts/<host> facts.md` (`host: "[[<host>]]"`) | Bastet only |
| Per-host reports from roles | `_bastet/reports/<host> reports.md` | Bastet only |
| Role files (which roles apply where, with which preset and values) | `_roles/{lab,groups/<g>,hosts/<h>}/<role>.md` | you, or `add role` |
| Your presets | `_roles/presets/<role>/<name>.md` | you |
| Role definitions the lab uses (the copies that run) | `_roles/library/<role>/` | `add role` and `role update` |
| Role sources | bundled (Bastet's app data dir), `~/.config/bastet/roles/`, a folder set in `bastet.yml` | role authors |

- **Folders must not start with a dot.** Obsidian doesn't index dot-folders, so Bases, links and embeds couldn't see them.
- **No migration tool.** Bastet hasn't been declared stable. Existing inventories are re-gathered, and old keys are tidied out of host notes by hand.

### 2.1 Host notes and facts

- **Bastet never writes to `hosts/<host>.md`.** Gather writes the facts note, and Bastet-generated views are embedded, not stored.
- **Declared versus observed is explicit.** A value you set on the host note (e.g. a fixed `ip`) that differs from the facts note is drift (main spec §7b), reported the same way as before.
- **Attribution and `--take` shrink to what's still needed.** They existed to share one note between you and gather.
- **A guest's settings live on its own host note:** cores, memory, disks, OS template, network. For a guest, that *is* its identity, the way hardware is for a physical machine. The host type (`lxc`, `vm`) defines and validates those fields, so they need no prefixes.
- **The host page embeds:**
  - the facts summary;
  - hardware;
  - the role files reaching the host (role, level, preset);
  - the resolved options table (each value and where it came from);
  - the reports note.

## 3. The role format

A role is a folder:

```
<role>/
  <role>.md        the contract (frontmatter) and documentation (body)
  templates/       Jinja2 templates
  role.py          optional Python
  tests/           optional plan tests (*.md)
```

### 3.1 The contract: frontmatter

The frontmatter is the whole machine contract. Bastet reads only this. Example, trimmed:

```yaml
---
bastet: role-definition
name: jellyfin
version: 1.2.0                  # semver: major = options renamed/removed or behaviour changed
api: 1                          # the bastet.blocks API version the role is written for
description: "Media server."
cssclasses: [bastet-role]
os: [arch, debian]              # flat lists, so Bases can show and filter them
os_min: {debian: 12}
types: [server, vm, lxc]        # or not_types: […]
requires:                       # conditions on gathered facts (Jinja expressions)
  - "facts.init == 'systemd'"
tags: [service, media]
needs:
  runtime: {kind: container-runtime, where: same-host, when: "install == 'container'"}
provides: [http]
contributes:
  firewall-port: [{port: "{{ http_port }}", proto: tcp, from: lan}]
data: [/var/lib/jellyfin]       # what removal would treat as data (removal is deferred)
vars:                           # role-internal names; not options, not user-settable
  pkg: {arch: [jellyfin-server, jellyfin-web], debian: [jellyfin]}
options:
  install:        {type: string, choices: [native, container], default: native, common: true}
  http_port:      {type: int, key: HttpServerPortNumber, section: network, common: true,
                   description: "Port the web UI listens on"}
  media_paths:    {type: list, items: {type: string}, common: true}
  hardening:      {type: string, choices: [relaxed, strict, off], default: relaxed}
presets:
  minimal: {…}
packages: "{{ pkg }}"
templates:
  - {src: network.xml.j2, dest: /etc/jellyfin/network.xml, owner: jellyfin, mode: "0640"}
units:
  - name: jellyfin
    enabled: true
    started: true
    access: {writable: [/var/lib/jellyfin, /var/cache/jellyfin], readable: ["{{ media_paths }}"],
             network: true, devices: [/dev/dri]}
hooks:
  after_files: [{run: "…", mode: changed}]
---
```

**Rules:**
- **Keep anything a Base may show as flat lists of plain values:** `os`, `types`, `tags`, `needs`/`provides` names. Options stay nested.
- **Every option for the managed thing is exposed.**
  - **Names** are upstream's setting names in snake_case (`PermitRootLogin` → `permit_root_login`; `[server] HTTP_PORT` → `server.http_port`). Each option records upstream's exact name in `key:` where the conversion isn't obvious.
  - **Unset means "leave upstream's default alone".** A contract `default:` is only for Bastet's own decisions (e.g. `install: native`, `microcode: auto`).
  - **`section`** groups options in the docs. **`common: true`** marks the handful most people touch; docs and pickers show those first.
  - **Big configs** have their option list generated from upstream's own reference for a given upstream version (a small generator config per role). There is no curated tier and no `settings` pass-through.
- **Shared option names** mean the same thing in every role, and building blocks implement them:
  - `install` (`native` | `container`);
  - `version`, `update_policy`;
  - `hardening`, `hardening_overrides`;
  - `expose`;
  - `extra_*`: adds to a list without replacing it;
  - `contribute: false`: opts out of contributions;
  - `preset` (in role files).
- **`vars:`** are internal. They're never options and never shown as options. Anything a user may want to change is an option.
- **OS differences** use one per-OS map form, usable anywhere: `{arch: …, debian: …, default: …}`.
  - Matching goes exact OS id, then family (from `/etc/os-release` `ID` and `ID_LIKE`; `debian` covers Proxmox VE unless a role names `proxmox`), then `default`.
  - No match and no `default` means unsupported. That must agree with `os:`, and `role check` verifies it.

### 3.2 The body: documentation

- The body is free-form: what the role does, why the defaults are what they are, examples, caveats, and a `## Changes` changelog.
- **The options section is either generated or hand-written.**
  - **Generated:** if the body contains the markers below, Bastet regenerates what's between them from the frontmatter, with one `### <option>` heading per option (so `[[jellyfin#http_port]]` links work), plus type, default, choices, upstream key and description.
    ```markdown
    ## Options
    <!-- bastet:options -->
    <!-- /bastet:options -->
    ```
  - **Hand-written:** without the markers, the author writes the section, and `role check` verifies every option is documented.
- **`cssclasses: [bastet-role]`** lets the stylesheet hide the raw nested properties, so readers see the documentation.

### 3.3 Templates and conditions: Jinja2

- **Full Jinja2** in template files and in frontmatter values. `when:` conditions are Jinja expressions.
- **Two settings, for correctness:**
  - `StrictUndefined`: a missing name is an error, never an empty string;
  - includes and imports resolve only inside the role's own folder, since that's what gets copied into the inventory.
- **Templates receive plain data only** (dicts and lists), through scoped names:
  - the role's resolved options, by name;
  - `vars`;
  - `host.<field>`: the host note;
  - `facts.<x>`: the facts note;
  - `roles.<role>.<option>`: another role's resolved option on this host;
  - `inventory.hosts`: read-only.

  There's no global variable namespace, so nothing needs prefixing.
- **Escaping is explicit:** `| quote` for shell, `| tojson`, a `| toyaml` filter Bastet provides.
- **Upstream style rule:** bundled roles keep templates simple (loops, conditions, common filters, no macro libraries), and computation goes in `role.py`. Local roles may do anything.

### 3.4 Python (`role.py`)

All of these are optional:

- **`validate(values, host, inventory)`** returns errors. It's for guards and rules across options, e.g. the ssh lockout guard, or "every `listen_address` port is in `port`". It runs at plan time, before any host is touched.
- **`build(values, host, inventory)`** returns extra resources, added to the declared ones. It's for logic templates can't express: choosing the NIC for `vmbr0`, microcode from the CPU vendor, a peer list built from other hosts.
- **New resource types,** as subclasses of `Resource` implementing read / compare / fix / verify. `read` and `fix` run commands on the host through the engine's runner. Multi-step procedures belong here:
  - a pool that is never recreated and refuses disks that aren't blank;
  - a bridge change with a rollback timer;
  - creating a guest.

  They appear in check like any resource ("tank exists, OK" / "would create tank" / "refusing: sdb has a partition table").

**No hard restriction.** `build` and `validate` may also use a host runner. The authoring guide spells out the costs:
- it runs during `check` as well, so it must not change anything;
- it isn't in the diff;
- it isn't masked unless the role calls the masker;
- it isn't covered by stop-on-failure.

Resources are the documented way, and upstream review enforces that for bundled roles.

**Public API.** `bastet.blocks` (the building blocks, `Resource`, host info, the inventory view) carries its own version. A role declares `api: N`, and a Bastet that no longer supports that version refuses the role with a clear message.

**Shell steps.** Plain shell commands as a role's main logic are allowed in local roles, but not accepted upstream. Hooks and `commands` are the sanctioned forms.

## 4. Where roles come from, and updates

- **Sources:**
  - bundled, in Bastet's app data dir, shipped with the install;
  - `~/.config/bastet/roles/`;
  - an optional folder set in `bastet.yml`.
- **The inventory copy is what runs, always.** Adding a role to a lab copies its folder into `_roles/library/<role>/`. Check and apply only use that copy, so a lab behaves the same on any controller.
- **A copy records its origin in its frontmatter:** `version`, `source` (`bundled` | `config` | `<dir>`) and `source_hash` (a hash of the files as copied).
- **When a name exists in several sources,** the first copy comes from: configured folder > `~/.config/bastet/roles` > bundled. After that the copy's `source:` sticks.
- **Updates are never silent.**
  - Check notes a newer source version ("ssh 1.5.0 available, you have 1.4.0").
  - `bastet role update [name]`:
    1. shows the contract diff: options added, removed or renamed; defaults changed; resources changed;
    2. runs a check with the new version, showing what it would change on hosts;
    3. copies it over and commits.
  - A major version that renames or removes an option you set is named with the file that sets it.
- **Editing the copy is allowed but detected** (the hash no longer matches). An update then becomes a three-way merge done by hand. The guideline is to customise through options and presets, or fork the role under a new name into `~/.config/bastet/roles`.
- **Trust prompt (deferred):** a role containing `role.py`, copied for the first time from a source other than bundled or your own folders, gets a one-time prompt naming the file.

## 5. Role files, presets and boards

- **Role files are unchanged in shape:** `bastet: role`, `role:` and `applies_to:`, plus option values. They gain:
  - **`preset: <name>`** (one, not a list).
    - The preset's values apply at that file's level, and the file's own values sit on top.
    - Precedence is unchanged (§5.4: role defaults < lab < host-type group < your groups < host).
    - Check shows each value's origin, e.g. `permit_root_login ← preset hardened (via _roles/hosts/vps1/ssh.md)`.
- **Presets:**
  - **shipped:** in the role's own `presets:`;
  - **yours:** `_roles/presets/<role>/<name>.md`, with values in the frontmatter and the reasoning in the body;
  - your preset overrides a shipped one with the same name;
  - preset names are lowercase with hyphens, so they survive kanban column handling.
- **Boards:** for each role with presets, Bastet generates a Base kanban over that role's role files, grouped by `preset`.
  - Cards are each place a decision is made: the lab file, group files, host files.
  - Dragging a card rewrites that file's `preset:`, and the next `check` shows the effect.
  - A host that only inherits has no card of its own. `add role` gives it one.

### 5.1 `bastet add role`

**Guided flow:**
1. **Pick targets:** hosts, groups or the lab; several are allowed.
2. **Pick roles,** filtered to those compatible with every target. Hidden ones are explained ("podman: not for proxmox").
3. **Pick a preset,** or none.
4. **Enter required options** not covered by the preset.
5. **Unmet needs are offered:**
   - "jellyfin with install: container needs a container runtime; add podman (default) or docker?";
   - nothing is ever added silently.
6. **Diff,** then write the role files, plus the role's copy into `_roles/library/` if it's new to the lab.

**Arguments:** `bastet add role ssh --to vps1 [--preset hardened]` does the same without asking.

## 6. Compatibility

- **Declared** in the contract: `os`, `os_min`, `types` / `not_types`, `requires` (Jinja expressions over facts).
- **Type** is on the host note, so it's checked immediately. OS and fact requirements are checked once facts exist.
- **Unknown facts:**
  - the role is allowed, with a note ("vps1: not gathered yet; jellyfin's requirements unchecked");
  - after gather, an incompatible role makes gather warn (on the dashboard and the host page);
  - **check and apply error for that host before anything changes**, while other hosts continue;
  - you resolve it by removing or narrowing the role file.

## 7. How a host's run works

### 7.1 Planning

For each host:
1. **Collect** the role files reaching it.
2. **Resolve** values with presets and precedence.
3. **Validate** types and compatibility, and run `validate()`.
4. **Render** declarations and templates.
5. **Run `build()`.**
6. **Merge contributions.**
7. **Produce one merged desired state.**

Identical items from several roles merge into one, with origins listed (`git ← base, gitea`). Conflicting items are an error naming both roles and files (main spec §9.0).

### 7.2 Contributions

- A role **offers items to another role's lists by kind** (`contributes:`), and the owning role **`collects:`** that kind.
- **They're merged at planning time,** so the firewall configuration is built once from every contribution and written once.
- **No collector on the host** means the contribution does nothing, with a quiet note.
- **Either side can limit it:**
  - the collector can refuse or narrow contributions with its own options;
  - a contributor can opt out with `contribute: false`.
- **Conflicts** (two roles, same port, different `from`) are an error naming both.
- **Contributions can't carry secrets.**

### 7.3 Order: by building block, not by role

All roles' resources run in **building-block phases**:

```
packages (repositories first, then installs, holds, updates) → [after_packages]
→ users → files → templates → [after_files] → [before_units]
→ systemd (units, drop-ins, timers, mounts, sysctl, modules, tmpfiles; enable/start) → [after_units]
→ commands, JSON state → triggers (restart/reload, once each)
→ [before_reboot] → reboot (policy; the reboot plan, 7.6) → [after_reboot]
```

- **The hard-coded role `ORDER` goes away.** On a host, needs/provides only drive what `add role` offers. Across hosts they drive order.
- **"Any failure stops the host"** still holds, at the first failed step. Report-only reads don't count.

### 7.4 Hooks

- Roles may attach commands to `after_packages`, `after_files`, `before_units`, `after_units`, `before_reboot` and `after_reboot`. They're discouraged, but available.
- **A failed `before_reboot` hook cancels that host's reboot.** The host is left flagged "reboot still needed". Example: the Proxmox node role uses `before_reboot` to record the running guests and shut them down cleanly (reverse start order, each with a timeout, never killed), and `after_reboot` to start those guests again (including ones not set to start at boot) and confirm each is running. A guest that won't stop in time fails the hook, so the node isn't rebooted.
- **Modes:**
  - **`changed`** (default): runs only when that role changed something in the preceding phase.
  - **`always`:** the author vouches it's idempotent. It's reported as *ran*, not *changed*.
  - **`check: <command>`:** runs when the check says it's needed. Check can predict it, and upstream prefers it.
- **`changed_exit: 2`** lets a hook report a real change.
- **Guideline:** "make X true" belongs in a building block, or justifies a new one. Hooks are for actions.
- Hooks are command resources: shown in check, stop the host on failure, and masked.

### 7.5 Across hosts

- A guest runs after its node, using the parallel runner's `after`. Independent hosts run in parallel. Real dependencies use needs/provides (main spec §9.3).
- Roles read other hosts through `inventory.hosts`, read-only.
- Proxy and DNS-style roles, which configure themselves from the whole lab and run last, are **deferred**.

### 7.6 The reboot plan

Before rebooting a host, Bastet builds a **reboot plan** that covers the hosts depending on it: any host that *needs* something this host *provides*, found through needs/provides (an NFS mount from it, for example). For each dependent:

| The dependent has… | Bastet |
|---|---|
| power control (IPMI, Redfish, Wake-on-LAN; 8.4) | shuts it down cleanly (its own guests first, through its hooks), reboots this host and waits for it, then powers the dependent on and waits until it answers over SSH |
| no remote power-on | doesn't power it off: stops what uses the shared resource and unmounts it before the reboot, then remounts and restarts it after. If that isn't possible (e.g. the share is a guest's root disk), it stops and asks |

**Rules:**
- **The whole plan is shown and confirmed before anything happens:** "rebooting pve1 also shuts down pve2 and powers it back on through IPMI".
- **Powering off another host needs that host's own reboot policy to allow it.** Otherwise Bastet asks, even under `-y` with `reboot: auto` on the rebooted host.
- **Never the controller:** Bastet never powers off or reboots the controller, or the host the controller runs on.
- **A dependent that doesn't come back** (power-on fails, or no SSH by the timeout) is reported loudly with its last known state. No endless retries.
- **Chains are followed in order:** dependents of dependents go down first and come back last.

## 8. Building blocks

Blocks are generic **mechanisms**. Specific things, and friendly menus over a mechanism, are roles.

| Block | Covers |
|---|---|
| packages | repositories and signing keys, install, hold, updates, reboot-needed marking |
| users | users, groups, authorized keys, sudoers drop-ins |
| files | file, directory, symlink, line, block; owner/mode; validate command before swap |
| templates | files rendered with Jinja2 from the role's `templates/` |
| systemd | units, drop-ins (incl. hardening from `access`), timers, `.mount` units, sysctl.d, modules-load.d, tmpfiles.d, hostname, locale, time; applied live |
| JSON state | APIs and JSON-speaking CLIs (8.1) |
| commands | a command with a check; also what hooks are |
| reports | read-only information roles expose as options (8.3) |
| power control | on / off / status through IPMI (`ipmitool`), Redfish or Wake-on-LAN; runs `on: host` (a host that can reach the management network) or `on: controller` (8.4) |

Triggers and reboot are end-of-run **phases**, not blocks; the reboot phase uses power control for its plan (7.6). Resources mark "restart X" or "needs reboot".

**Not blocks:**
- **Containers.** A podman role installs through Quadlet, so a container is templates plus systemd. A docker role is files plus a command.
- **The firewall.** An nftables role is a template plus a unit, and collects `firewall-port` contributions.
- **Friendly systemd menus.** The `systemd` role (time, hostname, locale), a mounts role and a sysctl role are roles over the systemd block.

### 8.1 JSON state

- **Read** with `http` (method + path, relative to a base URL) or `command` (stdout is JSON).
- **`find`** an object in a list by key.
- **Compare a subset of fields (`want`):**
  - values are normalised (`1` / `"1"` / `true`; list as set or ordered);
  - only the differing fields are shown.
- **Act** with `create`, `update` and (only when the role says so) `delete`, each over HTTP or as a command.
- **Write-only fields** (passwords) are sent but never compared.
- **Async APIs:** wait for the task (e.g. a Proxmox task ID) and fail with its log.
- **Auth** through `secret:` references, masked everywhere.
- **TLS:** self-signed certificates are pinned by fingerprint (like SSH host keys); never "skip verification".
- **Where it runs:** `on: host` (default; over SSH as `bastet`, with tokens passed on stdin) or `on: controller` (for cloud APIs).
- **Out of scope:** pagination and rate limits.

### 8.2 Hardening (services)

- **The role author declares `access`** on each unit: writable and readable paths, network, devices, capabilities. It's a fact about the app.
- **You set one option per role:**
  - `hardening: relaxed` (default) | `strict` | `off`;
  - `hardening_overrides: {Directive: value}` for single directives.
- **Bastet generates the drop-in** from the level, opening only what `access` lists.
  - **relaxed:** `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=full`, kernel tunables/modules/logs and control groups protected, `RestrictSUIDSGID`, `LockPersonality`, `RestrictRealtime`.
  - **strict** adds `ProtectSystem=strict`, `ProtectHome`, `PrivateDevices` unless devices are listed, syscall filters, address-family restrictions and dropped capabilities.
- **Container installs** get the equivalent from the same `access`: rootless, read-only root where possible, dropped capabilities, `no-new-privileges`.
- **Check reports each role service's exposure score.** Above the role's declared target is a warning.

### 8.3 Reports

- A role can expose extra information as options (e.g. the ZFS role's `drive_health: true`).
- **Reports are read-only:**
  - off by default unless cheap;
  - shown in check;
  - written to `_bastet/reports/<host> reports.md`, embedded on the host page;
  - never counted as a change;
  - never containing secret values.

### 8.4 Power control

- **Operations:** `on`, `off` (a clean shutdown first, a hard power-off only if a role explicitly asks), `status`.
- **Methods:** IPMI (`ipmitool`), Redfish, Wake-on-LAN. The method and address come from the machine's `oob:` details (main spec §5.3), and the credential from its `secret:` reference, masked everywhere.
- **Where it runs:** on a host that can reach the management network (`on: host`, the default), or from the controller.
- **Used by** the reboot plan (7.6), and later by roles.

## 9. Install methods and versions

- **App roles share `install: native | container`.**
  - **Bundled roles default to `native`** whenever possible (a distro package, else upstream's binary or repository), even when upstream recommends containers.
  - **`container`** prefers podman (docker is the alternative), rootless where supported.
- **`version` and `update_policy`** (main spec §9.5, §9.6) are implemented by the blocks, the same in every role:
  - **container:** `version` is the image tag; major-version jumps are held on `auto`;
  - **upstream binary or repository:** an exact pin;
  - **distro package:** `version` means *hold at the current version* (`IgnorePkg` / `apt-mark hold`), and `update_policy` decides whether the role's packages join package updates. Check reports newer versions.
- **Role docs say which install methods support a real pin.**

## 10. Secrets in roles

Main spec §15 applies unchanged: secret options are declared in the contract frontmatter (`secret`, `generate`, `source`, `rotate_every`, `rotation`), and role files reference them with `secret:`. Additions:

- **A template, hook or JSON body carrying a secret** is masked in all output and passed on stdin, never in a command line.
- **File modes are not forced** (the reading user varies by service). The file gets the role's declared owner and mode.
  - **A world-readable file** (read bit for "other") **carrying a secret** is a plan-time error naming the role and the file.
  - **A secret file with no declared owner or mode** is a `role check` warning, and an upstream requirement.

## 11. Guests

*Guest creation is a specific role, built on the blocks after the redesign's subplans; this section records its design.*

- **A guest is described by its own host note:** type `lxc` or `vm`, `runs_on: "[[<node>]]"`, and its settings.
- **The node's guest role** walks `inventory.hosts` for guests whose `runs_on` is that node, and creates them through Proxmox (Python resources and JSON state over `pvesh` or the API). Creation injects Bastet's SSH key (the LXC ssh-public-keys parameter, VM cloud-init) and reads the guest's host key through Proxmox, so nothing is trusted blindly (main spec §8).
- **First contact and bastet-user setup are part of the guest role itself:** pinning the host key it read through Proxmox, and setting up the `bastet` user and sudo. It's not a separate role. Existing hosts keep gather's first-contact path (main spec §8).
- **One apply creates and configures:**
  1. the node creates the guest;
  2. the guest role does first contact and sets up the `bastet` user;
  3. the guest's own roles run.

  Check shows "would create media01 on pve1" and lists the guest's roles as "pending creation".
- **Never recreate.**
  - Growing memory, cores or disk is a normal change.
  - Shrinking a disk or changing the OS template is refused, with a note on how to do it by hand.
  - Destroying a guest stays explicit (`state: destroyed`, main spec §8).

## 12. Removal (deferred)

- **v1:**
  - deleting a role file never uninstalls anything;
  - merged outputs rebuild from what remains (removing Jellyfin's role file drops its firewall port);
  - roles declare `data:` now.
- **Later:**
  - `state: absent`: the role's resources inverted, shown as a diff first;
  - `purge: true`: also removes data, and requires typing the host name, even with `-y`;
  - items other roles still want are kept;
  - a per-host record of what Bastet manages, with "no longer managed, left in place" reports.

## 13. Testing

| Level | What | Your roles | Upstream roles |
|---|---|---|---|
| Always | the contract parses, types are valid, the OS is claimed, templates render. Caught during check/apply. | enforced | enforced |
| `bastet role check <dir>` | options documented; per-OS maps vs `os`; templates render per OS and per preset; hooks declare a mode; units declare `access`; service roles declare `data`; `api` supported; unused `vars`; options no resource reads | opt-in | required |
| Plan tests (`tests/*.md`, `bastet role test`) | facts + values → expected resources or guard error | opt-in | required |
| Host tests (`bastet role test --hosts`, podman per supported OS) | apply, verify, re-apply = zero changes; exposure under target at strict and relaxed; presets apply. VM-only cases are marked and skipped. | opt-in | required where a container can test it |

## 14. Docs and pages

- **A role's page is its own `.md`** in `_roles/library/`. It replaces the generated `_bastet/roles/<role> role.md` copies.
- **The roles index** is a Base over the library: name, description, OS, needs, provides, tags, version, source, update available.
- **The authoring guide** is a document in the Bastet repo, also shipped into the vault. It covers:
  - the format;
  - shared options;
  - conventions (native first, podman, hardening, every option exposed, simple templates);
  - hooks;
  - Python and its costs;
  - testing;
  - upstream acceptance.

## 15. v1 scope and plans

**In v1:** everything above, except what's marked deferred:
- removal;
- the trust prompt;
- proxy and DNS roles;
- secret rotation (secrets part 2).

**Likely plans, in order:**
1. **Host-note split:** facts and reports notes; gather writes only Bastet's notes; host pages embed them.
2. **Role format and library:** the `.md` contract, the parser, sources, the inventory copy, `role update`, `role check`.
3. **Execution model:** merged desired state, building-block phases, hooks, contributions, needs/provides by kind, compatibility.
4. **New and expanded blocks:** templates (Jinja2), the systemd expansion, JSON state, reports, hardening from `access`.
5. **Presets, boards and the guided `add role`.**
6. **Convert the nine existing roles** to the new format, as the proof of the format.
