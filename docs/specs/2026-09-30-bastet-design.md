# Bastet — Design

Status: draft for review
Date: 2026-09-30
Replaces: `2026-09-28-bastet-redefined-design.md` (removed). This spec was designed from scratch; no earlier spec is an input.

**Status.** Chapters are **[firm]** where milestone 1 builds them, and **[draft]** (direction agreed, revisited at the milestone 1 decision point, chapter 13) otherwise:

- [firm]: 1, 3, 4, 5, 6, 7, the access and bootstrap parts of 8, 11.1–11.3, 14, 15 (storage, recipients, recovery key, redaction), 16.
- [draft]: creation and destruction (8), 9 (including import, 9.7), 10, 11.4, the commands in 12 beyond `init`, `add host`, `add hardware`, `show`, `gather`, `map`, `secret`.

**Read chapter 2 (the worked example) first.** It shows how using Bastet should feel. The chapters after it define what the example relies on.

Decisions marked *(chosen during writing)* were not discussed explicitly and are open to change in review.

## 1. What Bastet is

Bastet v1 is a **human-readable, Markdown-based inventory for Ansible**, plus a tool that works it for you:

- you write very small `.md` files for your hosts;
- Bastet gathers facts and writes them into those files, **after showing you a diff**;
- you add roles with the tool and see every option and default on the host page;
- `check` reports everything that differs between the files and reality (config, updates, container images, unaccounted packages, modified config files, hardware facts);
- `apply` makes it so, creating guests (Proxmox LXC/VM, Linode VPS) when a host doesn't exist yet;
- Bastet draws the network map and a dashboard for Obsidian;
- Bastet commits its own changes to git, so git is the history of the lab.

Ansible does most of the work underneath; you never run it directly. Roles that are easy to implement natively are native from the start (chapter 9). The goal is a fully human-readable view of the lab's software and hardware, where Bastet fills in the blanks and applies changes.

## 2. Worked example

The lab: `pve1`, a Proxmox node on physical hardware; `edge1`, a Linode VPS; `laptop`, the machine you work from. Later you add `git1`, an LXC on pve1. All names, addresses and serials are placeholders.

### 2.1 The lab file

`Homelab.md`, the dashboard, is also where lab-wide settings live:

```markdown
---
bastet: lab
cssclasses: [bastet-dashboard]
name: Homelab
domains:
  public: example.com
  internal: lab.example.net
timezone: America/New_York
acme_email: admin@example.com
proxy:
  public: "[[edge1/caddy]]"
networks:
  mgmt:    {cidr: 10.0.10.0/24, vlan: 10, purpose: [infrastructure], reserved: ".1-.9"}
  servers: {cidr: 10.0.20.0/24, vlan: 20, purpose: [apps], dhcp: ".100-.199"}
---
# Homelab
(embedded overview, chapter 11)
```

### 2.2 Minimal host files

You write these by hand, or with `bastet add host`:

```markdown
---
bastet: host
type: vps
provider: linode
ip: 203.0.113.10
---
# edge1
Public entry point.
```

```markdown
---
bastet: host
type: proxmox-node
ip: 10.0.10.11
location: "[[Closet]]"
---
# pve1
```

```markdown
---
bastet: host
type: laptop
ip: 10.0.10.50
---
# laptop
```

### 2.3 First gather

```console
$ bastet gather
pve1    host key SHA256:Qx3… (first contact) — trust? [y/N] y
        management login failed → bootstrap credentials ok
        bootstrapped: user 'bastet', key, sudo, python3
edge1   ok
laptop  ok (local)

hosts/pve1.md
  + hostname: pve1
  + os: Proxmox VE 9.0
  + cpu: 16 cores
  + ram: 128 GB
  + ssh_host_key: SHA256:Qx3…
hardware/ (new)
  + Supermicro chassis S123456.md     installed_in [[pve1]], oob: ipmi 10.0.10.9
  + WD Red 4TB WX12A3B4C5D6.md        installed_in [[pve1]]
  + Samsung 870 EVO S6PXNZ0T123456.md installed_in [[pve1]]
  + Intel X710 NIC.md                 installed_in [[pve1]]
hosts/edge1.md
  + hostname: edge1
  + os: Debian 13
  + ram: 4 GB
  + ipv6: 2001:db8::10
hosts/laptop.md
  + ...
Write? [Y/n] y
Committed: "gather: pve1 edge1 laptop — 3 hosts, 4 hardware files" (Bastet)
```

pve1 is a `proxmox-node`, so it's the only type that falls back to bootstrap credentials (chapter 8). edge1 was built with management access already in place.

### 2.4 A fact you set by hand

Months later, you edited `pve1.md` to say `ram: 128 GB` after a DIMM swap, but the machine now reports 96 GB:

```console
$ bastet gather pve1
pve1  ⚠ ram: file says 128 GB (set by Alice, 2027-01-12, commit a1b2c3 "DIMM swap")
         observed 96 GB — keeping yours. Physical hardware: check for a failed or unseated DIMM.
```

On an LXC, `ram` is a *desired* field, so the same mismatch would instead be a change for `apply` to make (chapter 6).

### 2.5 Adding a role

```console
$ bastet add role caddy edge1
+ hosts/edge1/caddy.md
Write? [Y/n] y
```

Caddy is a **collector** (9.3): it builds its sites from every service in the lab exposed through it (`proxy.public` in the lab file), so there's nothing to fill in. Manual `sites:` are only for things no role describes.

The roles table on edge1's page (a Bases view) now shows:

| role | from | option | value | source |
|---|---|---|---|---|
| ssh | type: vps | password_auth | false | default |
| hardening | type: vps | firewall | strict | group: internet-facing |
| users | type: vps | admin | you | lab |
| updates | type: vps | update_policy | security | group: internet-facing |
| caddy | host | collects | git.example.com → git1:3000 | exposed by git1/gitea |
| caddy | host | update_policy | auto | default |

That row appears once Gitea on git1 is exposed (2.6). `git.example.com` comes from Gitea's `expose.subdomain: git` and the lab's `domains.public`. `git1:3000` comes from the role on git1 that provides `http` (Gitea, port 3000; 9.3).

### 2.6 Adding an LXC (after the first slice)

Sections 2.6–2.8 include creating a guest as part of `apply`, which comes right after the first slice (chapter 13).

```console
$ bastet add host git1 --type lxc --on pve1
suggested network: servers (VLAN 20), ip 10.0.20.21 — next free, outside DHCP
+ hosts/git1.md   (type: lxc, runs_on: [[pve1]], network: servers, ip: 10.0.20.21, cores: 2, ram: 2 GB, disk: 16 GB)
$ bastet add role gitea git1
+ hosts/git1/gitea.md
```

In `hosts/git1/gitea.md` you set the exposure:

```markdown
---
bastet: role
host: "[[git1]]"
role: gitea
expose: {subdomain: git, domain: public}
---
```

### 2.7 Check

```console
$ bastet check
edge1   config      caddy: 1 site to add
        updates     14 packages (2 security)      policy: security
        unaccounted htop, tmux
        modified    /etc/ssh/sshd_config (owned by role ssh)
git1    missing     does not exist → would create LXC on pve1, then 5 roles
        secrets     will generate gitea/admin_password, gitea/secret_key
pve1    updates     pve-manager 9.0.4 → 9.0.6      policy: manual
        ⚠ ram 128 GB in file, 96 GB observed
laptop  unreachable (asleep)
Wrote hosts/*/status.md
Committed: "check: edge1 14 updates (2 sec), git1 missing, pve1 1 warning" (Bastet)
```

### 2.8 Apply

```console
$ bastet apply
secrets generated and committed: git1 gitea/admin_password, gitea/secret_key
git1    create LXC on pve1 (2 cores, 2 GB, 16 GB, debian-13, VLAN 20)
        roles: ssh, hardening, users, updates, gitea
edge1   caddy (collector, final phase): add site git.example.com → git1:3000
        updates: 2 security (policy: security)
Not applied (manual policy, use --updates): edge1 12 packages, pve1 pve-manager
Apply? [y/N] y
...
git1   created, 5 roles applied and verified
edge1  caddy ok, verify https://git.example.com 200
Committed: "apply: git1 created; edge1 caddy + 2 security updates" (Bastet)
```

### 2.9 In Obsidian

`Homelab.md` shows the lab at a glance: 4 hosts (3 reachable), one warning on pve1, 13 pending manual updates, `git.example.com → git1` under public domains, git1 nested under pve1, edge1 off-site at Linode, the spare-hardware count, and the last five Bastet commits. Each host page shows its roles table, its hardware, its status file and a small map.

## 3. Repositories and configuration

**Bastet repo** (public):

- the tool;
- host types (chapter 5);
- roles (Ansible and native, chapter 9);
- clean-install sets (chapter 10);
- the Obsidian CSS snippet, templates and docs.

