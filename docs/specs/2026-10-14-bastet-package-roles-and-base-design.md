# Package roles and the `base` role

**Status:** DRAFT, not finalized. Design agreed in conversation 2026-10-14 and still under the owner's review; open questions are in section 14. Nothing is built, and no plan exists yet. Plans follow once this is approved.

**Relationship to earlier documents:** builds on `2026-10-10-bastet-roles-architecture-design.md` (roles are Markdown over Python building blocks; a host runs by phase across all roles). It supersedes the roadmap's old wording for "VPS apps, step 3" (`base`, with the cleanup of `base`/`ssh`/`harden` first) and the old `packages` role design. `ssh` and `harden` are **out of scope** here (section 11).

## 1. What this changes, in one paragraph

Three roles already exist: `packages` (Python, `roles/builtin.py:_packages`; installs, update policy, reboot, the unaccounted report, apt-only knobs, the AUR) and the Markdown manager roles `pacman` and `apt` (today only their settings and repositories). This design moves each setting to its right home: `packages` becomes a thin, manager-neutral **role on the lab**; `pacman` and `apt` additionally take the manager-specific install options and can **override** the shared `packages` settings; the OS files bring the manager role to each host the way `systemd` comes with Arch; and a new **`base` role** (Markdown, applied everywhere, inert until a note sets something) is added. The `packages` building block stays Python and stays callable by any role, and by a person directly if they want, though that is discouraged.

## 2. Decisions (owner, 2026-10-14)

1. **`base`** is a Markdown role applied to every host. Lab, group and host notes each add to it. Bastet is a little opinionated, so `base` may do something with no options; what exactly is decided at the owner's review of the old role's behaviour (section 10). This is an exception to the CLAUDE.md rule "a default must change nothing with no options" (section 15).
2. **`packages`** is applied at the lab by default and nowhere else. It holds the manager-neutral settings.
3. **Manager roles** (`pacman` and `apt` exist already; later ones are new) come with each OS the way `systemd` comes with Arch today (OS files, `src/bastet/data/oses/<os>.yml`).
4. **A manager role can override `packages` settings.** On the manager role the shared options exist, are **unset by default** (so they override nothing), and are **shown** (effective value and where it came from) so nobody has to jump between roles to understand a host.
5. **Precedence stays one rule (enforced and documented):** note rank first (lab < group < host, host always wins), a role's own `overrides:` (like `time` on Debian) last. The only new rule: **at equal rank the manager role beats `packages`**. Because `packages` lives at the lab and managers come in at the OS level or above, the manager wins in every ordinary case.
6. **Arch installs always use `pacman -Syu`** (never `-Sy` alone). `refresh: false` stays as an explicit opt-out that keeps plain `-S`, with a loud warning on an Arch host (section 6).
7. **The AUR is removed everywhere** (decided earlier today), including roles table item 8.
8. **Reflector lives in the `pacman` role** and uses the `packages` and `systemd` blocks. For now it only installs reflector and enables and starts its timer; configuring it is noted for a later fix (section 8).
9. **Optional dependencies as dependencies** is a setting in **both** manager roles (pacman: optional deps installed `--asdeps`; apt: recommends), **on by default**.
10. **Unaccounted reports** appear in each host's markdown note as one section, with one subsection per kind (packages, users, files, services).
11. **`ssh` and `harden` are ignored** for now: not touched, not removed, not rebuilt.

## 3. How a role reaches a host

Existing ranks (`roles/resolve.py:sources_for`): OS default (−1), lab note (0), type default (1), group (2), host (3). Nothing ships as an "every host" default today.

