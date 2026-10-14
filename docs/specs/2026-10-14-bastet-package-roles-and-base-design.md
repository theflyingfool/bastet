# Package roles and the `base` role

**Status:** DRAFT, not finalized. Design agreed in conversation 2026-10-14 and still under the owner's review; open questions are in section 14. Nothing is built, and no plan exists yet. Plans follow once this is approved.

**Relationship to earlier documents:** builds on `2026-10-10-bastet-roles-architecture-design.md` (roles are Markdown over Python building blocks; a host runs by phase across all roles). It supersedes the roadmap's old wording for "VPS apps, step 3" and the old `packages` role design. `ssh` and `harden` are removed from `src/` in this round and rebuilt as Markdown later (section 12).

**Scope of this round (owner, 2026-10-14): only what is needed to build the Markdown roles.** Everything else is deferred and is in the roadmap. In: the cleanup and AUR removal, Arch `-Syu` with the lock check and the `refresh: false` warning, `supersedes` as a contract feature, reflector with the mirrorlist `NoExtract` (both wanted right away), the `base` role, and groups copied into a user folder. Deferred: all Debian-based changes (`debian.yml`, the `apt` role's options and optional dependencies, Debian-only notes), optional dependencies as dependencies, moving options between `packages` and the manager roles (they stay as they are), `init` generating groups, and the gather prompt that asks and remembers a "no".

**Vocabulary.** A *building block* is a role too, one of the special ones: the only place with real code (Python). Every other role is Markdown data that the blocks act on. There is no separate "block" and "role" for the same name: `packages` is one thing, a role, and it is the building block.

## 1. What exists, and what this changes

**Roles that exist today**
- Building-block roles (Python, `role.yml`): `packages`, `users`, `files`, `systemd`. (`commands` and `reports` are blocks too, with no role folder of their own.)
- Markdown roles: `pacman` and `apt` (settings and repositories only), and `time` (built and mostly working).
- Old-format roles that are not blocks (Python builders in `roles/system.py`): `base`, `ssh`, `harden`. They are to be Markdown.

**What this design changes.** Each setting moves to its right home. `packages` stays the Python building block, applied at the lab, holding the manager-neutral options; `pacman` and `apt` take the manager-specific install options and **supersede** the shared `packages` options; the OS files bring the manager role to each host the way `systemd` comes with Arch; `base` is rewritten as a Markdown role applied everywhere with the old role's behaviour; `ssh` and `harden` are removed from `src/` for a later rebuild. A person may use a building block directly, though that is discouraged.

## 2. Decisions (owner, 2026-10-14)

1. **`base`** is a Markdown role applied to every host. Lab, group and host notes each add to it. Bastet is opinionated, so `base` keeps the old role's defaults (tool list, `microcode: auto`) (section 15).
2. **`packages`** is applied at the lab by default and nowhere else. It stays Python (it is a building block) and holds the manager-neutral settings.
3. **Manager roles** (`pacman` and `apt` exist already; later ones are new) come with each OS the way `systemd` comes with Arch today (OS files, `src/bastet/data/oses/<os>.yml`). This round: `pacman` is added to `arch.yml`; `debian.yml` and `apt` changes are deferred.
4. **A manager role can supersede `packages` settings.** On the manager role the shared options exist, are **unset by default** (so they override nothing), and are **shown** (effective value and where it came from) so nobody has to jump between roles to understand a host.
5. **Precedence stays one rule (enforced and documented):** note rank first (lab < group < host, host always wins), a role's own `overrides:` (like `time` on Debian) last. The only new rule: **at equal rank the manager role beats `packages`**. Because `packages` lives at the lab and managers come in at the OS level or above, the manager wins in every ordinary case.
6. **Arch installs always use `pacman -Syu`** (never `-Sy` alone). `refresh: false` stays as an explicit opt-out that keeps plain `-S`, with a loud warning on an Arch host (section 6).
7. **The AUR is removed everywhere**, including roles table item 8.
8. **Reflector lives in the `pacman` role** and uses the `packages` and `systemd` roles' blocks. For now it only installs reflector and enables and starts its timer; configuring it is a later fix (section 8).
9. **Optional dependencies as dependencies** is a setting in **both** manager roles (pacman: optional deps installed `--asdeps`; apt: recommends), **on by default**. **Deferred.**
10. **Unaccounted reports** appear in each host's markdown note as one section, with one subsection per kind (packages, users, files, services). They work today and are not touched this round (section 11).
11. **`ssh` and `harden` are removed from `src/` now** (moved to `refs/`, every use pulled from the code and tests) and **rebuilt as Markdown later**. Until then Bastet assumes every host uses SSH port 22 (section 12).

## 3. How a role reaches a host

Existing ranks (`roles/resolve.py:sources_for`): OS default (−1), lab note (0), type default (1), group (2), host (3). Nothing ships as an "every host" default today.

- **`packages` and `base`** are lab role notes (`_roles/lab/packages.md`, `_roles/lab/base.md`) that **`bastet init` writes** from each role's `starter:`. `init` writes the lab role notes of **every role that applies by default**, not a fixed pair, and is safe to rerun (it never overwrites a note that exists). The owner re-initializes the lab folder; no migration is written.
- **Managers** come from the OS file: `pacman` is added to the existing `arch.yml`, with no options, as `systemd` does. `apt` needs a new `debian.yml` (only `arch.yml` exists today; Proxmox is Debian underneath): **deferred**.
- **Where the OS comes from.** OS defaults are shipped inside Bastet (`data/oses/arch.yml`) and picked by the host's `os` value (`osinfo.os_id`; any Arch-like name maps to `arch`, `osdefaults.defaults_for`). That value is a gathered fact, so a brand-new host has **no OS defaults, and no manager role, until its first `bastet run -g`**.
- **Generated groups exist, but in the wrong place.** `core/render.py` generates one group note per OS seen and one per host type seen, under `_bastet/groups/` (for example `arch.md` with `match: {os: arch}`, `vps.md` with `match: {type: vps}`), refreshed when facts are gathered. A role note with `applies_to: "[[arch]]"` reaches every Arch host, so **to adjust all Arch hosts you write a role note for the `arch` group** (group rank); a lab note with `overrides: [{when: host.arch_like, ...}]` also works, as `time` does. **Change (owner):** `_bastet/` is not editable by the user, so these groups move into a **user folder** (`groups`) where they can be edited. A user's own group note of the same name wins over a generated one.
- **Gather copies the groups.** On `bastet run -g`, the generated groups are copied into the user folder, and the user's copy wins over the generated one. **Deferred:** `init` generating the groups (the owner thinks it should generate all types), and the prompt that asks and remembers a "no" in the config folder.
- **`bastet add group` (to do, out of scope for this design).** Groups are also made by hand, for anything else (for example mail servers). The rule syntax is designed later; it is in the roadmap.
- **Arch derivatives:** the owner runs only Arch proper and Proxmox, so derivatives are not handled in this round (`match` is exact on the OS id). This may change.
- **To check when planning:** what a lab with an OS that has no OS file gets (no manager role: the `packages` role still runs, but no manager-specific options apply).

## 4. The `packages` role (the building block)

`packages` stays Python (`engine/packages.py` for the resources, `roles/builtin.py:_packages` for the role) and is applied at the lab. It keeps the manager-neutral options: `install`, `remove`, `updates`, `updates_exclude`, `reboot`, `reboot_timeout`, `report_unaccounted`, `allowed`.

- **What changes:** the AUR is removed (section 7), and installs use `-Syu` with the lock check (section 6). **Moving the manager-specific options (apt's `default_release`, `allow_change_held`, `dpkg_options`, the pacman install behaviour) to the manager roles is deferred**; they stay where they are.
- **Updates:** a value set at a manager role (for example in `pacman.md`) is passed to `packages`, which deals with it.
- **Unaccounted** lives here today (`_packages` emits `Unaccounted`, `batches_for` fills its tracked list). It works and **is not removed or reworked**; it is noted for a future cleanup. `Reboot` is a building-block resource that is ignored for now.

## 5. Manager roles

**This round the split between `packages` and the manager roles is left as it is.** What is built is the contract feature `supersedes` so a manager role (and any other role) can use it, and the first use can come with the first role that needs it. The rest of this section is the design for that use.

- **`apt`** (deferred): `default_release`, `allow_change_held`, `dpkg_options`, repositories (already), `install_recommends`.
- **`pacman`:** `pacman.conf` settings (already), reflector (section 8); later the `-Syu` behaviour and `refresh`, optional deps.
- **Shared options (decision 4).** Each manager role lists the `packages` options it may override (`updates`, `updates_exclude`, `reboot`, `reboot_timeout`, `report_unaccounted`, `allowed`), unset by default, **with the same key names as in `packages`** (owner), so `reboot` in `pacman.md` and `reboot` in the lab's `packages.md` are the same setting. Each carries **`supersedes: packages.reboot`** (owner's choice): it names the role and option it overrides as `role.option`, so the names may differ, and the same key lets any maintainer override an option in any other role. Type and description are taken from the target when left out. Resolution: rank first; at equal rank the manager role wins (enforced by the resolver and also written in `writing_roles.md`); a set value overrides, an unset one does nothing. **Checks when a role file is read:** a `supersedes` that names a role or option that does not exist (a typo such as `packages.rebot`) fails the load with a clear message, instead of silently doing nothing. If a host has the manager role but no `packages` note, the manager's value still reaches `packages` (always usable).
- **Display.** `bastet show` and the resolved table list the effective value of each shared option and its origin (the role and the note), for example `reboot ask (lab, packages)` or `reboot auto (OS default, pacman)`, also on the manager role's page. Nothing is hidden by the override.
- **List merging:** list options **merge as a union** across levels (`resolve._merge`), so a host's list adds to the lab's. A scalar set at two notes of the same rank that disagree is a clash, as today.

## 6. Arch installs

`Package.fix_group` (`engine/packages.py`) installs with `pacman -Syu --noconfirm --needed <pkgs>`; `refresh: false` keeps `pacman -S`. The controller's own tool install (`core/tools.py`) gets the same change, the same flaw. `pacman -Sy <pkg>` alone is never used. **`refresh: false` on an Arch host raises a loud warning on every run** (a stale database can 404 or half-upgrade the system). The existing update check (`checkupdates`) must keep failing loudly, not reporting "nothing pending", when the mirror is unreachable; a test pins it. A kernel upgrade that results is already covered by the reboot-needed mark.

### Package database lock and long upgrades

`-Syu` on a host that is far behind can run longer than a fix command is allowed (`FIX_TIMEOUT` is 1800 s in `engine/run.py`), and a timeout kills the ssh session while `pacman` may still be running (seen on the VPS, 2026-10-14). Decided for now, with no permanent fix:

- **Lock check:** before a pacman install or upgrade, if `/var/lib/pacman/db.lck` exists, check whether a `pacman` process is running. If one is, report that and stop. If none is, say the lock is stale and **ask** before removing it (never removed silently when interactive; **`-y` alone is enough to remove a stale lock**).
- **Timeout:** the message says a timed-out `pacman` may still be running or have left a lock. Making the limit settable, or running upgrades detached, is parked.

## 7. AUR removal

Remove `aur`, `aur_user`, `aur_helper`, the yay bootstrap, `PACKAGE_KEYS["aur"]`, their tests and the contract test; close roles table item 8. A note that still says `aur` is refused by the normal unknown-key error, which must name the key.

## 8. Reflector (in `pacman`)

**This is a stopgap, not a designed role** (owner): it is thrown in so Arch hosts have working mirrors, and the role's docs say it is incomplete.

For now: install `reflector` and enable and start `reflector.timer` (a `Unit` entry), nothing else. Its own configuration (`/etc/xdg/reflector/reflector.conf`: countries, age, protocols, number, sort) is a fix for later; until then reflector runs with its package defaults. It is on by default (section 15). A dead mirror is a separate failure from a stale database; reflector is the answer to it.

**Mirrorlist protection (opinionated default):** `etc/pacman.d/mirrorlist` is added to `NoExtract` in `pacman.conf` (the `no_extract` option of the `pacman` role), so an update of `pacman-mirrorlist` cannot overwrite the list reflector wrote. **It applies only when reflector is on**, and reflector is on by default.

## 9. Optional dependencies as dependencies (deferred)

**Deferred by the owner; kept here as the design.**

One setting in both managers, **on by default** (candidate name: `install_recommends`, which `packages` already has for apt; on pacman it means optional deps installed with `--asdeps`). Rules: it can be set per package entry (for packages whose optional deps are alternatives, such as pulseaudio against pipewire); an optional dep that something already installed satisfies is skipped; packages installed `--asdeps` are not "explicit", so they stay out of the unaccounted report (it reads `pacman -Qe`). A role that needs one specific alternative lists it as its own package. The change happens once in `packages`; both manager roles expose it.

## 10. The `base` role

Markdown, no Python (it is not a building block). `bastet init` and `bastet add role base` write the lab note. For now it only does what the old role did:

- **`tools`:** list of package names, default `[vim, zsh, git, htop, tree, gdu, wget, less]`. Lists **union** across lab, group and host, but a note that sets `tools` replaces the default list. That is why `extra_tools` stays: it adds on top at every level. Eventually `tools` becomes the shipped, non-editable baseline (selected by a host-kind baseline, for example LXC against the rest) and `extra_tools` holds everything else. A `baseline` option is **reserved**: documented as unused for now.
- **`microcode`:** `auto` (default) or `never`. Physical hosts only; package by OS and CPU vendor (Arch `intel-ucode`/`amd-ucode`; Debian `intel-microcode`/`amd64-microcode`). Everything the old Python raised as an error becomes a `checks:` error: no CPU fact (name `bastet run -g`), unknown vendor, no package known for this OS. A virtual host gets an info note. Debian is kept as a straight port (the same role file lists the Debian packages, and the packages role picks the manager on the host); the Debian-only info note about the `non-free-firmware` component is deferred.
- **It will grow** (owner), but nothing else is added in this round: no firmware, fwupd, smartd or sensors options yet.
- The old Python `base` (`roles/system.py:base`, `data/roles/base/role.yml`) is moved to `refs/` with the rest of `system.py` (section 12).

## 11. Reports and the unaccounted sections

`Unaccounted` (packages: explicit packages minus system packages, minus what roles install, minus `allowed`) and `UnaccountedUsers` are report-only resources in the `reports` slot; a run shows them as "attention" items. Their tracked lists are filled by `batches_for`, across all roles. They work and are **not touched this round**. The result users see is fixed here: each host's markdown note shows one section with a subsection per kind (packages, users, files, services).

- **Unaccounted services (new, roadmap):** `systemd` needs an unaccounted-services report: enabled units that are neither OS defaults nor managed by a role's `Unit` entry. How OS defaults are told apart (unit presets) is for its plan.
- **Unaccounted files (roadmap):** the goal is to look at least at `/etc`. The hard part is the baseline: a package's default config files are correct, so "not written by a role" is not enough, and a baseline per installed package (files it ships, unchanged) is needed first.
- Reports about outside tools (lynis, ports, exposure) belong to `harden`'s rebuild.

## 12. `ssh` and `harden`: removed now, rebuilt later

- **Removed now:** `roles/system.py` (the `base` code goes with it, replaced by section 10), `data/roles/{base,ssh,harden}/`, their entries in `BUILDERS` and `ORDER`, `HostInfo.ssh_ports`, the `ssh`-role port lookup in `cli/common.py`, and their tests are moved to `refs/` and pulled from `src/` and `tests/`. Copies in `refs/` are made first; `refs/` is git-ignored, so they are the only working reference. `engine/security.py` (lynis, exposure, listening ports, vulnerable packages, AppArmor) stays with its engine tests; only the role that called it goes.
- **SSH port:** nothing is done about it for now. Bastet assumes port 22 everywhere. A host-note `ssh_port` field, which the rebuilt `ssh` role would write sshd's `Port` from so the two cannot disagree, is a later item in the roadmap.
- **Cost, stated plainly:** until they are rebuilt, Bastet does not manage or check sshd, fail2ban or sysctl, and the lynis and exposure reports pause. Removing a role reverts nothing on hosts: files already written stay as they are. The `bastet` account guard stays (it belongs to `users`).
- **Rebuild rule:** the old roles relied on far too much Python. When rebuilt, they are Markdown over the blocks, and whatever they did in Python is provided by a block, not by the role:
  - **`systemd` block:** sysctl (`sysctl.d`, the safe default values, the refusal on containers, the setting-name check, the apply step) and `modules-load.d` for blocked modules. It is already a planned `systemd` feature; it is not built in this round, and `harden`'s code in `refs/` is the reference.
  - **`files` block:** nothing new is expected for sshd: the `validate:` entry key (a command run on the new file, `sshd -t -f %s`) is the check, and `edit: ini` or a template writes the settings. To confirm when `ssh` is rebuilt, including `Match` blocks. fail2ban uses `edit: ini`.
  - **`reports` block:** the lynis, exposure, listening-ports, vulnerable-packages and AppArmor resources need a `reports:` entry type in the contract.
  - **Contract:** the "ports stay accounted for" logic becomes a role `check:` once the SSH port is picked up again.
- Roles after `base`, in this order: `caddy`, `forgejo`, `vaultwarden` (all in the Arch repos, native roles over the blocks). A short plan for each; with the contract right, each is mostly a Markdown note and its tests. `ssh` and `harden` come last.

## 13. Order of work

**In this round**
1. **Cleanup:** `ssh`, `harden` and the old `base` moved to `refs/` and pulled; AUR removed.
2. **Contract:** `supersedes` (with the typo check), the manager-wins tie rule (enforced and documented), the display of shared values, and the CLAUDE.md amendment (section 15).
3. **Arch installs and pacman:** `-Syu`, the lock check, the `refresh: false` warning, reflector timer and the mirrorlist `NoExtract`; groups copied to a user folder.
4. **`base`** in Markdown.
5. **`caddy`, `forgejo`, `vaultwarden`.**

**Deferred (all in the roadmap)**
- Debian: `debian.yml`, `apt` options and optional deps, the `non-free-firmware` note.
- Optional dependencies as dependencies (both managers).
- Moving options between `packages` and the manager roles.
- `init` generating groups; the gather prompt with a remembered "no"; `bastet add group`.
- Reflector configuration; unaccounted services and files; sysctl in the `systemd` block.
- `ssh` and `harden` rebuilt (last); the SSH port field.
- `tools` baselines; more `base` options; the test audit.

## 14. Open questions

Answered 2026-10-14 and removed: shared option key names (same as `packages`), the key (`supersedes`), `-y` behaviour, `debian.yml` scope, `NoExtract` only with reflector, Arch derivatives (not this round), unaccounted reports (untouched), lab role notes (init writes all that apply), what `base` does now (as the old role), the groups folder name, the format of the remembered "no", `add group` syntax (out of scope), the SSH port (22 for now), `sshd -t` (the files `validate:`).

1. Nothing about `supersedes` is open: the typo check and the no-`packages`-note case are decided in section 5.
3. The final wording of the CLAUDE.md and skill amendment (section 15).
4. How the baseline that fills `tools` is selected. Not this round.
5. Reflector's configuration (stopgap, section 8).

## 15. Opinionated defaults, and the CLAUDE.md rewrite

**Bastet is opinionated, but it tries to respect users choosing their own defaults most of the time.** Some roles install software or change settings just by being there; these are deliberate, the role's documentation says exactly what they do, and a note can turn them off. Listed here: `base` (tool list and `microcode: auto`), reflector's timer on Arch, optional dependencies on, `etc/pacman.d/mirrorlist` in `NoExtract`, always `-Syu` on Arch. Every other role waits for an option.

When this design is approved:
- CLAUDE.md's role paragraph (today: "must change nothing with no options") is rewritten around that principle.
- **Skills to change (checked against `.claude/skills/`):**
  - `bastet-new-role`, rule 1 ("Unset means leave alone, and a default applied to every host must change nothing"): rewritten to the opinionated-defaults principle (an opinionated default is allowed when the role's documentation lists exactly what it does and a note can turn it off; the no-options test then asserts exactly that documented behaviour, not "emits nothing"). Its test pointer (`test_systemd_default_is_neutral.py`) stays for roles that do wait for an option.
  - `bastet-new-role`, "Where it lives": the sentence that the old Python roles are "plus ssh/base/harden until converted" is wrong after the cleanup (they move to `refs/`; `base` returns as Markdown). Its opening line also lists `base`, `harden` and `ssh` among roles to write; update to what is left.
  - `bastet-new-role`, new text: the `supersedes:` key, with a pointer to `docs/testing.md` for the tests.
  - `bastet-run-plan`, review checklist line "Anything applied to every host by default must be neutral": changed to match the new principle (a default that changes a host must be one the role's docs list); and a pointer to `docs/testing.md` in the implementer rules.
  - `run-bastet`: nothing in it refers to these roles; no change.
- CLAUDE.md is tidied. Done 2026-10-14: the stray `4CLAUDE.md` (test-writing guardrails) now lives in `docs/testing.md`, linked from CLAUDE.md.
- The roadmap has a test audit row.