Anyone can use or improve a role. Roles hold logic only; anything specific to a lab is an option value.

**Inventory repo** (private):

- the lab file, hosts, hardware, groups, locations, role option files, status files, maps;
- encrypted secrets;
- private clean-install sets;
- **user roles** in `roles/`: roles imported from an existing Ansible setup (prefixed `imported_`, 9.7) and any role too niche to publish.

Values only, never logic.

**Config** (`~/.config/bastet/bastet.yml`):

```yaml
inventory:
  remote: git@github.com:you/homelab-inventory.git   # optional
  path: ~/Homelab                                   # optional; your working copy (the Obsidian vault)
secrets:
  age_identity: ~/.ssh/id_ed25519
```

| Configured | Behavior |
|---|---|
| remote + path (laptop) | work in the working copy, sync with the remote |
| remote only (web server) | Bastet keeps its own clone in its data directory |
| path only | local, no syncing |

During milestone 1 the tool runs as `uv run bastet` from its repo, so the older CLI (and its `~/.config/bastet/config.yml`) keeps working.

**Where Bastet runs:** your laptop, and later an orchestrator LXC with the web UI. Either can do everything, so the orchestrator going down never locks you out. Host the inventory remote outside the lab (e.g. GitHub). A remote inside the lab has the same chicken-and-egg problem as the orchestrator.

## 4. Git handling

- **Pull** before every command, when a remote is set. If the remote is unreachable, Bastet continues on the last pulled state with a warning and holds its commits until it can push.
- **Your pending edits:** *(chosen during writing)* before a run, if files Bastet will read or write have uncommitted changes, Bastet lists them and commits them **as you** (your git identity), after asking. `--yes` does it without asking. This turns your edits into history that attribution can read (chapter 7), and stops Bastet's writes from colliding with unsaved work. Files unrelated to the run are left alone.
- **Bastet's commits:** Bastet commits only files it wrote, under its own identity (`Bastet <bastet@<machine>>`), with a message saying what ran and where. Status files hold only stable content (package names and versions, no "checked at" times), and a file whose content didn't change isn't committed, so an unchanged lab produces no commits however often it's checked. Everything stays on `main`.
- **Push** after committing.
- **A push conflict on a Bastet-owned file** (status files, maps) is resolved as "newer run wins". A conflict on a file you also edit stops and reports it; Bastet never merges by hand-guessing.

## 5. Inventory files

### 5.1 Recognition

*(Chosen during writing.)* A file belongs to Bastet if its frontmatter has a `bastet:` key: `lab`, `host`, `hardware`, `group`, `location` or `role`. Folders are a convention (below) and carry no meaning. Files without the key are ignored, so your own notes can live anywhere in the vault.

```
Homelab.md           lab file and dashboard
hosts/<host>.md      host files
hosts/<host>/        status.md
_roles/              role files (your values; tucked away, reached from the host and group pages)
  hosts/<host>/<role>.md   groups/<group>/<role>.md   lab/<role>.md
hardware/  groups/  locations/
_bastet/roles/       generated role reference pages
maps/                generated Mermaid views
_secrets/            one note per secret: <host>/<role>/<name>.md, <host>/<name>.md, lab/…
.bastet/build/       generated Ansible inventory (gitignored)
```

### 5.2 Frontmatter rules