- **`packages` and `base`** are lab notes (`_roles/lab/packages.md`, `_roles/lab/base.md`) that **`bastet init` writes** from each role's `starter:`. The owner re-initializes the lab folder; no migration is written.
- **Managers** come from the OS file (`pacman` added to the existing `arch.yml`; `apt` needs a new `debian.yml`, since only `arch.yml` exists today), with no options, as `systemd` does. `debian.yml` covers Debian-based hosts; Proxmox is Debian underneath, which is the owner's only non-Arch OS today. Ubuntu and others later.
- **Where the OS comes from, and the generated groups.** OS defaults are shipped inside Bastet (`data/oses/arch.yml`) and picked by the host's `os` value (`osinfo.os_id`; any Arch-like name maps to `arch`, `osdefaults.defaults_for`). That value is a gathered fact, so a brand-new host has **no OS defaults, and no manager role, until its first `bastet run -g`**.
- **The groups already exist, but in the wrong place.** `core/render.py` generates one group note per OS seen and one per host type seen, under `_bastet/groups/` (for example `arch.md` with `match: {os: arch}`, `vps.md` with `match: {type: vps}`), refreshed when facts are gathered. A role note with `applies_to: "[[arch]]"` reaches every Arch host, so **to adjust all Arch hosts you write a role note for the `arch` group** (group rank); a lab note with `overrides: [{when: host.arch_like, ...}]` also works, as `time` does. **Change (owner):** `_bastet/` is not editable by the user, so these groups move into a **user folder** where they can be edited. A user's own group note of the same name wins over a generated one.
- **Gather offers, the user can say no.** On `bastet run -g`, when a host's OS or type has no group yet, gather **asks** whether to create it, instead of creating it silently. A "no" is remembered in the **config folder** (`~/.config/bastet/`) so it is not asked again and a deleted group is not regenerated. With `-y`, gather **generates** the groups without asking.
- **`bastet add group` (new).** Groups are also made by hand, for anything else (for example mail servers): `bastet add group <name>` writes a group note with a `match:` rule or a plain member list.
- **Arch derivatives:** the owner runs only Arch proper and Proxmox, so derivatives are not handled in this round (`match` is exact on the OS id). This may change.
- **To check when planning:** that `bastet init` can write more than one lab role note, and what a lab with an OS that has no OS file gets (no manager role: the host's `packages` entries run, but no manager-specific options apply).

## 4. The `packages` role (thin)

Keeps the manager-neutral options: `install`, `remove`, `updates`, `updates_exclude`, `reboot`, `reboot_timeout`, `report_unaccounted`, `allowed`.

- **This round it stays Python** (`roles/builtin.py:_packages`) for these neutral parts. Only the manager-specific options and the AUR move out of it (sections 5 and 7). The unaccounted report currently lives here (`_packages` emits `Unaccounted`, `batches_for` fills its tracked list): **it is not removed**. It is noted for a cleanup round, together with the Markdown conversion of the thin `packages` role.
- **Cleanup later (noted, not now):** `packages` becomes Markdown handing data to the block (an update-policy entry on the block); the engine adds the report resources to every host itself with `allowed` as plain role data; `Reboot` is revisited with the block.
- **Updates:** a value set at a manager role (for example in `pacman.md`) is passed to the `packages` block, which deals with it.

## 5. Manager roles

- **`apt`:** `default_release`, `allow_change_held`, `dpkg_options`, repositories (already), `install_recommends` (optional deps, section 9).
- **`pacman`:** `pacman.conf` settings (already), the `-Syu` behaviour and `refresh`, optional deps, reflector (section 8).
- **Shared options (decision 4).** Each manager role lists the `packages` options it may override (`updates`, `updates_exclude`, `reboot`, `reboot_timeout`, `report_unaccounted`, `allowed`), unset by default. **The shared options keep the same key names as in `packages`** (owner), so `reboot` in `pacman.md` is the same setting as `reboot` in the lab's `packages.md`; the origin shown for each value names the role and the note it came from. The manager role marks which of its options are the shared ones (a short list under one contract key; the key's spelling is for the contract plan). Resolution: rank first; at equal rank the manager role wins (enforced by the resolver and also written in `writing_roles.md`); a set value overrides, an unset one does nothing. The key name and the exact merge go into the contract plan.
- **Display.** `bastet show` and the resolved table list the effective value of each shared option and its origin (for example `reboot ask (lab, packages)` or `reboot auto (OS default, pacman)`), shown on the manager role's page too. Nothing is hidden by the override.
- **List merging reminder:** list options **merge as a union** across levels (`resolve._merge`), so a host's list adds to the lab's. A scalar set at two notes of the same rank that disagree is a clash, as today.

