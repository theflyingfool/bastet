# Cleanup, `supersedes`, Arch installs and the `base` role — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. In this repo, the `bastet-run-plan` skill supplies the Bastet-specific parts; the `bastet-new-role` skill holds the role checklist.

**Status:** written 2026-10-14 from the approved spec. **Awaiting the owner's read; no code is written yet.**

**Goal:** VPS apps, step 3: remove the unconverted `ssh`, `harden` and old `base` roles and the AUR; add the `supersedes` contract key; make Arch installs work against a stale database; add a reflector stopgap to `pacman`; copy the generated groups into a user folder; rewrite `base` in Markdown.

**Architecture:** Cleanup first (so there is less to cross-check), then one contract feature (`supersedes`), then changes inside the `packages` building block and the `pacman` Markdown role, then `base` as a Markdown role. `packages` is a building block-role and stays Python. `caddy`, `forgejo` and `vaultwarden` are **not in this plan**: each gets its own short plan after `base` lands, written on the finished contract.

**Tech Stack:** Python ≥3.12, pydantic, PyYAML, Jinja2 (existing sandbox), pytest, ruff.

**Spec:** `docs/specs/2026-10-14-bastet-package-roles-and-base-design.md`. Models: `src/bastet/data/roles/time/time role.md`, `.../pacman/pacman role.md`. Test rules: `docs/testing.md`.

## Global Constraints