- **Plain YAML only.** No comments, custom tags or anchors. Obsidian (1.13.7) rewrites a note's whole frontmatter block when any property is edited: comments are deleted, flow style becomes block style, and unneeded quotes are dropped (spike: `docs/superpowers/spikes/2026-09-30-obsidian-frontmatter.md`).
- **Bastet writes in Obsidian's style:** block style for maps and lists, minimal quoting, wikilinks quoted, new keys appended at the end. An Obsidian edit then changes only the edited value.
- **Dates are read whether quoted or not** (Obsidian's date picker writes unquoted YAML dates).
- **Bastet changes only the lines it must.** It adds or edits single keys and never re-serializes the whole block.

### 5.3 File kinds

- **Lab file:** lab-wide settings (domains, timezone, ACME email, proxies per domain, DNS providers, networks with VLAN, purpose and reserved/DHCP ranges, admin user, version pins…) and the dashboard body.
- **Host:** `type` plus that type's minimal fields; `ip` (a fixed address, or `dhcp` for machines that move around) and an optional `address` Bastet connects to when the IP isn't fixed (`laptop.local`, a DNS or Tailscale name); facts and desired fields (chapter 6); `groups`; `location`; `runs_on` for guests; `state` (`present`, the default, or `destroyed`); prose. The body embeds the host's views.
- **Hardware:** one file per chassis, drive, NIC, GPU, HBA, PSU…, with `installed_in: "[[<host>]]"` (or a location, for spares). The host is the hub, and the chassis is just another part pointing at it. `serial`, `model` and `size` are facts; `purchased`, `vendor`, `warranty_until`, `location` and notes are yours. Status: `in-service`, `spare`, `failed`, `retired`, `sold`.
  - **Out-of-band management** sits on the chassis (or the machine's main hardware file): `oob: {type: ipmi|idrac|ilo|amt|redfish|pikvm, address: …, url: …, credential: secret:…}`. The address is gathered where possible (e.g. `ipmitool lan print`) and goes through the gather diff.
  - **Links** (cabling) sit on the downstream end, on a host or hardware file: `links: [{port: enp65s0f0, to: "[[<switch>]]", to_port: "8", speed: 10G, note: …}]`. Each cable is written once, and switch-side views are derived.
- **Group:** a set of hosts that shares role files. Hosts join with `groups: ["[[internet-facing]]"]`. Groups can belong to groups the same way (nesting, as in Ansible `children`). A host type is a group too: every host is automatically a member of its type's group. An optional `priority:` number breaks ties between groups at the same level (5.4).
- **`ansible_vars:`** (host or group): a pass-through map of Ansible variables that no role option claims, handed to Ansible exactly as written. Mainly produced by import (9.7); shrinks as roles are migrated.
- **Role file:** `bastet: role`, `role: <name>` and `applies_to:` a link to a host, a group or the lab (`"[[Homelab]]"`). It lives tucked away under `_roles/` (`_roles/hosts/<host>/`, `_roles/groups/<group>/`, `_roles/lab/`); you reach it from the roles table on the host or group page, which lists every role reaching that page, including inherited ones and where they come from. `_roles/` holds your values and is separate from `_bastet/`, which only holds generated notes. The file is the switch: it puts that role into the desired state of every host it reaches. Its frontmatter holds only the options you set; defaults stay in the role's contract. A host that needs a different value than its group or the lab gets its own role file with just that option. Your notes about it go in the body.
- **Status file** (`hosts/<host>/status.md`): written by Bastet on every check (chapter 10); committed, so git holds its history.
- **Location:** where things sit, with an optional `parent` (closet → rack → shelf; Linode → region).

### 5.4 Precedence

Values and role assignments resolve lowest to highest, like Ansible's variable precedence:

**role defaults < lab < host-type group < your groups < host**

- **Nested groups:** an inner group wins over the group it belongs to (`laptops` inside `workstations`), as Ansible's child groups do.
- **Same level:** a group's `priority:` decides. If two groups at the same level with the same priority set an option to different values, it's an error naming both files. Bastet never picks silently (Ansible would go alphabetically).
- **Lists add up:** list options (e.g. `packages.install`) combine across levels instead of replacing each other, so a host adds one package without repeating the lab's list.

The host page's roles table shows every role, where it came from, and each option's value and source. Relative values, like `subdomain: git`, combine with lab settings (`domains.public`) into the value shown.

## 6. Host types

Types ship in the Bastet repo; you can add your own. v1: `proxmox-node`, `lxc`, `vm`, `vps`, `laptop`, `server`, and `unknown` (imported hosts whose type couldn't be inferred; gather offers the right type in its diff). UniFi types (`unifi-gateway`, `unifi-switch`, `unifi-ap`) follow after the slice.

Each type declares:

- **minimal fields**: what you must write (e.g. `vps`: `provider`, `ip`);
- **fields and their nature**:

| Nature | Meaning | File ≠ reality |
|---|---|---|
| **desired** | Bastet can make it true (e.g. `ram`, `cores`, `disk` on an LXC/VM) | a change for `apply` |
| **fact** | only gathered (e.g. `ram` on physical hardware, serials, OS version) | reported; a ⚠ warning on physical hardware (chapter 7) |
| **yours** | never observed (purchase info, notes) | never compared |

- **baseline roles** (e.g. `systemd`, `users`), with option defaults suited to the type. They act as the role files of the type's group (5.4): they beat the lab and lose to your groups and the host, so a type sets only the options it deliberately differs on (e.g. `proxmox-node` sets `systemd.ntp_service: chrony` and leaves `timezone` to the lab);
- **how it's gathered** (Ansible facts, a native gatherer, later the UniFi controller API);
- **how it becomes manageable** (chapter 8);
- **how it's created, if creatable** (chapter 8);
- **its clean-install set** (chapter 10).

**Comparing values:** facts and your values are compared after normalising units (sizes to bytes, speeds to bits per second, versions as versions), with small per-field tolerances where hardware reports oddly (RAM visible to the OS, drive marketing sizes). Gather writes values back in readable units; the type sets each field's display unit.

The same field can be desired on one type and a fact on another. A VPS's `ram` starts as a fact and can become desired later (Linode plan resize).

## 7. Gather and attribution

`bastet gather [hosts]` collects facts, computes changes to your files, shows them as one diff, and writes them after you approve (`--yes` when unattended). It can create hardware files. Discovered hardware that moves to another host updates its `installed_in`, and hardware no longer seen is reported, never deleted or re-statused automatically.

**Attribution.** When a *fact* in your file differs from what's observed:

- **Bastet was the last to set it:** the change is a normal update in the diff.
- **You were the last to set it:** Bastet **keeps your value** and tells you who set it, when, and in which commit. On physical hardware, it's a ⚠. The notice shows prominently the first time for each commit that set the value. After that, the mismatch sits in a standing list, "manual values that differ from reality", in the host's status file, visible but quiet.
- **Uncommitted, or history unavailable** (squashed, file renamed): treated as yours.

"Who set it" is **value history, not line blame**. For each field, Bastet finds the most recent commit in which the field's *parsed value* changed, and uses that commit's author. This survives Obsidian rewriting the frontmatter block and Bastet's own line edits.

`bastet gather <host> --take <field>` accepts reality for that field, which then becomes Bastet-maintained again.

**Desired** fields aren't gathered into the file. A mismatch appears in `check` as a change to apply.

## 7b. Drift [firm for reporting; resolution open]

The files are the source of truth. A difference between a **desired** or **yours** field and what Bastet
finds in reality (e.g. a guest's IP changed in Proxmox, a guest now on another node) is **drift**:

- It's reported inline (gather output), on the affected host's page (a Drift callout in its generated
  summary) and in the dashboard's "Needs attention". It's stored in the summary note, so it survives
  refreshes, and cleared only when a later gather finds file and reality in agreement.
- Bastet never changes the file to match reality on its own. Observed **facts** keep the gather rules of
  chapter 7 (Bastet-set facts update; hand-set facts are kept and attributed).
- **How drift gets resolved is undecided.** Candidates: accept reality explicitly (a `--take`-style
  command updating the file through a diff), restore the file's value (`apply`, milestone 2), or both.

## 8. Lifecycle: bootstrap, creation, destruction

**Access.** `bastet init` creates Bastet's SSH keypair (`~/.config/bastet/ssh/id_ed25519`, owned by the user). Remote hosts get a `bastet` user with that key and sudo. The controller is reached the same way when it is itself a target (the laptop, `connection: local`): over SSH at 127.0.0.1 as its own `bastet` user. sshd listening on 127.0.0.1 is enough. `bastet init` creates that local user (passwordless sudo through a validated sudoers drop-in, Bastet's key in its authorized_keys), offers to start sshd, and pins the local host key once confirmed. Until the `ssh` role is applied (e.g. `listen_address: 127.0.0.1`), stock sshd listens on every interface, so the first `init` and `apply` are best done offline. The orchestrator LXC (later) runs Bastet as a `bastet` system user.

**Existing hosts** are brought over by gather: it tries `bastet@host`; if that's rejected, it falls back to the user's own SSH login (ssh-agent and keys) and offers, as a confirmable change, to set up the `bastet` user (user, key, sudo, Python). Declining still gathers, as the user, with a reminder.

**Becoming manageable** is declared per type:

- **`proxmox-node`: credential fallback.**
  - Any command that connects tries the management credentials first. If they're **rejected** (authentication failure only; timeouts, refusals and DNS failures mean "unreachable"), it tries the host's bootstrap credentials.
  - If those work, Bastet creates the management user, installs the key, configures sudo and ensures Python, then carries on.
  - Bootstrap credentials are secrets: per host, falling back to per type (`bootstrap/<host>`, then `bootstrap/proxmox-node`).
- **`lxc`, `vm`, `vps`: manageable at birth.** The tooling that creates them sets up management access. There's no bootstrap step.
- **Other types** declare their own method when added. There's no fallback unless the type opts in.

**Host-key guardrails** (all SSH, and required for credential fallback):

- The host key is recorded as a fact (`ssh_host_key`) on first contact.
- **First contact:** an interactive run shows the fingerprint and asks. For guests Bastet created, it reads the key from the new guest through its parent (e.g. the Proxmox API), so there's nothing to trust blindly.
- **Key matches:** continue.
- **Key changed** (a reinstall, or a different machine at that IP): no credential fallback and no management. Bastet stops and reports. `--accept-new-hostkey` confirms a reinstall. Unattended runs only flag it.
- Every bootstrap is reported in the output and the commit message.

**Addresses for new hosts.** `add host` suggests a network and address; it never assigns one silently.

- **Network:** from the roles' `placement` (e.g. `[apps]`, `[cameras]`) and exposure (public adds `public`), matched against network `purpose` in the lab file.
- **Address:** the next free one in that network, skipping reserved and DHCP ranges, addresses used in the inventory, and addresses gather or UniFi have seen in use.
- Duplicate addresses in the inventory are an error naming both files; an address in use on the network but not in the inventory is a warning; a host whose roles want a different network is a hint in `check`.
- For guests, `network` is a desired field, so creation puts the guest on the right bridge and VLAN.

**Creation is part of `apply`.** A host of a creatable type that doesn't exist is created as the first step of `apply`, then configured:

- LXC/VM: through the existing Proxmox creation roles, run against its `runs_on` node;
- VPS: through Ansible's Linode modules.

`check` shows "would create". There is no `create` command.

**Destruction is explicit.** Removing a host file never destroys anything; `check` reports "exists but not described". Setting `state: destroyed` makes `apply` destroy the guest after you type its hostname to confirm. The file is then kept as a record, or you delete it.

**Nothing is removed by absence.** Deleting a role file makes the next check report "no longer managed, left in place".

## 9. Roles and execution

### 9.0 Desired state first (milestone 2, decided)

You think in **desired state**, not in roles or tasks. Three layers:

1. **Resources:** Bastet's building blocks (9.2): systemd settings and units, packages and repositories, files, users. Code only; you never write them in notes.
2. **Roles:** **menus of options** for the state of one specific thing (`systemd`, `packages`, `users`, `gitea`). Each option has a type, a default and a description; the role turns the values you pick into resources. Everything in a note is a role option: even a plain package list is the `packages` role. Typos and wrong types are therefore always caught.
3. **Desired state:** the merged result per host (5.4), after all role files reaching it are combined. Check, apply and every report work at this level.

**Role-managed state is not gathered.** Gather records what Bastet doesn't control (hardware, OS, addresses, guests). What a role controls is read live by check and shown in its diff, never stored in host files, so there are never two copies to disagree. Drift (chapter 7) therefore only concerns things Bastet observes but doesn't enforce; each role that takes something over shrinks that set.

**Several roles can want the same item** (gitea and a common setup both want `git`). Items are matched by identity: a package by name, a file by path, a unit by name, a user by username.
- The same desired state from several roles merges into one item. The report lists it once, with its origins as a footnote (`git ← gitea, packages`).
- Conflicting desired state (installed vs absent; two contents for one file) is an error before anything runs, naming both roles and files.

**Removing** a role file (or its `applies_to` link) removes that role from desired state and never uninstalls anything: check reports items only it managed as "no longer managed, left in place". Explicit removal (an option per role, shown in the diff first) is later work.

### 9.1 The role contract

Roles live in the Bastet repo. A role's **contract** is Bastet's own and independent of any backend, so moving away from Ansible never changes it:

```
roles/gitea/
  role.yml      the contract
  ansible/      an implementation: Ansible tasks/, templates/, handlers/
  native/       optional: a native implementation (Python)
```

`role.yml`:

```yaml
description: Self-hosted Git service
options:
  domain:      {type: string, required: true, description: "Public hostname"}
  http_port:   {type: int, default: 3000, description: "Port Gitea listens on"}
  rootless:    {type: bool, default: true}
  admin_password:
    type: string
    secret: true
    generate: {kind: password, length: 32}     # absent: Bastet may not generate it (issued, chosen)
    source: generated                          # what a new value usually is: generated | chosen | issued
    rotate_every: {generated: 180d}            # suggested; lab, host, host role file and the secret override it
    rotation:                                  # required for every secret option (15.6)
      method: two-step                         # two-step | direct | manual
      set: "gitea admin user change-password --username admin --password {{ next }}"
      verify: {http_login: {user: admin, password: "{{ next }}"}}
  version:        {type: version, description: "Pin a Gitea version; unset follows update_policy"}
  update_policy:  {default: auto}
  expose:         {type: expose}
placement: [apps]
provides:
  http: {port: "{{ http_port }}"}
needs:
  database: {kind: postgres, modes: [bundled, role, external]}   # 15.5: who owns the credential
consumes:                                      # rotation hooks for secrets other roles provide (15.6)
  database_password: {stop: [gitea], configure: database, start: [gitea], verify: {service: gitea}}
verify:
  - service: gitea
  - http: "http://localhost:{{ http_port }}/"
```

- `role.yml` is the **only source of truth** for options and defaults. Users, the roles table, generated role docs, dependencies and maps read only the contract and never know which backend runs.
- Bastet passes every resolved value to the implementation explicitly. For Ansible, it generates `defaults/main.yml` and `meta/argument_specs.yml` from `role.yml` into `.bastet/build/`, so Ansible's runtime validation works without a second hand-written copy.
- **Imported roles** (`imported_*`, 9.7) have no `role.yml`; Bastet builds a minimal contract from their `defaults/main.yml` (options and defaults, no types, descriptions or dependencies).

**App roles backed by a config file** (Gitea, Postgres, Jellyfin, Caddy's global options…) expose **every** setting without hand-writing them, in two tiers:

1. **Curated options** in `role.yml`: typed, described, used by dependencies and maps, and shown in the roles table.
2. **`settings`:** a pass-through onto the app's own config file, with flat dotted keys so frontmatter stays flat:
   ```yaml
   settings:
     server.LFS_START_SERVER: true
     mailer.SMTP_ADDR: smtp.example.com
   ```
   - The full list of settings is a **schema generated from upstream's own config reference** (e.g. Gitea's config cheat sheet and `app.example.ini`) for each supported app version, with descriptions and defaults. The role author writes only the curated tier and a small generator config.
   - Settings are validated against it. A key that's not in the schema (a brand-new upstream setting) is a warning and is passed through. Setting something a curated option controls is an error naming both.
   - Every setting is **visible**: each role on a host gets a generated view (e.g. `hosts/git1/gitea.settings.md`, embedded collapsed in the role file) listing every setting by section, with its effective value, default, whether you set it, and its description. It's regenerated only when the schema version or your values change.
   - The roles table stays compact: curated options plus the settings you've set.

The existing roles are reworked as they move into the Bastet repo. Container apps run through a **container runtime role**: `podman` by default, or `docker` where it stays, selected by an option (`runtime: podman`, `rootless: true`). An app role doesn't change when its runtime does.

### 9.2 The engine (milestone 2, decided)

Research: `docs/research/2026-10-01-execution-engine-survey.md` (Ansible, pyinfra, Fabric and our own, compared from source). Decision: **Bastet's own engine, in pyinfra's shape**, reusing gather's runner (OpenSSH, pinned host keys, `sudo -n`, one batched script per round trip). Logic for fiddly resources may be ported from pyinfra (MIT, with attribution); Ansible modules are reference only (GPLv3). Fabric adds nothing over the existing runner. Ansible stays as a backend for large existing roles (below).

**Connections.** A run makes several round trips per host (read, fixes, on-change, verify), so the runner multiplexes them over one SSH connection per host: `ControlMaster=auto`, `ControlPath=$XDG_RUNTIME_DIR/bastet/%C`, `ControlPersist=60s`, closed with `ssh -O exit` at the end of the run. The host key is checked and the `bastet` key offered once per host per run, so fail2ban and intrusion detection see one login, not dozens. Gather's existing options stay (`BatchMode`, `IdentitiesOnly`, pinned host key, `ConnectTimeout=15`, `ServerAliveInterval=15`), plus `ServerAliveCountMax=3` so a dead link fails within about 45 seconds.

**A resource** is the desired state of one thing on one host. Each resource type defines:
- **read:** shell commands plus a parser, run like gather's probes;
- **compare:** current vs desired → field changes, each with before and after values (pure Python, never touches the host);
- **fix:** the commands that make those changes;
- optionally a **validate** command run on new file contents before they replace the old (`visudo -cf`, `sshd -t`).

**First resource set:**

| Family | Resources |
|---|---|
| systemd | unit (enabled, running; start, stop, restart, reload, `daemon-reload`), drop-in config, timezone / NTP / hardware clock (`timedatectl show`, `set-…`), hostname (`hostnamectl`), locale and keymap (`localectl`). Grows to cover what systemd does (journald, resolved, networkd, timers, tmpfiles, sysctl, modules-load) as roles need it; accounts stay with the users family |
| files | file with exact contents, directory, symlink, line or block in someone else's file; owner and mode |
| packages | installed / absent for apt, pacman, dnf, zypper, apk; package repositories |
| users | user, group, authorized key, sudoers entry (validated file in `/etc/sudoers.d/`) |
| escape hatch | a guarded command: a command plus a check that decides whether it runs; always explicit |

Later, when a role needs them: sysctl, kernel modules, mounts, downloads and git checkouts, firewall rules, cron.

**On change.** Any resource can trigger an action when it changes (`on_change: reload chrony`, `daemon-reload`). Triggers are collected, deduplicated and run once after the role's resources, like Ansible handlers. Restarts and reloads always go through the systemd family, so every role shares one implementation and no role calls another.

**Templates.** Roles render file contents from Jinja2 templates (`roles/<role>/templates/*.j2`) on the controller, with strict undefined variables; the rendered text goes to the file resource. No Ansible filter set; filters are added when a template needs one.

**A run on one host:**

1. **Collect:** every role file reaching the host contributes resources; a role's own order is its dependency order (package, then config, then service).
2. **Read:** all reads in one script, one SSH round trip; root reads through the host's privilege method.
3. **Compare:** the report. `check` stops here. Something that doesn't exist yet reads as absent, so check can still say "would create".
4. **Apply:** only the fixes for changed fields, in order. A failing resource stops the rest of that host's run: nothing later in its role or in its other roles is applied. Triggers of changes that already succeeded still run, and the host is reported as failed. The failure is reported with the command's output.
5. **On change:** collected triggers run once each.
6. **Verify:** a second batched read. Anything not matching desired state is a failure, even if every command succeeded.

**Reports** are grouped by what's managed, never by role:

```
HOST: media01                         applied

Packages
  vim      missing → installed ✓
Services
  ssh
    state:   down → up ✓
Files
  /etc/motd
    updated ✓
      - Welcome to Debian
      + media01 · managed by Bastet
Hostname, curl, git, ssh enabled: compliant ✓

media01: 3 changed · 4 compliant · 0 failed
```

- Check shows `desired ≠ actual → <action>`; apply shows the outcome (`✓`, `✗` with the error output, `– skipped (reason)`, `✗ still down after start` when verify fails).
- File changes show a diff underneath; contents marked secret show only "changed (secret)".
- One host: every item. Several hosts: changes only, compliant items collapsed into one line per host. `-v` shows everything.
- A summary line per host and for the whole run.

**Contract test.** Every resource type and every native role passes: apply to a throwaway container, then apply again, and the second run shows no changes. A role must also check correctly on a fresh host.

**Privilege.** Milestone 2 uses `sudo -n` (present everywhere today), as gather does. How Bastet becomes root is a per-host setting from a later milestone (`become: sudo | run0 | doas | root`):
- `run0` (systemd 256+, not setuid, authorised by polkit) is the intended direction where a host qualifies. It needs polkit and a rule letting the `bastet` user manage units, which is as broad as `NOPASSWD: ALL`. Its non-interactive behaviour (piped script, exit status) is to be verified first.
- `doas` and `sudo-rs` are smaller drop-in alternatives.
- What matters most is scope, not the tool: key-only login, `from=` restrictions in `authorized_keys`, and later narrower rules, all set by the `users` role.

**Ansible implementations** remain for large existing roles (`ansible/` beside `role.yml`):

- Bastet resolves each host's roles and values (5.4), then **generates** an Ansible inventory, `host_vars` and a playbook into `.bastet/build/` (gitignored), regenerated on every run and left there for inspection.
- Secret values are never written there; roles receive them through a lookup that decrypts in memory at run time.
- ARA records the runs, and status files link to them.
- **Moving a role off Ansible:** add `native/` beside `ansible/`; while both exist, the contract test runs both against identical throwaway hosts and compares the resulting state. When they match, delete `ansible/`.

### 9.3 Dependencies

Roles declare what they **provide** and what they **need** (`role.yml`). In files, you link to a host or to a specific role on a host:

- `upstream: "[[git1]]"` resolves to git1's provider of the needed kind (here `http`: Gitea on port 3000) and becomes an address and port (git1's IP or DNS name). If git1 has more than one provider of that kind, you must name it: `"[[git1/gitea]]"`.
- **Ordering:** `apply` orders work so providers are applied before what needs them, across hosts. A guest that doesn't exist yet is created first in the same run. Cycles are an error listing the cycle.
- **Unresolvable:** a link to something not in the inventory, or to a host without a matching provider, stops the run **before any change**, naming the file and key.
- Dependencies are also knowledge: "what depends on git1?" and service arrows on the maps.
- Imported roles declare nothing; they keep working with plain values until migrated.

**Collectors.** Some roles configure themselves from the whole lab rather than from one host: the reverse proxy (from exposures), and later DNS. Their contract says `collects: expose`.

- Collectors run in a **final phase**, after every other step in the run, ordered among themselves by their dependencies (DNS after the proxy).
- A collector scans the **whole inventory**, not only the hosts in this run, for everything targeting it, plus any manual entries (e.g. Caddy `sites:` for things no role describes).
- An exposure whose provider doesn't exist yet, or failed earlier in this run, is left out and reported as **pending**; the next apply picks it up.

**Exposure.** The public and internal domains may be the same (split-horizon DNS): `public`/`internal` on an exposure then means who can reach it, not which zone it's in. The DNS collector writes both records for the same name (public → the public proxy, internal → inside the lab); internal-only services get only the internal one. App roles take a standard `expose` option: `{subdomain: git, domain: public|internal, auth: none}`. The lab file names the proxy for each domain (`proxy: {public: "[[edge1/caddy]]", internal: …}`), which a group or host can override. The dashboard's domains list and the logical map come from exposures. Two services claiming the same name on the same domain is an error naming both files.

**DNS (after the slice).** A DNS collector, after the proxy, creates one record per exposure (and optionally per host). Providers are plugins, named per domain in the lab file: Cloudflare for public names; for internal names, Pi-hole, the UniFi gateway or a local DNS server. Which internal provider is still open. It only touches records it created, tracked at the provider where supported or in its status, and reports records nobody describes any more instead of deleting them.

### 9.4 Execution order

A run is a graph of steps (*create guest*, *apply role on host*, *verify role on host*):

- **Within a host:** baseline roles in the type's declared order, then group and host roles, adjusted by provides/needs.
- **Across hosts:** a provider is applied **and verified** before anything that needs it.
- **Creation:** a guest is created before any role on it; its parent must be reachable.
- **Collectors:** a final phase (above).
- Cycles are an error listing the cycle.

**Running:**

- Unrelated hosts run in parallel (a few at a time, configurable); steps within a host run one at a time.
- Consecutive Ansible roles on a host whose dependencies are met run as **one** generated playbook; a native role between them splits the batch. Ansible handlers fire at each batch boundary, so services restarted by earlier roles are restarted before a native role that follows.
- Each role is verified right after it's applied.

**Failure:** the failing host stops; steps elsewhere that depend on it are skipped and reported ("edge1/caddy: skipped, needs git1/gitea which failed"); unrelated hosts carry on; collectors still run without the failed providers (shown as pending). The summary lists applied, failed, skipped and pending.

**Check** runs the same plan in check mode, so it shows the real order. A role whose check depends on an earlier, not-yet-made change is shown as "depends on earlier changes" rather than failing.

Output is the same whichever backend ran; Ansible batches link to their ARA record.

### 9.5 Versions

Any role installing something versioned takes `version:`.

- **Unpinned:** follows `update_policy`. Major version jumps on `auto` are held back and reported unless the role's contract marks majors as safe.
- **Pinned** (`version: 1.22.3`): changes only when you edit the pin, whatever the policy.
- `check` always reports newer versions, pinned or not.
- A pin can sit at any level (lab, group, host): "all Postgres stays on 16" is one line in a group.

### 9.6 Update policy

A role option, resolved through the usual precedence:

- `manual`: only applied with `apply --updates [roles]`. Default for base system, kernel and Proxmox.
- `auto`: applied on every `apply`. Default for container apps.
- `security`: security updates on every `apply`, the rest manual.

`check` tags each pending update with its policy.

### 9.7 Importing an existing Ansible setup

`bastet import --inventory <dir> --playbook <site.yml> [--roles <dir>…]` takes over an existing Ansible setup so it runs through Bastet **unchanged**, then lets you migrate role by role.

1. **Inventory → files.** Each host becomes a host file; each group becomes a group file, nesting kept. The type is inferred where possible (e.g. a group of Proxmox nodes → `proxmox-node`, container groups → `lxc`), otherwise `unknown`.
2. **Playbook → role assignments.** `import_playbook` is followed, and every play is resolved to which hosts get which roles, in which order:
   - a play targeting exactly one group becomes a role assignment on that group's file;
   - other patterns (`all:!pvenodes`) become assignments on the resolved hosts;
   - play keywords (`become`, `remote_user`, `gather_facts`) are kept with the assignment;
   - role order is preserved;
   - inline `tasks`/`pre_tasks`/`post_tasks` in a play are wrapped into a generated user role.
3. **Variables.** Each variable goes into the role file of the role whose `defaults/main.yml` declares it. Anything unclaimed goes into `ansible_vars:` on the host or group (5.3). Nothing is guessed or dropped.
4. **Roles are copied** into the inventory's `roles/`, **prefixed `imported_`** (`caddy` → `imported_caddy`). References between copied roles (`meta/main.yml` dependencies, `include_role`/`import_role` names) are rewritten to the new names. Role contents and **variable names are unchanged**. The roles table shows their options from `defaults/main.yml`.
5. **Secrets.** ansible-vault encrypted files and strings are decrypted once with the vault password and re-encrypted as secret notes under `_secrets/`; the variables become `secret:` references. The vault password isn't needed after import.
6. **Proof that it runs as-is.** Import ends by comparing the original with Bastet's generated output:
   - `ansible-inventory --list` for both, per host, every resolved variable (secrets compared by value, never printed);
   - each host's role sequence and play keywords under the original playbook vs. the generated one.

   Differences are shown. The import is only reported clean when both match.

Import is read-only on the source, and running it again against an unchanged source changes nothing.

**Migrating a role** means writing its `role.yml` and moving its tasks under `ansible/` in the Bastet repo. **Switching hosts over** is per host. `bastet add role caddy <host>` on a host that uses `imported_caddy` offers, in its diff, to move the values across (old variable names → the new role's options) and to remove `imported_caddy` from that host: a Bastet `caddy` and your `imported_caddy` coexist, so you switch one host to the new role (and move its values from `ansible_vars` or the old variable names to the new options), check, apply, and move the others later. `check` reports imported roles no host uses any more.

## 10. Check and status

`bastet check [hosts]` reports, per host, reusing existing tools:

| Category | Source |
|---|---|
| **config** | Ansible `--check --diff`, or native check |
| **missing** | the host doesn't exist yet: would create |
| **desired fields** | e.g. LXC `ram` 2 → 4 GB |
| **updates** | the package manager (`apt list --upgradable`, `checkupdates`, Proxmox) |
| **images** | registry digest vs. running container (`podman auto-update --dry-run`, skopeo for Docker) |
| **unaccounted packages** | explicitly installed packages (`apt-mark showmanual`, `pacman -Qe`) minus the clean-install set minus packages the host's roles install |
| **modified config files** | the package manager's verification (`pacman -Qkk`, `dpkg --verify`), cross-referenced with files roles manage |
| **facts** | fact mismatches, ⚠ on physical hardware; the standing list of manual values |
| **unmanaged** | exists but not described (guests, roles removed) |

Results are written to each host's `status.md` and committed, so git is the history ("when did this start"). Unreachable hosts (a sleeping laptop) are reported as unreachable, not as errors.

**Clean-install sets** live in the Bastet repo, keyed by **install source** (`debian-13/linode`, `debian-13/pve-lxc-template`, `proxmox-ve-9/iso`, `arch/archinstall-minimal`). A type names its default set, and a host can override it.

- `bastet baseline capture <host>` records one from a fresh install into the private inventory; a private set with the same name overrides the shipped one.
- `--export` writes a clean file (package names only) to contribute to the Bastet repo.
- These are distinct from **baseline roles** (chapter 6).

## 11. Views

### 11.1 Dashboard

`Homelab.md` is your file. Bastet never writes into it; its body embeds generated files and Bases views. It shows:

- counts by type and reachability; warnings; pending updates by policy;
- hosts by location, with Proxmox guests nested and VPSs off-site;
- domains: every public and internal name, what it points at, which host serves it;
- main services (compact);
- hardware: spares, ⚠ items, warranties ending soon;
- out-of-band management addresses for every system that has them;
- the last N Bastet commits;
- mini maps linking to `maps/`.

A CSS snippet shipped with Bastet (cards, status badges, grid, light and dark) is installed into `.obsidian/snippets/` by `bastet init` and applied through `cssclasses`. The visual design is done in its own pass, in Obsidian, with the user.

### 11.2 Host and hardware pages

- **Summary:** each host and hardware page embeds a Bastet-generated note, `_bastet/summary/<page> summary.md`, right under its title. It shows a grid of stat cards (CSS snippet) like the stage 0 mockup.
  - **Host:** OS, CPU, RAM, storage, network and type; Machine and Out-of-band for physical hosts; Guests for Proxmox nodes.
  - **Hardware:** cards suited to the category.
  - **Warnings:** the host's warnings from its last gather, stored in the summary note's frontmatter so they survive refreshes.
  - The summary is deterministic (no timestamps).
- **Hardware:** a Base (Table tab first, then Cards) listing hardware whose `installed_in` is the page.
- **Roles (milestone 2, decided):**
  - **Applied roles:** a Base on the host page (and on each group page) over every role file reaching it, its own and inherited (its groups' and the lab's), with columns role, from (host, group or lab, linked to the role file), the values set, and a link to the role's reference page. You never need to browse `_roles/`; you click through from here to edit values.
  - **Role reference pages:** one generated note per role, `_bastet/roles/<role>.md`, from its `role.yml`: what it does, every option with type, default and description, the full settings list for app roles, and which hosts use it with where each value comes from.
  - **Available roles:** a Base over the reference pages.
  - Adding a role: create a role file in Obsidian, or `bastet add role <role> <host|group|lab>`, which asks for required options and shows the file as a diff first.
- **Refresh:** `bastet refresh` regenerates every summary note and the dashboard from the files, without contacting hosts. `show`, `add` and `gather` refresh too. Only `_bastet/` files are written automatically, committed as `refresh: …`. Edits to the user's pages (embedding a summary under the title) go through a confirmed diff.

### 11.3 Maps

Mermaid diagrams in `maps/`, regenerated by `bastet map` and after gather and check, and committed. Views can be filtered (`bastet map cabling --around pve1`).

- **virtual**: Proxmox node → guests; VPSs separate;
- **logical**: VLANs and subnets, hosts on each, IPs;
- **physical**: locations → racks and shelves → machines, spares included;
- **cabling**: port → switch port, speed, PoE, uplinks (from `links:` you write, gather data, LLDP, and later UniFi);
- **overlay**: WireGuard, Tailscale, Nebula and Teleport peers and tunnels.

Discovered cables and ports go through the gather diff like any other fact.

### 11.4 Web UI (after the slice)

Runs on the orchestrator LXC with a remote-only inventory, on the same core. It shows the dashboard, host pages, status, maps and history (from git), and triggers gather, check and apply. **Whether it edits files is left open** until it exists. If it needs speed, a database is added as a cache built from its clone; it's never the source.

## 12. Commands

Few verbs; options over sibling commands. Every command pulls first and commits and pushes what Bastet wrote.

| Command | Does |
|---|---|
| `bastet init` | Config, age identity, Obsidian snippet |
| `bastet add host [name] [--type …] [--on <node>]` | Writes a minimal host file; asks for anything not given (type from a list, then the type's fields; `connection: local` for the computer Bastet runs on) |
| `bastet add role <role> <host\|group\|lab>` | Writes a role file after asking for required options and showing it as a diff |
| `bastet add hardware <name>` | Writes a hardware file (e.g. a spare) |
| `bastet show [name]` | Lists the inventory and any problems, or one object with what links to it |
| `bastet gather [hosts] [--take <field>] [--yes]` | Facts → diff → write (chapter 7) |
| `bastet check [hosts]` | Everything that differs → status files (chapter 10) |
| `bastet apply [hosts] [--updates [roles]] [--yes] [--accept-new-hostkey]` | Create if missing, configure, update per policy, verify, destroy if `state: destroyed` |
| `bastet map [view] [--around <host>]` | Regenerate maps |
| `bastet secret set\|view\|edit\|rekey\|rotate\|audit` | Secrets (chapter 15) |
| `bastet baseline capture <host> [--export]` | Clean-install sets |
| `bastet import --inventory … --playbook … [--roles …]` | Take over an existing Ansible setup (9.7) |

**The laptop is both controller and target.** When a target is the machine Bastet runs on, Bastet still connects over SSH, at 127.0.0.1, and never reboots it. It refuses changes that would remove its own access (e.g. disabling the key or user it connects with).

**Many hosts at once.** `gather`, `check` and `apply` work on up to `parallel.jobs` hosts at once (`--jobs`/`-j`, default 8). Questions come first (or last, for reboots), one host at a time; the work runs in parallel and each host's output is printed as one block. `apply` checks every host, then asks once for the whole run (all, none, or chosen hosts). A guest waits for its node and is skipped if the node failed; a node reboots only after its guests. Ctrl-C starts no new host and stops running ones at their next change.

**Unattended runs** (the orchestrator) use `--yes`. They never trust a new host key, never fall back to bootstrap credentials after a key change, and never destroy anything.

## 13. Build order

> **Superseded for status and order by `docs/ROADMAP.md`.** This section is kept as the original plan.

Each stage gets its own implementation plan and branch.

### Milestone 1: See your lab [firm]

Goal: get inventory in, both by importing an existing Ansible setup and by fresh start, and see it in Obsidian. Nothing in milestone 1 changes a host's configuration, except the Proxmox bootstrap user.

**Stage 0: Groundwork.**
- A new `bastet` repo layout (tool, types, clean-install sets later, docs) and a fresh private inventory repo.
- Config (`inventory.remote`, `inventory.path`).
- An Obsidian spike: Bases filtering on links to the current file; whether editing one property through Properties or Bases rewrites the rest of the frontmatter block; comments, quoted dates, lists of maps. The results may tighten 5.2 and 11.2.

**Stage 1: Inventory files.**
- Reading and validating every file kind (5) and host types with field natures (6); wikilink resolution; duplicate names.
- Writing frontmatter in Obsidian's style (5.2); every write shown as a diff and confirmed.
- `bastet init`, interactive with defaults (every question also a flag; `--yes` takes the defaults): inventory location, git remote, Bastet's SSH key (generate or use an existing one), the user's login for setting up existing hosts, lab name and domains, the Obsidian stylesheet. The config file location is fixed (`$BASTET_CONFIG`, XDG, `~/.config/bastet/bastet.yml`), not asked.
- `add host` (with address suggestions), `add hardware`, `show`.
- Git handling (chapter 4).

**Stage 2: Gather.**
- Gather for `vps`, `proxmox-node`, `laptop`, `lxc` and `server`: Bastet's own collector, **no Ansible and no Python needed on the target**. The tools come from the survey in `inv.sh`/`inv2.sh`; Bastet calls each tool itself over SSH (at 127.0.0.1 for the controller), prefers JSON output (`lsblk -J`, `ip -j`, `smartctl -j`, `hostnamectl --json`), has a parser and tests per tool, and keeps the raw output as the snapshot. The stage plan compares the tool list against Ansible's fact gathering and fills the gaps. Then diff-then-write, hardware files, unit normalisation.
- Host type proposal from systemd's chassis type (`hostnamectl`; `/sys/class/dmi/id/chassis_type` fallback) plus markers such as `pveversion` (proxmox-node) and the DMI vendor (VPS providers).
- Value-history attribution, ⚠ on physical facts, `--take`.
- Access (8): connect as `bastet` with Bastet's key; on rejection fall back to the user's own SSH login and offer, as a confirmable change, to set up the `bastet` user (user, key, sudo, Python); host-key recording. Credential fallback for fresh `proxmox-node` installs (age-encrypted secret notes, recovery key).
- The laptop gathered over SSH at 127.0.0.1, as its local `bastet` user.

**Stage 2c: Hardware completeness.** Anything physically removable gets its own hardware file; anything built in is listed on its parent.
- Own files: CPUs, memory sticks, PSUs (`dmidecode` type 39 and `ipmitool fru`) and removable USB devices (from `/sys/bus/usb`), in addition to machines, drives and add-in cards. Matched by serial; a placeholder serial falls back to host + socket/slot/bus.
- Listed on the machine file: integrated GPUs (`gpus`), built-in USB devices (`usb`), onboard ports.
- Firmware on the machine file: BMC firmware (`ipmitool mc info`), CPU microcode, TPM version, boot mode and Secure Boot. NIC firmware is on each port entry, and drive firmware on drive files.
- Each physical port gets `max_speed`: its highest supported link mode, from `ethtool`. It doesn't churn.
- Host files get `bridges`, `bonds` and `vlans` from `ip -j -d link`. Guest tap/veth ports are left out.
- Every host file carries `gather: true` explicitly, so the skip switch is visible and editable in Obsidian.
- `ethtool` joins the tools gather may install on physical hosts.

**Stage 3: Views.**
- `Homelab.md` dashboard and the CSS snippet, designed with the user in Obsidian.
- Host pages: roles table, hardware, facts, mini map.
- Maps: virtual, logical, physical.

**Decision point.** The user runs milestone 1 against the old Ansible inventory and a few fresh starts and judges the files and dashboards. The [draft] chapters are revisited, and the spec revised if needed, before milestone 2 is planned.

### Milestone 2: Desired state and the engine [firm]

Revisited after milestone 1 (9.0, 9.2). Ansible import is deferred; the first roles are new native ones.

1. **Stage 3a, the engine:** resources (9.2 first set), on-change triggers, Jinja2 templates, the six-phase run, check/apply reports (root through `sudo -n`), the contract test harness against throwaway containers.
2. **Stage 3b, roles:** `role.yml` contracts, role files at host, group and lab level, precedence and list merging (5.4), item merging and conflicts (9.0), reference pages and the Applied/Available roles views, `bastet add role`, `bastet check`, `bastet apply`.
3. **First roles:**
   - **`systemd`:** the settings systemd owns, in one role.
     - **Services:** `services: {<unit>: {enabled, state}}` for units you want in a given state. Another role wanting the same unit merges with it (9.0).
     - **Time:** `timezone`, `ntp`, `ntp_servers`, `fallback_ntp_servers`, `rtc_local`, `ntp_service` (`timesyncd` | `chrony` | `keep`; lab default `timesyncd`, `proxmox-node` default `chrony`, needed for clustering). `timedatectl` sets the timezone, hardware clock and NTP on/off (falling back to enabling the detected unit directly, and reporting which path it used). Servers go in a Bastet-owned drop-in (`/etc/systemd/timesyncd.conf.d/bastet.conf`, or `/etc/chrony/sources.d/bastet.sources`), and the service is reloaded only on change; verified with `timedatectl show-timesync` / `chronyc -c sources`. On LXC only the timezone applies (the clock belongs to the node).
     - **Hostname:** `hostname:` is always present in the host's frontmatter, even when redundant: `bastet add host` writes the note's name, and gather fills it in once with the machine's current hostname where it's missing (through the usual diff). From then on it's desired state, not a fact: a mismatch is a change for apply (`hostnamectl`), and gather never overwrites it. The note's file name is the fallback when the key is absent. Skipped on LXC, where Proxmox sets it from the container's config.
     - **Locale:** `locale`, `keymap` (`localectl`).
     - Without systemd (Alpine): timezone through `/etc/localtime` and `/etc/timezone`; the rest reported unsupported.
     - Later, in the same role: journald, resolved, networkd, timers, tmpfiles, sysctl, modules-load. Accounts (`sysusers`, `homed`) stay with `users`.
   - **`packages`:** `install` (and later `remove`), per package manager. Existing hosts carry many packages no role or baseline accounts for, so recording what's installed and capturing clean-install baselines (chapter 10) follow right after this role, making that drift visible early.
   - **`users`:** users, groups, keys, sudoers; locking down the `bastet` account.
   - **`files`:** files you want on a host, with contents written in the role file or from a template, plus owner and mode.

### Milestone 3 and later [draft]

In rough order:

0. **Network design (first, right after milestone 2).** The user designs the network in the vault by hand: the UniFi gateway replacing the ISP gateway, switches and APs with what's on which port (`links:`), networks and the VLAN plan in the lab file, wiring. Bastet adds UniFi device types (gateway, switch, AP) with ports and shows cabling and VLANs on pages and maps. Discovery from the controller comes later (item 5).
1. Ansible import (9.7) and the Ansible backend, for gitea, caddy, podman and hugo.
2. The rest of check: updates, images, unaccounted packages, clean-install sets, modified config files, status files; update policies and versions.
3. Creation and destruction as part of `apply` (Proxmox LXC/VM, Linode).
4. The container runtime role split, app roles with the settings tier and exposure, the proxy collector, then the DNS collector.
5. UniFi discovery (controller API) with cabling and overlay maps.
6. The web UI and orchestrator LXC, including a per-host lock on targets.
7. Run logs and resilience: every run recorded as JSONL events on the controller (secrets redacted), long or risky steps run as transient systemd units so a dropped connection doesn't kill them, reconnecting to finish a run, `bastet watch` / `bastet log`.
8. Explicit removal per role; `become` other than sudo (run0 first); the `proxmox-node` baseline (no-subscription repositories, the subscription notice, Proxmox packages, microcode); more native roles.

**Existing work:** the current `cli/` and `ansible/` keep working unchanged until the Ansible import (milestone 3). Then they run through Bastet as `imported_` roles, and each moves into the Bastet repo as it's reworked.

## 14. Stack

- **Python**, packaged with uv (`uv tool install bastet`), plus a container image for the orchestrator.
- **CLI:** Typer. **Validation** of inventory files and `role.yml`: pydantic.
- **Ansible:** `ansible-runner`; Ansible's own libraries to read inventories during import.
- **SSH** for gather and native roles: the system OpenSSH client (honours the user's agent and `~/.ssh/config`; no extra dependency). **Git:** the `git` CLI.
- **Web UI** (later): FastAPI + htmx.
- **Tests:** pytest.

## 15. Secrets

*(Revised 2026-10-03; replaces the sops design.)*

### 15.1 Storage: one note per secret

A secret is a Markdown note. Its frontmatter is readable metadata, so Obsidian and Bases can list secrets; its **body is exactly one armored age message** and nothing else. The YAML parser never sees the ciphertext, and frontmatter edits (`set_keys`) can't touch it. No sops.

```markdown
---
bastet: secret
store: age                   # where the value lives; only age today (15.9)
applies_to: "[[git1]]"
role: gitea
option: admin_password
source: generated            # generated | chosen | issued
created: 2026-10-03T14:22
rotated:                     # empty until the first rotation
rotates: true
rotation:                    # in-progress while a two-step rotation runs (15.6)
rotate_every:                # optional; this secret's own policy, wins over everything
expires:                     # optional hard deadline someone else sets (issued tokens)
standalone: false            # true = kept on purpose though nothing uses it
locked: true                 # false while plain text (15.4)
---
-----BEGIN AGE ENCRYPTED FILE-----
…
-----END AGE ENCRYPTED FILE-----
```

- Dates use Obsidian's date-and-time format (`YYYY-MM-DDTHH:mm`, local time). Every field is always present, empty or false when unused, so Bases can filter on it.
- `source`: **generated** (Bastet made it), **chosen** (you picked the value), **issued** (a service gave it; nobody picks it, e.g. an API token).
- The encrypted payload carries the secret's path (host, role, name) with the value, so a value copied into another note fails to decrypt as that secret. During a rotation it also carries the `next` value (15.6).
- Bastet owns the whole body. Extra text below the ciphertext is reported plainly ("notes about a secret go elsewhere"), not as a decryption error.
- `bastet: secret` is an inventory kind like host, hardware and role.

**Where notes live:**

| Path | For |
|---|---|
| `_secrets/<host>/<role>/<name>.md` | a role's secret on one host |
| `_secrets/<host>/<name>.md` | a host's own secret that no role owns (a BMC password) |
| `_secrets/lab/<role>/<name>.md` | lab-wide, used by a role everywhere (a DNS token) |
| `_secrets/lab/<name>.md` | lab-wide, no role |

`lab` can't be a host name. The command line names secrets as `<host> <role> <option>` (or `<host> <name>`; `lab` in the host slot); the file path is an implementation detail.

**Using a secret:** any role option, whether or not the contract marks it secret, can take a reference instead of a value: `secret:<path>`, or a short form resolved under the same host and role (`admin_password: secret:admin_password`). It also works for one item inside a list or map. Bastet decrypts it in memory at run time, then checks it against the option's type. An option holding a reference is treated as secret everywhere: redacted in output, reports, role pages and the roles table (`‹secret›`), never in commits.

### 15.2 Who can decrypt

Recipients are public keys listed in `Homelab.md`. By default:

| Recipient | Why |
|---|---|
| your SSH key | you decrypt by hand: `show`, `unlock`, emergencies |
| Bastet's own key (from `bastet init`) | Bastet decrypts during runs |
| the recovery key (from `bastet init`, shown once, kept offline) | survives losing the laptop |
| later: a YubiKey (`age-plugin-yubikey`) | a second key off the laptop |

- age reads key files (no ssh-agent support). Bastet's key has no passphrase so runs never prompt: anything that can read that file can decrypt every secret, which is why the recovery key matters.
- Any other machine you run Bastet from is added the same way. Bastet is not planned to run fully unattended; scripted runs are still a person's runs.
- Changing the list doesn't re-encrypt by itself: `check` and `audit` report "N secrets need re-encryption", and `bastet secret rekey` (later) does it.

### 15.3 Commands

| Command | Does |
|---|---|
| `bastet secret` | The secret inventory: every secret, its host / role / option, whether it's set, who uses it, secrets roles need but don't have, and a health summary. Never values. |
| `bastet secret set` | Numbered list of secrets that need a value (`0` = all, `q` = quit). For each: type or paste a value, Enter to generate (only when the contract allows; otherwise Enter asks again), or `e` to create the note unlocked and fill it in yourself. Typed values are asked twice. |
| `bastet secret set <host> <role> <option>` | The same for one secret. Replacing an existing value asks first. Reads the value from stdin when piped (`pass show x \| bastet secret set lab caddy dns_token`). |
| `bastet secret show <host> <role> <option>` | The one deliberate way to see a value: asks "display in terminal" or "copy to clipboard" (clipboard only when running locally; cleared after 45 s; needs `wl-copy` or `xclip`). Refuses when output isn't a terminal. |
| `bastet secret unlock [<host> <role> <option>]` | Plain text in place, for one secret or all (15.4). |
| `bastet secret lock` | Encrypts every plain-text secret note, from an unlock session or not; refuses empty values; commits. |
| `bastet secret audit` | Secret hygiene (15.7); prints and writes to the dashboard. |
| later: `bastet secret rotate …`, `bastet secret rekey` | explicit, never side effects of `apply` |

- `set` records `source` itself: Enter = generated; typed = chosen, or issued when the contract says so. It never changes `standalone`.
- Walking several secrets: each is committed as it's done (nothing lost on quit or crash); when the walk finishes, those unpushed commits are squashed into one before pushing.
- `bastet add role` lists the secrets the new role needs and asks "Set them now?": the `set` flow per secret, `s` to skip. Skipped ones are printed with their exact `set` commands. `-y` never asks; it prints them. Credentials another role provides (15.5) aren't asked.

### 15.4 Plain text: unlock and lock

- `bastet secret unlock` replaces each body with its plain value and sets `locked: false`. A live countdown runs: **Enter adds 15 minutes, `q`, Esc or Ctrl-C lock now**, a warning a minute before the timeout, then it locks. A progress bar shows decrypting and encrypting (names, never values).
- Locking re-encrypts only values that changed (they get `source: chosen` and a new date); unchanged ones get their original ciphertext back, so git sees nothing. Then one commit naming what changed.
- **Any plain-text secret note**, from an unlock session, `set … e`, or typed by hand, means:
  - a git hook Bastet installs in the inventory refuses every commit;
  - every other Bastet command refuses to run until `bastet secret lock` (no auto-lock: it could encrypt a half-typed value);
  - it shows red in `check`, `audit` and the dashboard.
- `unlock` refuses while Obsidian Sync is on for the vault (unless `_secrets/` is excluded), or while the Obsidian Git plugin auto-commits. It warns that backups taken while unlocked keep the plain text, and that Obsidian's own search index may too.

### 15.5 Generated and shared secrets

- A secret option with `generate:` (`password`, `token`, `ssh-keypair`, `wireguard-keypair`) is created when first needed. `check` lists what would be generated; `apply` generates **all** needed values **before touching any host**, encrypts, writes and commits them, then pushes. Keypairs: the private half is a secret, the public half an ordinary fact.
- Never shown after creation unless asked for with `show` or `unlock`.
- **A credential belongs to the role that creates the account it opens**; consumers reference it:

| Setup | Owner | Secret |
|---|---|---|
| bundled (app and database in one Compose stack) | the app's role | `git1/gitea/db_password` |
| a database role on the same host | the database role | `git1/postgres/gitea_password` |
| a database role on another host | the database role there | `db1/postgres/gitea_password` |
| a database Bastet doesn't manage | nobody in Bastet | `git1/gitea/db_password`, chosen or issued |

  Which row applies follows the consumer's `needs` setting (`database: bundled`, `"[[db1]]"`, or `external`).

### 15.6 Rotation

- **Every role with a secret option must define how it rotates** (its contract's `rotation:`); a role missing it doesn't load. Consumers of another role's secret define their part too (`consumes:`). Role pages and the roles index show it.
- **Methods:**
  - **two-step** (the default): the new value is stored as `next` inside the same encrypted payload, with the current one kept, and the note says `rotation: in-progress`. Bastet sets it, **verifies it works**, then promotes `next` to current and fills `rotated`. If anything fails, the old value is put back.
  - **direct**: the role can safely switch the value in one step.
  - **manual**: Bastet can't (issued tokens, your own passwords); `check` and `audit` say what to do by hand.
- **Across hosts**, Bastet carries the conversation (the roles never talk directly). For db1's Postgres password used by gitea on git1:
  1. gitea stops;
  2. postgres sets the new password;
  3. gitea updates its config, starts, and verifies it connects;
  4. done; on failure, postgres gets the old password back and gitea restarts with it.

  A short outage is accepted.
- **Policy** (`rotate_every`, per source: `{generated: 180d, issued: 365d, chosen: }`), weakest to strongest:
  1. the role contract's suggestion;
  2. `Homelab.md`;
  3. the host note's frontmatter;
  4. the host's role file;
  5. the secret note.

  Each level overrides only the sources it sets.
- `rotates` defaults to true. Nothing is due until some level sets a policy for that source.
- `expires` is separate: a hard date set by someone else, warned about ahead of time whatever `rotates` says.

### 15.7 Health: check versus audit

`check` answers "can Bastet safely do the configured work?"; `bastet secret audit` answers "is the secret setup healthy?".

| Finding | `check` | `audit` |
|---|---|---|
| missing required secret | blocks the hosts that need it | listed |
| doesn't decrypt, or path mismatch | blocks | listed |
| plain-text secret notes | blocks every command but `lock` | listed |
| changed upstream (15.8) | red alert; stops the run | listed |
| rotation due, expiring soon, unused, plaintext placeholders, too few recipients, needs re-encryption | a one-line summary pointing at `audit` | listed with details |
| weak or default values | — | listed (decrypts every value) |

- Unused: listed unless `standalone: true`; a standalone secret that something does use is listed too.
- `check`'s summary appears at the end of its output (scoped to the hosts checked, plus the lab secrets they use) and at the bottom of the dashboard. `audit` prints and writes its findings, with their date, to the dashboard.
- Later, opt-in: known-compromised passwords (a hash prefix to an outside service), password quality, reuse.

### 15.8 Tamper and change detection

- **Changed upstream:** every command pulls first. A pull that changes anything under `_secrets/` is a red alert listing each secret, who committed it, from which machine and when. `apply` stops and asks before going on, **even with `-y`**. With no answer (or no terminal), **the whole run stops**.
- **Not made by Bastet:** `check` warns when the last commit touching a secret note wasn't Bastet's. Commit authors are plain text, so this catches accidents, not deliberate forgery.
- **Later, if the inventory ever lives somewhere less trusted:** signed commits (git signing with Bastet's SSH key), so `check` can require a valid Bastet signature on the last change to each secret.
- Secrets are redacted from all output, status files, maps, commits and the generated inventory. A missing, undecryptable or plain-text secret stops the run before anything changes.
- **Early testing:** a plaintext value where a secret reference is expected is accepted with a warning. Placeholder values only.

### 15.9 Other stores (planned)

Vaultwarden is planned, and other password managers may follow. Every read and write of a value goes through one small store interface (get, set, exists); `store:` in the note says which. A Vaultwarden note keeps its frontmatter and has an empty body plus a reference to the item. The note, its Base listing, the commands and the health checks don't change. To design when it's built: unlocking (the master password per run, or a stored unlock for scripted runs), fetching everything once per run, and Vaultwarden's own sharing instead of age recipients.

### 15.10 Finding secrets in the vault

- Each host page embeds a Base listing that host's secrets grouped by role (name, role, source, dates, rotation). Nothing about secrets goes into the host's frontmatter except its rotation policy.
- The dashboard links to a master list, `_bastet/Secrets.md`: every secret with where it lives, **who uses it** (from role files, so a shared Postgres password shows its consumer), source, dates and rotation.

## 16. Testing

**Documented requirements:** the Bastet repo's README lists everything needed on the controller and on managed hosts (required vs. optional, and what each optional tool adds). Any change that introduces an external tool updates it in the same commit.


- Everything is callable from tests without a terminal, against **fixture inventories** with placeholder data.
- Gather parsing is tested against recorded fact output.
- The generated Ansible inventory is compared with expected files.
- Import is tested against fixture Ansible setups (groups, nesting, `import_playbook`, host patterns, inline tasks, vault strings): the as-is comparison must come out clean, and a second import must change nothing.
- Git handling (your-edits commit, Bastet commits, attribution by value history, conflicts) is tested in temporary repos.
- Native roles must pass the contract test (9.2).
- An end-to-end run against a disposable LXC or VPS is an opt-in marked test.

## 17. Out of scope for v1, and open questions

**Out of scope:** locking between controllers (added with the orchestrator, chapter 13); Bastet's own engine beyond native roles that pass the contract; Puppet, Packer, Terraform/OpenTofu; UniFi configuration changes (discovery only); backups (not designed yet); removal by absence; a database as a source of truth.

**Open:**

- Web UI: whether it edits files (11.4).
- Which internal DNS provider (9.3).
- The exact bootstrap-credential shape (8).
- Ansible roles (milestone 3): whether they're called directly from a host or group file, run as they are with their variables passed through and no option menu, or always get a `role.yml` contract first (9.2, 9.7).