## 6. Arch installs

`Package.fix_group` (`engine/packages.py`) installs with `pacman -Syu --noconfirm --needed <pkgs>`; `refresh: false` keeps `pacman -S`. The controller's own tool install (`core/tools.py`) gets the same change, the same flaw. `pacman -Sy <pkg>` alone is never used. **`refresh: false` on an Arch host raises a loud warning on every run** (a stale database can 404 or half-upgrade the system), not a one-time note. The existing update check (`checkupdates`) must keep failing loudly, not reporting "nothing pending", when the mirror is unreachable; a test pins it. A kernel upgrade that results is already covered by the reboot-needed mark.

### Package database lock and long upgrades

`-Syu` on a host that is far behind can run longer than a fix command is allowed (`FIX_TIMEOUT` is 1800 s in `engine/run.py`), and a timeout kills the ssh session while `pacman` may still be running (seen on the VPS, 2026-10-14). Decided for now, with no permanent fix:

- **Lock check:** before a pacman install or upgrade, if `/var/lib/pacman/db.lck` exists, check whether a `pacman` process is running. If one is, report that and stop. If none is, say the lock is stale and **ask** before removing it (never removed silently when interactive; **`-y` alone is enough to remove a stale lock**, no extra flag).
- **Timeout:** the message says a timed-out `pacman` may still be running or have left a lock. Making the limit settable, or running upgrades detached, is parked.

## 7. AUR removal

Remove `aur`, `aur_user`, `aur_helper`, the yay bootstrap, `PACKAGE_KEYS["aur"]`, their tests and the contract test; close roles table item 8. A note that still says `aur` is refused by the normal unknown-key error, which must name the key.

## 8. Reflector (in `pacman`)

For now: install `reflector` and enable and start `reflector.timer` (a `Unit` entry), nothing else. Its own configuration (`/etc/xdg/reflector/reflector.conf`: countries, age, protocols, number, sort) is **noted as a fix for later**; until then reflector runs with its package defaults. It is on by default (an opinionated default, section 15). A dead mirror is a separate failure from a stale database; reflector is the answer to it.

**Mirrorlist protection (opinionated default):** `etc/pacman.d/mirrorlist` is added to `NoExtract` in `pacman.conf` (the `no_extract` option of the `pacman` role), so an update of `pacman-mirrorlist` cannot overwrite the list reflector wrote.  **It applies only when reflector is on** (owner), and reflector is on by default.

## 9. Optional dependencies as dependencies

One setting in both managers, **on by default** (candidate name: `install_recommends`, which the block already has for apt; on pacman it means optional deps installed with `--asdeps`). Rules: it can be set per package entry (for packages whose optional deps are alternatives, such as pulseaudio against pipewire); an optional dep that something already installed satisfies is skipped; packages installed `--asdeps` are not "explicit", so they stay out of the unaccounted report (it reads `pacman -Qe`). A role that needs one specific alternative lists it as its own package. The `packages` block change happens once; both roles expose it.

## 10. The `base` role

Markdown, no Python. Options: `tools` (list of package names, **union** across lab, group and host), `microcode` (`auto` or `never`; unset = leave alone). `bastet init` and `bastet add role base` write a starter with a basic tool list. What it does with no options is decided at the owner's review, once the old role is looked at again (the old Python `base` defaulted to a tool list and `microcode: auto`).

- **`extra_tools` stays** (owner, 2026-10-14). Eventually `tools` becomes the baseline list for `base` (shipped baselines per host kind, **not editable** by notes), and `extra_tools` holds everything that is not baseline. Until baselines exist, both options are plain lists that union across levels, `tools` carrying the starter list. Baselines will likely differ by host kind (the owner expects different tools on LXCs than elsewhere); how they are chosen is undecided and not part of this round.
- **Microcode** (`auto`): physical hosts only, package by OS and CPU vendor (Arch `intel-ucode`/`amd-ucode`; Debian `intel-microcode`/`amd64-microcode`). Everything the old Python raised as an error becomes a `checks:` error: no CPU fact (name `bastet run -g`), unknown vendor, no package known for this OS. A virtual host gets an info note. On Debian an info note says the `non-free-firmware` component is needed.
- The old Python `base` (`roles/system.py:base`, `data/roles/base/role.yml`) is replaced by this role; its copy goes to `refs/`.