- **Unit tests** never touch the real inventory, `~/.config/bastet`, `~/.local/share/bastet`, `~/.ssh`, the real `~/.cache` or `$XDG_RUNTIME_DIR`; no network; `tmp_path` only; placeholder data only (10.1.x.x addresses, host names like pve1/media01). Follow `docs/testing.md`: a few focused tests per task, `parametrize`, no sleeps, no duplicate layers.
- **Test file basenames unique across `tests/`** (no `__init__.py`).
- Every message goes through `bastet.ui.out`; no `typer.echo` in `src/`; no "spec §"/"Task N" references in `src/`.
- The version is written only in `pyproject.toml`, bumped with `scripts/version-bump` (Task 11).
- `docs/roles.md` is generated (`uv run python scripts/gen_roles_doc.py`); a repo test checks it.
- `ruff check src tests` and `scripts/privacy-check` pass before the final commit (copy the ignored `.privacy-patterns` into a fresh worktree first, then delete the copy).
- Nothing in Bastet deletes notes, records or host files; this plan adds no deletion. Removing a role from `src/` reverts nothing on hosts.
- A building block is a role too, the special ones that stay Python (`packages`, `users`, `files`, `systemd`); every other role is Markdown. A role may do something with no options only when its own docs list exactly what (the opinionated-defaults principle in the spec, section 15).
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` and the `Claude-Session:` line; first line ends `(Task N, not reviewed yet)`.
- The owner runs the full suite and says when it passed.

## Decisions carried from the spec (not to be reopened in the tasks)

1. `ssh` and `harden` are removed now and rebuilt last; **Bastet assumes SSH port 22 everywhere** (no `ssh_port` field). Their code is copied to `refs/` first.
2. Arch installs always `pacman -Syu --noconfirm --needed`; `refresh: false` keeps `-S` and warns loudly. A stale `db.lck` is removed only with `-y`; interactively the run stops with instructions. (**Simplification to confirm:** the spec says "ask"; the engine has no prompt channel inside a fix, so this plan refuses with instructions unless `-y`.)
3. `supersedes: <role>.<option>` marks a manager option as overriding another role's option; rank first, a tie goes to the role with `supersedes`. No existing role uses it this round.
4. Deferred (roadmap): Debian/`apt`/`debian.yml`, optional dependencies as dependencies, moving options between `packages` and the managers, `init` generating groups, the gather prompt, `add group`, reflector configuration, sysctl, `tools` baselines.

## Review Focus

1. A note still naming a removed role (`base` old, `ssh`, `harden`) fails the host with the existing `unknown role` message, and other hosts are unaffected. (Task 2)
2. `supersedes` naming a role or option that does not exist fails the role load with a message naming the role file and key; a type mismatch is refused. (Task 4)
3. A host with the superseding role but no `packages` note still gets the value. (Task 5)
4. A stale or live pacman lock, and an unreachable mirror during the update check, never read as "nothing to do". (Task 7)
5. `base` on a physical host with no or an unknown CPU fact is an error naming `bastet run -g`; on a VM or container it installs nothing; `base` with no options on a physical Arch host installs the default tools and the right microcode package. (Task 10)

---

### Task 1: Approve the spec; amend CLAUDE.md and the skills

**Files:** Modify `docs/specs/2026-10-14-bastet-package-roles-and-base-design.md` (status line), `CLAUDE.md`, `.claude/skills/bastet-new-role/SKILL.md`, `.claude/skills/bastet-run-plan/SKILL.md`.

- [ ] **Step 1: Spec status.** Change the status line from "DRAFT, not finalized" to "Approved by the owner 2026-10-14; plans follow".
- [ ] **Step 2: CLAUDE.md.** Rewrite the paragraph that starts "Roles: a role leaves things alone unless an option is set" to: *Bastet is opinionated, but tries to respect users choosing their own defaults most of the time. A role leaves things alone unless an option is set, except where its own documentation lists exactly what it does with no options (for example `base`'s tool list and `microcode: auto`, `pacman`'s reflector timer); a note can always turn such a default off. Anything else applied to every host by default (an OS default role, a default entry) must change nothing with no options.* Keep the rest of the paragraph (accounts, starter). Also update the line "The `users`, `files`, `packages` and `systemd` roles are the special ones that stay Python" if it still names `ssh`, `base` or `harden` anywhere (it should not).
- [ ] **Step 3: Skills.** In `bastet-new-role`: rewrite rule 1 to the same principle (the no-options test asserts the documented behaviour; roles that wait for an option keep the "emits nothing" test and the pointer to `tests/roles/test_systemd_default_is_neutral.py`); replace "plus ssh/base/harden until converted" with the real list (`users`, `files`, `packages`, `systemd` only) and drop `base`, `harden`, `ssh` from the description's "use before writing" list except as roles to be rebuilt later; add one bullet on `supersedes: <role>.<option>` and one pointing to `docs/testing.md`. In `bastet-run-plan`: change the review line "Anything applied to every host by default must be neutral" to match, and add `docs/testing.md` to the implementer rules.
- [ ] **Step 4: Check.** `grep -n -i "must change nothing\|neutral" CLAUDE.md .claude/skills/*/SKILL.md` shows only the new wording. No tests to run.
- [ ] **Step 5: Commit** `Approve the spec; CLAUDE.md and skills: Bastet is opinionated (Task 1, not reviewed yet)`.

---

### Task 2: Move `ssh`, `harden` and the old `base` to `refs/`

**Files:**
- Delete: `src/bastet/roles/system.py`, `src/bastet/data/roles/{base,ssh,harden}/`
- Modify: `src/bastet/roles/builtin.py`, `src/bastet/cli/common.py`, `src/bastet/data/docs/using_roles.md`, `docs/roles.md` (regenerated)
- Delete or trim tests (below); Create `tests/roles/test_removed_roles_unknown.py`

**Interfaces:** Produces: `BUILDERS = {"systemd", "packages", "users", "files"}`; `ORDER = ("pacman", "packages", "users", "files", "systemd")`; `HostInfo` without `ssh_ports`; `ssh_ports(ctx, doc) -> list[int]` returns `[22]` (kept so `cli/run.py` and `cli/gather.py` need no change; a comment says port support returns with the `ssh_port` field in the roadmap).

What depends on the old roles (checked in the code):

| Dependency | Where | Decision |
|---|---|---|
| Python builders and helpers | `roles/system.py` | Copy to `refs/`, delete |
| `BUILDERS`, `ORDER`, `HostInfo.ssh_ports`, the `ssh` lookup in `batches_for` | `roles/builtin.py:24,36,211,216` | Remove |
| Role definitions | `data/roles/{base,ssh,harden}/role.yml` | Copy to `refs/`, `git rm` |
| Port Bastet connects on | `cli/common.py` `ssh_port`, `_role_ports`, `ssh_ports` | `ssh_ports` returns `[22]`; delete `ssh_port` and `_role_ports` |
| Role-only tests | `tests/roles/test_harden_role.py`, `test_ssh_role.py`; `base`/`ssh`/`harden` cases in `test_system_roles.py`, `test_builtin.py` | Delete or trim; `packages`/`users` cases stay |
| Port tests | `tests/cli/test_ssh_port.py` | Keep only the "default is 22" case |
| Container contract tests | `tests/contract/test_contract.py`: `test_base_contract`, `test_ssh_contract`, `test_harden_contract`, `test_arch_harden_reports_contract` | Delete |
| Tests using the names as example data | `tests/cli/test_add_role.py`, `test_common.py`, `test_secret_leaks.py`, `tests/core/test_inventory.py`, `test_render.py`, `test_pages.py` | Grep each; switch to a surviving role (`packages`, `files`, `time`, `pacman`); leave unrelated words alone (ssh the command, Obsidian "Bases") |
| Type and OS default roles | `data/types/*.yml`, `oses/arch.yml` | None name them (verified) |
| `engine/security.py` and its tests | lynis, exposure, ports, vulnerable packages, AppArmor | Stay; only the role that called them goes |
| `role-hashes.txt` | lists the three | `scripts/version-bump` rewrites it (Task 11) |
| Docs | `using_roles.md:4`, `docs/roles.md` | Edit / regenerate |

- [ ] **Step 1: Failing tests** in `tests/roles/test_removed_roles_unknown.py`:

```python
import pytest

from bastet.core.errors import BastetError
from bastet.roles.contract import load_roles


def test_the_removed_roles_are_not_shipped():
    assert not {"ssh", "harden"} & set(load_roles())


def test_a_note_naming_a_removed_role_fails_that_host_only(tmp_path):
    # Build a tiny inventory (copy the helper in tests/roles/test_resolve.py) with two hosts and a role note
    # `_roles/hosts/media01/ssh.md`; resolve() must raise BastetError matching "unknown role 'ssh'" for media01
    # (with the note's file) and must succeed for the other host.
    ...
```

Fill in the second test from `tests/roles/test_resolve.py`'s inventory helper; it must be complete, not a stub. `base` is not asserted missing here because it returns in Task 10.
- [ ] **Step 2: See them fail** (`uv run pytest tests/roles/test_removed_roles_unknown.py -q`).
- [ ] **Step 3: Copy first.** `mkdir -p refs/removed-2026-10-14 && cp -r src/bastet/data/roles/{base,ssh,harden} src/bastet/roles/system.py tests/roles/test_harden_role.py tests/roles/test_ssh_role.py tests/cli/test_ssh_port.py refs/removed-2026-10-14/ && git show HEAD:tests/contract/test_contract.py > refs/removed-2026-10-14/test_contract.py`, then `ls refs/removed-2026-10-14` to confirm. `refs/` is git-ignored, so this is the only working reference (sysctl, fail2ban and sshd logic for the later rebuilds).
- [ ] **Step 4: Remove and edit** per the table: `git rm -r` the three role folders and `system.py`; edit `builtin.py` and `cli/common.py`; trim or delete tests; regenerate `docs/roles.md`; edit `using_roles.md`.
- [ ] **Step 5: Run** `uv run pytest tests/roles tests/cli tests/core tests/engine -q -x`, `uv run python -c "import bastet.roles.builtin"`, `ruff check src tests`. Expected: pass.
- [ ] **Step 6: Commit** `Move ssh, harden and the old base to refs/; Bastet assumes SSH port 22 (Task 2, not reviewed yet)`.

---

### Task 3: Remove the AUR

**Files:**
- Modify: `src/bastet/engine/packages.py` (`Package.aur`, `aur_user`, the two `_check` branches, the `group_key` part, the `yay` branch of `fix_group`), `src/bastet/roles/builtin.py` (`_packages`: `aur_user`, `helper`, `wants_aur`; delete `_aur_bootstrap`, `AUR_NAME`; remove imports left unused), `src/bastet/roles/entries.py:31` (`"aur"` out of `PACKAGE_KEYS`), `src/bastet/data/roles/packages/role.yml` (options `aur`, `aur_user`, `aur_helper` and the AUR example)
- Modify tests: `tests/engine/test_packages.py` (AUR cases), `tests/roles/test_builtin.py`, `tests/roles/test_role_package_entries.py`, `tests/roles/test_system_roles.py`, `tests/contract/test_contract.py` (`test_arch_aur_contract`)
- Modify: `docs/ROADMAP.md` (roles table item 8, the packages row), `docs/roles.md` (regenerated)

- [ ] **Step 1: Failing test.** In `tests/roles/test_role_package_entries.py`, add (adapting that file's `role`/`built` helpers):

```python
def test_aur_is_refused_naming_the_key(tmp_path):
    with pytest.raises(BastetError, match="aur"):
        built(role(tmp_path, [{"name": "yay-bin", "aur": True}]), {})
```

and in `tests/roles/test_builtin.py`: `check_values(ROLES["packages"], {"aur_user": "x"}, "packages")` raises "has no option 'aur_user'". Run: they fail while `aur` is accepted.
- [ ] **Step 2: Remove** everything listed; delete the pure-AUR tests, and keep the ordinary half of tests that mix AUR and normal packages. Check the unknown-key message names the key.
- [ ] **Step 3: Verify.** `grep -rIn -i -E "\baur\b|yay|bastet-aur|aurutils" src tests scripts` prints only unrelated hits. Roadmap: close item 8 ("removed 2026-10-14"), delete "AUR bootstrap" from the packages row.
- [ ] **Step 4: Run** `uv run pytest tests/engine tests/roles -q`, `uv run python scripts/gen_roles_doc.py`, `ruff check src tests`.
- [ ] **Step 5: Commit** `Remove the AUR everywhere (Task 3, not reviewed yet)`.

---

### Task 4: `supersedes` — parse and check

**Files:** Modify `src/bastet/roles/contract.py` (`Option`, `OPTION_KEYS`, `_option`, `load_roles`); Create `tests/roles/test_supersedes_parse.py`; Modify `src/bastet/data/docs/writing_roles.md` (option keys list and a short section).

**Interfaces:** Produces: `Option.supersedes: str | None` (`"role.option"`). After `load_roles()`, every option with `supersedes` has its `type`, `description`, `items`, `fields`, `choices` filled from the target when the role file left them out, and the target is known to exist.

- [ ] **Step 1: Failing tests** (build roles with the same helpers `tests/roles/test_option_requires.py` uses to write a role file into `tmp_path` and call `load_roles(directory)`; the target role comes from a second folder):

```python
@pytest.mark.parametrize("target", ["packages.rebot", "nosuchrole.reboot", "packages", "packages.reboot.x"])
def test_a_bad_supersedes_fails_the_load_naming_file_and_key(tmp_path, target): ...  # BastetError, file is the role file, key "supersedes"

def test_supersedes_copies_type_and_description_from_the_target(tmp_path): ...
    # target role has option reboot {type: string, description: "when to reboot", choices: [never, ask, auto]};
    # manager option says only `supersedes: target.reboot`; loaded option has those three.

def test_a_type_mismatch_with_the_target_is_refused(tmp_path): ...
```

Write each out in full. A manager option that sets its own `type` must match the target's type.
- [ ] **Step 2: See them fail.**
- [ ] **Step 3: Implement.** Add `"supersedes"` to `OPTION_KEYS`; `_option` stores the string after checking it matches `^[a-z][a-z0-9_-]*\.[a-z_][a-z0-9_]*$` (and allows `type` to be omitted when `supersedes` is present: the "needs a type" check in `_option` moves to after the fill-in). In `load_roles`, after all roles are parsed, a second pass resolves every `supersedes` against the loaded roles (missing role or option → `BastetError(f"role {name}: option {opt} supersedes {target}, which does not exist", file=role.path, key="supersedes")`; type mismatch likewise) and fills the missing fields. `RoleDef` gains nothing.
- [ ] **Step 4: Run** `uv run pytest tests/roles -q`; `ruff check src tests`.
- [ ] **Step 5: Commit** `Contract: supersedes names the option of another role an option overrides (Task 4, not reviewed yet)`.

---

### Task 5: `supersedes` — resolution and display

**Files:** Modify `src/bastet/roles/resolve.py` (`resolve`, a new helper `_apply_supersedes`), `src/bastet/roles/pages.py` (`resolved_table`); Create `tests/roles/test_supersedes_resolve.py`; Modify `src/bastet/data/docs/writing_roles.md`.

**Interfaces:** Consumes: `Option.supersedes` (Task 4). Produces: after merging, for each applied role A and each option `o` of A with `supersedes == "T.p"` that has a value, the effective value of `T.p` is decided by **rank first** (the highest note rank that set it, as in `Source.rank`), and **a tie goes to the role with `supersedes`**; the winner is written into T's merged values before defaults, and T's origin for `p` reads `"<label>, <role>"` (for example `OS default (arch), pacman`). If T is not applied to the host, it is applied with only that value. An unset superseding option changes nothing.

- [ ] **Step 1: Failing tests** in `tests/roles/test_supersedes_resolve.py` (use the inventory-building helper in `tests/roles/test_resolve.py` with two shipped-style roles written into a `tmp_path` roles directory, `target` and `manager`, as in Task 4):

```python
def test_the_manager_value_wins_a_tie_with_the_lab_note(...): ...      # lab target note reboot=ask, lab manager note reboot=auto -> auto, origin "lab, manager"
def test_a_host_note_on_the_target_beats_a_lab_note_on_the_manager(...): ...  # rank first: host target note reboot=never wins
def test_an_unset_manager_option_changes_nothing(...): ...             # target keeps its own value and origin
def test_the_target_is_applied_when_it_has_no_note(...): ...           # only the manager note exists; target Applied exists with the value
def test_the_resolved_table_shows_the_effective_value_and_its_origin(...): ...  # resolved_table(applied) lists the target option with "lab, manager" and the manager role's row shows the shared option with the effective value
```

Write all five completely.
- [ ] **Step 2: See them fail.**
- [ ] **Step 3: Implement.** In `resolve`, keep per-role pre-default `merged`, `origins` and a new `ranks: dict[str, tuple]` (the highest rank among sources that set each key) in a list instead of appending `Applied` straight away; run `_apply_supersedes` over that list (create the target's entry when missing from `roles[target]`); then, per role, do `check_relations`, `with_defaults` and build `Applied`, so `requires`/`conflicts` see the superseded value. Keep the final sort by role name. `resolved_table` prints, under a manager role with shared options, a line per shared option with the effective value and `from <origin>` even when the manager's own value is unset.
- [ ] **Step 4: Run** `uv run pytest tests/roles -q`; `ruff check src tests`.
- [ ] **Step 5: Commit** `Resolver: supersedes decides by rank, ties to the superseding role, and is shown in the table (Task 5, not reviewed yet)`.

---

### Task 6: Arch installs use `pacman -Syu`

**Files:** Modify `src/bastet/engine/packages.py` (`Package.fix_group`), `src/bastet/core/tools.py:22`, `src/bastet/data/roles/packages/role.yml` (the `refresh` and `full_upgrade` descriptions); tests `tests/engine/test_packages.py`, `tests/core/test_tools.py`, `tests/engine/test_updates.py`.

**Interfaces:** Produces: for `manager == "pacman"` and `state == "present"` the install command is `pacman -Syu --noconfirm --needed{extra} -- <pkgs>` when `refresh` is true (the default) and `pacman -S --noconfirm --needed{extra} -- <pkgs>` when `refresh=False`. Removal commands are unchanged. `pacman -Sy` alone appears nowhere.

- [ ] **Step 1: Failing tests** in `tests/engine/test_packages.py`: change the pacman case at the parametrized table (`"pacman -S --noconfirm --needed -- tree"`) to `-Syu`, add `test_pacman_refresh_false_keeps_a_plain_install` and `test_pacman_never_runs_sy_alone` (build `Package(name="tree")` and `Package(name="tree", refresh=False)` with the file's existing "absent" current-state helper and assert on `type(p).fix_group([...])`). In `tests/core/test_tools.py` expect `pacman -Syu --noconfirm --needed dmidecode`. In `tests/engine/test_updates.py` add a case: a `checkupdates` exit code of 1 (error) raises `ReadError` with "couldn't check for updates"; if the existing fixtures already pin this, name that test in the commit message instead of adding one.
- [ ] **Step 2: See them fail**, then implement: pacman install `cmds` use `'-Syu' if first.refresh else '-S'`; same in `core/tools.py`; update the `refresh` description: *Arch: refresh and upgrade the whole system together (-Syu); false installs with plain -S, which fails or half-upgrades when the database is stale.*
- [ ] **Step 3: Run** `uv run pytest tests/engine tests/core/test_tools.py -q`; `ruff check src tests`.
- [ ] **Step 4: Commit** `Arch installs run pacman -Syu so a stale sync database no longer 404s (Task 6, not reviewed yet)`.

---

### Task 7: Stale pacman lock and the `refresh: false` warning

**Files:** Modify `src/bastet/engine/packages.py` (`Package.reads`, `current`, `fix_group`), `src/bastet/roles/builtin.py` (`HostInfo`, `_packages`), `src/bastet/cli/run.py` (pass `-y` into `HostInfo`); tests in `tests/engine/test_packages.py` and a new `tests/roles/test_packages_pacman_warnings.py`.

**Interfaces:** Produces: `Package.remove_stale_lock: bool = False` (also in `group_key`); `HostInfo.remove_stale_lock: bool = False`, set from the CLI's `-y`. A pacman `Package` reads the lock state (`none`, `running`, `stale`: `/var/lib/pacman/db.lck` present and `pgrep -x pacman`). `current()` raises `ReadError` when `running` ("pacman is running on this host; try again when it finishes") and, when `stale` and not `remove_stale_lock`, `ReadError("pacman's database lock /var/lib/pacman/db.lck is stale (no pacman is running); rerun with -y to remove it, or remove it yourself")`. With `remove_stale_lock` the fix commands start with `rm -f /var/lib/pacman/db.lck`. The timeout message in `engine/run.py` (`_exec`) mentions that a timed-out `pacman` may still be running or have left a lock.

- [ ] **Step 1: Failing tests:** lock states from a faked read result (the file already fakes `results` dicts) → `ReadError` for `running` and for `stale` without the flag; `stale` with the flag keeps the install and prepends the `rm -f`; `none` changes nothing. In the new test file: `_packages` for an Arch `HostInfo` with `refresh: False` on any package leaves a warning `Note` (level `warning`) on the batch naming `refresh: false`, on every build; a non-Arch host with `refresh: False` leaves none.
- [ ] **Step 2: See them fail; implement.** Note the engine already uses `Note("warning"|"info", role, text)` (`engine.run.Note`) attached to a `Batch`.
- [ ] **Step 3: Run** `uv run pytest tests/engine tests/roles tests/cli -q -x`; `ruff check src tests`.
- [ ] **Step 4: Commit** `pacman: stale lock check, loud warning for refresh: false (Task 7, not reviewed yet)`.

---

### Task 8: `pacman`: reflector (stopgap) and the mirrorlist `NoExtract`

**Files:** Modify `src/bastet/data/roles/pacman/pacman role.md` (new option, entries, docs, `## Changes`, `version: 0.1.1`); Create `tests/roles/test_pacman_reflector.py`; `docs/roles.md` regenerated.

**Interfaces:** Produces: option `reflector` (bool, default `true`; **on by default, listed in the role's docs as an opinionated default**). With it true on an Arch host the role installs `reflector` and enables and starts `reflector.timer`. `etc/pacman.d/mirrorlist` is in `NoExtract` while reflector is on. This is a stopgap: nothing configures reflector (no `reflector.conf`), and the role's docs say so.

- [ ] **Step 1: Failing tests** (build the role like `tests/roles/test_time_role.py`): (a) with no options an Arch host gets `Package("reflector")` and `Unit("reflector.timer", enabled=True, state="up")`; (b) `reflector: false` emits neither; (c) the `pacman.conf` settings contain `NoExtract = etc/pacman.d/mirrorlist` with reflector on and no `no_extract` set, and do not contain it with `reflector: false`; (d) a note that sets its own `no_extract: [usr/share/doc/*]` keeps the user's list and the role leaves a `warning` check that the mirrorlist is then unprotected while reflector is on.
- [ ] **Step 2: Implement** in the role file: option `reflector`; a `packages:` entry `reflector` and a `systemd:` unit entry for `reflector.timer`, both `when: reflector`; the `NoExtract` default through the existing `no_extract` option's mechanism. **If the contract cannot express "mirrorlist protection only while reflector is on" in a few lines of the role file** (the role-level `overrides:` `when` can see merged options before defaults), stop and ask the owner; the fallback is a `no_extract` default of `[etc/pacman.d/mirrorlist]` that applies always, documented as such.
- [ ] **Step 3: Docs.** The role body gets a "What it does with no options" list (reflector installed, timer enabled and started, mirrorlist in `NoExtract`, plus the existing `color`/`candy` defaults) and a line that reflector is a stopgap. The timer starts on its schedule; the role does not run reflector once at apply time (noted in the docs and the roadmap).
- [ ] **Step 4: Run** `uv run pytest tests/roles -q`; `uv run python scripts/gen_roles_doc.py`; `ruff check src tests`.
- [ ] **Step 5: Commit** `pacman: reflector timer and mirrorlist NoExtract, on by default (Task 8, not reviewed yet)`.

---

### Task 9: Gather copies the generated groups into a user folder

**Files:** Modify `src/bastet/core/render.py` (the group generation near `GROUPS_DIR = "_bastet/groups"`, the `_write_group` helper); tests next to `tests/core/test_render.py` (new file `tests/core/test_group_copy.py`).

**Interfaces:** Produces: the generated OS and type groups are written once to `groups/<ident>.md` in the inventory (a user folder) instead of `_bastet/groups/`; **an existing note of that name is never overwritten** (the user's copy wins); `_bastet/groups/<ident>.md` is no longer written.

- [ ] **Step 1: Failing tests:** (a) after a refresh of an inventory whose host is `os: Arch Linux` there is `groups/arch.md` with `bastet: group` and `match: {os: arch}`, and no `_bastet/groups/arch.md`; (b) the user edits `groups/arch.md` (adds a line to the body), a second refresh leaves it byte-for-byte unchanged; (c) a user note named `vps` elsewhere in the inventory is not overwritten and no `groups/vps.md` is created.
- [ ] **Step 2: Implement.** `_write_group` targets `root/"groups"/f"{ident}.md"`; if `inv.get(ident)` exists (any path) do nothing; otherwise create. Keep the body text (it already says how to point a role note at the group); change "Generated by Bastet" to say it is a copy the user may edit. Leave the existing behaviour that drops a stale generated group when a user note of the same name exists.
- [ ] **Step 3: Run** `uv run pytest tests/core tests/cli -q -x`; `ruff check src tests`.
- [ ] **Step 4: Commit** `Generated groups are copied once into groups/ and never overwritten (Task 9, not reviewed yet)`.

---

### Task 10: The `base` role in Markdown

**Files:** Create `src/bastet/data/roles/base/base role.md`, `tests/roles/test_base_role.py`; `docs/roles.md` regenerated.

**Interfaces:** Produces: role `base`, version `0.1.0`, options `tools` (list of strings, default `[vim, zsh, git, htop, tree, gdu, wget, less]`), `extra_tools` (list, no default, adds on top), `microcode` (`auto` default or `never`), `baseline` (**reserved**: string, documented as unused, no effect). Opinionated defaults are documented in the role's body.

Rules from the spec: a note that sets `tools` replaces the default list; `extra_tools` adds at every level; microcode on physical hosts only; the package comes from the OS and CPU vendor (Arch `intel-ucode`/`amd-ucode`; Debian `intel-microcode`/`amd64-microcode`, one table in the role file, no Debian code); every error the old Python raised becomes a `checks:` error (no CPU fact naming `bastet run -g`; unknown vendor; no package known for the OS); a virtual host gets an info note. The Debian `non-free-firmware` note is deferred.

- [ ] **Step 1: Failing tests** (`tests/roles/test_base_role.py`; helper `build(values, system, cpu)` as in `test_time_role.py`; systems: Arch server, Debian server, Arch vm, lxc, Alpine server):

```python
def test_no_options_on_a_physical_arch_host_installs_the_default_tools_and_microcode(): ...  # 8 tools + intel-ucode for an Intel CPU fact
def test_setting_tools_replaces_the_default_list_and_extra_tools_adds(): ...
@pytest.mark.parametrize("system,cpu,package", [...])  # arch/debian x intel/amd -> the four packages
def test_microcode_package_by_os_and_vendor(system, cpu, package): ...
def test_a_vm_or_container_gets_tools_only_and_an_info_note(): ...
def test_microcode_never_installs_no_microcode(): ...
def test_a_physical_host_without_a_cpu_fact_is_an_error_naming_run_g(): ...
def test_an_unknown_vendor_and_an_os_without_a_package_are_errors(): ...  # parametrize both
def test_baseline_is_accepted_and_changes_nothing(): ...
```

How an error `check` surfaces (copy the form `test_time_role.py` uses for the Debian `ntp: true` error). Write every test completely.
- [ ] **Step 2: See them fail.**
- [ ] **Step 3: Write the role note** (frontmatter `bastet: role-definition`, `name: base`, `version: 0.1.0`, `api: 0`, `description`, `starter: {extra_tools: []}` only if the starter mechanism needs a value; options above; `checks:`; `packages:` with `each: tools`, `each: extra_tools`, and four `when:`-guarded microcode entries; examples; `## Changes`). Microcode conditions use `host.physical`, `host.arch_like`, `host.debian_like`, `host.cpu` (a lowercase `'intel' in host.cpu|lower` test; if the sandbox lacks `lower`, use a `{% if %}` form). The body lists exactly what it does with no options.
- [ ] **Step 4: Run** `uv run pytest tests/roles -q` (parse, docs and accounts tests see the new role); `uv run python scripts/gen_roles_doc.py`; `ruff check src tests`.
- [ ] **Step 5: Commit** `base: a Markdown role with the old role's tools and microcode (Task 10, not reviewed yet)`.

---

### Task 11: Roadmap and version

**Files:** `docs/ROADMAP.md`, version files via `scripts/version-bump`.

- [ ] **Step 1: Roadmap.** Tick the cleanup, AUR removal, `supersedes`, Arch installs (`-Syu`, lock check, warning), reflector stopgap and `base` rows in step 3 of the VPS apps; leave the deferred rows (Debian round, optional deps, group generation, packages split, reflector configuration, sysctl, ssh/harden rebuilds, test audit) as written; add "reflector runs on its timer, not once at apply time" to the pacman row; set "next" to `caddy`.
- [ ] **Step 2: Version.** This round changes code, roles and behaviour: `scripts/version-bump 0.3.0` (rewrites `pyproject.toml`, the time zone list, `role-hashes.txt`, `docs/roles.md`); `scripts/version-bump --check` must print nothing. Commit them together.
- [ ] **Step 3: Final checks.** `ruff check src tests`, `scripts/privacy-check`, `uv run pytest tests/roles tests/engine tests/core tests/cli -q`. Do **not** run the container contract suite or the full suite; give the owner `cd <worktree> && uv run pytest -q` and wait for his "passed". Note which contract tests were already failing before this plan (`test_roles_contract`, `test_arch_updates_reported`) in the ledger.
- [ ] **Step 4: Commit** `ROADMAP: base, supersedes and Arch installs done; Bastet 0.3.0 (Task 11, not reviewed yet)`.

## Self-review (2026-10-14)

- **Spec coverage:** in-round list (spec section 13): cleanup (2, 3), `supersedes` with typo check and display (4, 5), CLAUDE.md and skills (1), `-Syu`, lock check, warning (6, 7), reflector and `NoExtract` (8), groups copy (9), `base` (10), roadmap (11). `caddy`/`forgejo`/`vaultwarden` are named as separate plans.
- **Placeholders:** the `...` tests in Tasks 2, 4, 5, 7, 8 and 10 are named with the exact behaviour to assert; the implementer writes them out in full (each step says so).
- **Names:** `supersedes`, `Option.supersedes`, `remove_stale_lock`, `reflector`, `extra_tools`, `baseline` are used the same way in every task they appear in.
- **Open for the owner's read:** (a) the lock rule is "refuse with instructions unless `-y`" (decision 2); (b) `NoExtract` fallback in Task 8 if "only while reflector is on" cannot be expressed simply; (c) Task 5 applies the target role when it has no note.