## 11. Reports and the unaccounted sections

Found in the code: `Unaccounted` (packages: explicit packages minus system packages, minus what roles install, minus `allowed`) and `UnaccountedUsers` are report-only resources in the `reports` slot; a run shows them as "attention" items. Their tracked lists are filled by `batches_for`, across all roles. This round changes none of that (section 4). The result users see is fixed here: each host's markdown note shows one section with a subsection per kind (packages, users, files, services). Each block keeps its own check through one shared pattern.

- **Unaccounted services (new):** `systemd` needs an unaccounted-services report: enabled units that are neither OS defaults nor managed by a role's `Unit` entry. Nothing does this today (`ServiceExposure` only takes the managed list). How OS defaults are told apart (unit presets) is for the plan.
- **Unaccounted files** is left for later. The goal is to look at least at `/etc`. The hard part is the baseline: a package's default config files are correct, so "not written by a role" is not enough, and a baseline per installed package (files it ships, unchanged) is needed first.
- **Not found yet:** where unaccounted items are written into a host note, if anywhere. The only note-writing code found is `core/security_note.py`, for the security reports.
- Reports about outside tools (lynis, ports, exposure) belong to `harden`'s rebuild and are not touched.

## 12. Out of scope, and what comes after

- `ssh`, `harden`, the `reports:` entry type, the `ssh_port` host field, and the removal of those three roles from `src/` are all **ignored for now**. Their Python (`roles/system.py:ssh`, `harden`, `data/roles/{ssh,harden}`) stays untouched.
- Roles after `base`, in this order: `caddy`, `forgejo`, `vaultwarden` (all in the Arch repos, native roles over the blocks). A short plan for each; with the contract right, each is mostly a Markdown note and its tests.

## 13. Order of work

1. **Contract:** shared options, the manager-wins tie rule (enforced and documented), and the display of shared values.
2. **Package roles:** manager-specific options move from `packages` to `pacman`/`apt`; AUR removal; `-Syu` with the lock check and the `refresh: false` warning; reflector timer and the mirrorlist `NoExtract`; optional deps on by default; `debian.yml`; `bastet init` writes the lab notes; CLAUDE.md amended (section 15).
3. **`base`.**
4. **`caddy`, `forgejo`, `vaultwarden`.**

## 14. Open questions

Answered 2026-10-14 and removed from this list: shared option key names (same names as `packages`), `-y` for groups (generates) and for the pacman lock (removes it), the `debian.yml` scope, `NoExtract` only with reflector, Arch derivatives (not this round), unaccounted reports (they work; not touched), the number of lab notes (a plan detail).

1. The spelling of the contract key that marks a manager option as a shared one (contract plan).
2. How the shipped baselines for `tools` are chosen per host kind (for example LXC against the rest), and when `tools` stops being editable. Not this round.
3. Whether `base` does anything with no options, after the owner reviews the old role (section 10). **In progress.**
4. Groups: the name of the user folder, the format of the remembered "no" in the config folder, and the `add group` rule syntax (section 3).
5. The wording of the CLAUDE.md and skill amendment (section 15), once the design is approved.
6. Reflector's own configuration (countries, age, and so on): a later fix, noted in section 8.

## 15. Opinionated defaults (a change to a CLAUDE.md rule)

CLAUDE.md says a role applied to every host by default must change nothing with no options set. In practice that means "the role being there installs and changes nothing until someone asks". The owner wants Bastet a little opinionated, so some roles will install software or change settings just by being there, without an option being set. Those are deliberate and are listed here: `base` (to be settled), reflector installed with its timer enabled on Arch, optional dependencies on, `etc/pacman.d/mirrorlist` in `NoExtract`, and always `-Syu` on Arch. When this design is approved, CLAUDE.md and the `bastet-new-role` skill are amended: a role may do something with no options when its own documentation lists exactly what it does; every other role still does nothing until an option is set.
