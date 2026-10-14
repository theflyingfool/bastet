# Cleanup, `supersedes`, Arch installs and the `base` role — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. In this repo, the `bastet-run-plan` skill supplies the Bastet-specific parts; the `bastet-new-role` skill holds the role checklist.

**Status:** written 2026-10-14 from the approved spec. **Awaiting the owner's read; no code is written yet.**

**Goal:** VPS apps, step 3: remove the unconverted `ssh`, `harden` and old `base` roles and the AUR; add the `supersedes` contract key and shipped default roles; make Arch installs work against a stale database; bring `pacman` with Arch and add a reflector stopgap; copy the generated groups into a user folder; rewrite `base` in Markdown.

**Architecture:** Cleanup first (so there is less to cross-check), then one contract feature (`supersedes`), then changes inside the `packages` building block and the `pacman` Markdown role, then `base` as a Markdown role. `packages` is a building block-role and stays Python. `caddy`, `forgejo` and `vaultwarden` are **not in this plan**: each gets its own short plan after `base` lands, written on the finished contract.

**Tech Stack:** Python ≥3.12, pydantic, PyYAML, Jinja2 (existing sandbox), pytest, ruff.

**Spec:** `docs/specs/2026-10-14-bastet-package-roles-and-base-design.md`. Models: `src/bastet/data/roles/time/time role.md`, `.../pacman/pacman role.md`. Test rules: `docs/testing.md`.

## Global Constraints

- **Unit tests** never touch the real inventory, `~/.config/bastet`, `~/.local/share/bastet`, `~/.ssh`, the real `~/.cache` or `$XDG_RUNTIME_DIR`; no network; `tmp_path` only; placeholder data only (10.1.x.x addresses, host names like pve1/media01). Follow `docs/testing.md`: a few focused tests per task, `parametrize`, no sleeps, no duplicate layers.
- **Test file basenames unique across `tests/`** (no `__init__.py`).
- Every message goes through `bastet.ui.out`; no `typer.echo` in `src/`; no "spec §"/"Task N" references in `src/`.
- The version is written only in `pyproject.toml`, bumped with `scripts/version-bump` (Task 12).
- `docs/roles.md` is generated (`uv run python scripts/gen_roles_doc.py`); a repo test checks it.
- `ruff check src tests` and `scripts/privacy-check` pass before the final commit (copy the ignored `.privacy-patterns` into a fresh worktree first, then delete the copy).
- Nothing in Bastet deletes notes, records or host files; this plan adds no deletion. Removing a role from `src/` reverts nothing on hosts.
- A building block is a role too, the special ones that stay Python (`packages`, `users`, `files`, `systemd`); every other role is Markdown. A role may do something with no options only when its own docs list exactly what (the opinionated-defaults principle in the spec, section 15).
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` and the `Claude-Session:` line; first line ends `(Task N, not reviewed yet)`.
- The owner runs the full suite and says when it passed.

**Priority (owner, D-032):** the biggest push is reaching the point where Markdown roles can be written so the VPS can run; cleanup of the current roles and the destructive features come after. If the round runs long, **Task 10 (groups copy) is the first to drop to the next round**; it is not needed to write roles.

## Decisions carried from the spec (not to be reopened in the tasks)

1. `ssh` and `harden` are removed now and rebuilt last; **Bastet assumes SSH port 22 everywhere** (no `ssh_port` field). Their code is copied to `refs/` first.
2. Arch installs always `pacman -Syu --noconfirm --needed`; `refresh: false` keeps `-S` and warns loudly. **The stale `db.lck` check is deferred** (roadmap).
3. `supersedes: <role>.<option>` marks a manager option as overriding another role's option; rank first, a tie goes to the role with `supersedes`, and it runs **before** a role's own `overrides:`. No existing role uses it this round.
4. `packages` and `base` are **shipped default roles** (a new `defaults.yml`, not `bastet init`); `pacman` comes with Arch through `oses/arch.yml`, as `systemd` does.
5. Deferred (roadmap): the pacman lock check, Debian/`apt`/`debian.yml`, optional dependencies as dependencies, moving options between `packages` and the managers, `init` generating groups, the gather prompt, `add group`, reflector configuration, sysctl, `tools` baselines.

## Review Focus

1. A note still naming a removed role (`base` old, `ssh`, `harden`) fails the host with the existing `unknown role` message, and other hosts are unaffected. (Task 2)
2. `supersedes` naming a role or option that does not exist fails the role load with a message naming the role file and key; a type mismatch is refused. (Task 4)
3. A host with the superseding role but no `packages` note still gets the value. (Task 5)
4. An unreachable mirror during the update check never reads as "nothing pending"; `refresh: false` on an Arch host warns on every run. (Tasks 7 and 8)
5. `base` on a physical host with no or an unknown CPU fact is an error naming `bastet run -g`; on a VM or container it installs nothing; `base` with no options on a physical Arch host installs the default tools and the right microcode package. (Task 11)

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

**Rule (owner): remove nothing that still works.** Only the three roles themselves move to `refs/` (their folders, `system.py`, their `BUILDERS` entries and imports, and the tests of those roles), and the AUR code goes in Task 3. Everything else that mentions them but still works is left alone and listed in the roadmap as cleanup debt.

**Interfaces:** Produces: `BUILDERS = {"systemd", "packages", "users", "files"}`. `ORDER`, `HostInfo.ssh_ports`, the `ssh` lookup in `batches_for` and `cli/common.py`'s port functions stay as they are: with no `ssh` role they do nothing harmful, and `ssh_port()` already answers 22 when no `ssh` role applies.

What depends on the old roles (checked in the code):

| Dependency | Where | Decision |
|---|---|---|
| Python builders and helpers | `roles/system.py` | Copy to `refs/`, delete |
| `BUILDERS` entries and the `system` import | `roles/builtin.py:211` | Remove (they would not import once `system.py` is gone) |
| `ORDER` names, `HostInfo.ssh_ports`, the `ssh` lookup in `batches_for` | `roles/builtin.py:24,36,216` | **Leave alone** (harmless dead code); roadmap cleanup debt |
| Role definitions | `data/roles/{base,ssh,harden}/role.yml` | Copy to `refs/`, `git rm` |
| Port Bastet connects on | `cli/common.py` `ssh_port`, `_role_ports`, `ssh_ports` | **Leave alone**: no `ssh` role means the lookup finds nothing and the port is 22. A host that still has an `ssh` note gets the existing "roles couldn't be read; connecting on port 22" warning, which is accurate. Roadmap cleanup debt |
| Role-only tests | `tests/roles/test_harden_role.py`, `test_ssh_role.py`; `base`/`ssh`/`harden` cases in `test_system_roles.py`, `test_builtin.py` | Delete or trim; `packages`/`users` cases stay |
| Port tests | `tests/cli/test_ssh_port.py` | Keep the "default is 22" case; move the tests that write an `ssh` role note (they test the removed role) to `refs/` |
| Container contract tests | `tests/contract/test_contract.py`: `test_base_contract`, `test_ssh_contract`, `test_harden_contract`, `test_arch_harden_reports_contract` | Delete |
| Tests using the names as example data | `tests/cli/test_add_role.py`, `test_common.py`, `test_secret_leaks.py`, `tests/core/test_inventory.py`, `test_render.py`, `test_pages.py` | Grep each; switch to a surviving role (`packages`, `files`, `time`, `pacman`); leave unrelated words alone (ssh the command, Obsidian "Bases") |
| Type and OS default roles | `data/types/*.yml`, `oses/arch.yml` | None name them (verified) |
| `engine/security.py` and its tests | lynis, exposure, ports, vulnerable packages, AppArmor | Stay; only the role that called them goes |
| `role-hashes.txt` | lists the three | `scripts/version-bump` rewrites it (Task 12) |
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

Fill in the second test from `tests/roles/test_resolve.py`'s inventory helper; it must be complete, not a stub. `base` is not asserted missing here because it returns in Task 11.
- [ ] **Step 2: See them fail** (`uv run pytest tests/roles/test_removed_roles_unknown.py -q`).
- [ ] **Step 3: Copy first.** `mkdir -p refs/removed-2026-10-14 && cp -r src/bastet/data/roles/{base,ssh,harden} src/bastet/roles/system.py tests/roles/test_harden_role.py tests/roles/test_ssh_role.py tests/cli/test_ssh_port.py refs/removed-2026-10-14/ && git show HEAD:tests/contract/test_contract.py > refs/removed-2026-10-14/test_contract.py`, then `ls refs/removed-2026-10-14` to confirm. `refs/` is git-ignored, so this is the only working reference (sysctl, fail2ban and sshd logic for the later rebuilds).
- [ ] **Step 4: Remove and edit** per the table: `git rm -r` the three role folders and `system.py`; edit `builtin.py` (only the `BUILDERS` entries and the import); do **not** touch `cli/common.py`; trim or delete the tests of the removed roles; regenerate `docs/roles.md`; edit `using_roles.md`.
- [ ] **Step 5: Run** `uv run pytest tests/roles tests/cli tests/core tests/engine -q -x`, `uv run python -c "import bastet.roles.builtin"`, `ruff check src tests`. Expected: pass.
- [ ] **Step 6: Commit** `Move ssh, harden and the old base to refs/ (Task 2, not reviewed yet)`.

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
def test_a_role_override_that_clears_the_option_wins_over_supersedes(...): ...  # the target role's own overrides: clears the option on this host; the superseding value does not come back
```

Write all six completely.
- [ ] **Step 2: See them fail.**
- [ ] **Step 3: Implement.** In `resolve`, keep per-role pre-default `merged`, `origins` and a new `ranks: dict[str, tuple]` (the highest rank among sources that set each key) in a list instead of appending `Applied` straight away; run `_apply_supersedes` over that list (create the target's entry when missing from `roles[target]`); then, per role, apply the role's own `overrides:` (`_apply_role_overrides`), `check_relations`, `with_defaults` and build `Applied`. **The order is: merge, `supersedes`, the role's own `overrides:`, relations, defaults**, so a role's deliberate clearing of an option still wins over a superseding value, and `requires`/`conflicts` see the final value. Keep the final sort by role name. `resolved_table` prints, under a manager role with shared options, a line per shared option with the effective value and `from <origin>` even when the manager's own value is unset.
- [ ] **Step 4: Run** `uv run pytest tests/roles -q`; `ruff check src tests`.
- [ ] **Step 5: Commit** `Resolver: supersedes decides by rank, ties to the superseding role, and is shown in the table (Task 5, not reviewed yet)`.

---

### Task 6: Shipped default roles (`packages` for every host)

**Files:** Create `src/bastet/data/defaults.yml`; Modify `src/bastet/core/osdefaults.py` (or a small new loader next to it), `src/bastet/roles/resolve.py` (`sources_for`), `src/bastet/data/docs/writing_roles.md`; Create `tests/roles/test_shipped_default_roles.py`.

**Interfaces:** Produces: `data/defaults.yml` with `roles: {packages: {}}` (the file may carry `overrides:` per role like an OS file); a source with rank `(-2,)` and label `Bastet default` for every managed host. Unmanaged host types still get nothing (`resolve` returns early for them). `base` is added to this file in Task 11, when the role exists.

- [ ] **Step 1: Failing tests:** (a) a host with no role notes at all resolves `packages` with origin `Bastet default`; (b) a lab note for `packages` overrides the shipped default and the origin reads `lab`; (c) an unmanaged host type (for example `unifi`) gets no roles; (d) the shipped file names only roles that exist (`set(defaults) <= set(load_roles())`). Use the inventory helper in `tests/roles/test_resolve.py`.
- [ ] **Step 2: See them fail; implement.** Load the file once (cache like `load_os_defaults`), add the source in `sources_for` before the OS default source, and add `Bastet default` to the resolved table's origin labels.
- [ ] **Step 3: Expect existing tests to change.** `packages` is now applied to every managed host, so `_packages` also emits `Reboot` and the `Unaccounted` report on hosts that had no `packages` note (more items on a `check`). Run `uv run pytest tests -q -x --ignore=tests/contract`, fix the tests whose counts or expected role lists change (minimally, without weakening what they pin), and list each one in your report. Document the behaviour in the `packages` role's description.
- [ ] **Step 4: Run** `uv run pytest tests/roles tests/cli tests/core tests/engine -q`; `ruff check src tests`.
- [ ] **Step 5: Commit** `Shipped default roles: packages reaches every managed host (Task 6, not reviewed yet)`.

---

### Task 7: Arch installs use `pacman -Syu`

**Files:** Modify `src/bastet/engine/packages.py` (`Package.fix_group`), `src/bastet/core/tools.py:22`, `src/bastet/data/roles/packages/role.yml` (the `refresh` and `full_upgrade` descriptions); tests `tests/engine/test_packages.py`, `tests/core/test_tools.py`, `tests/engine/test_updates.py`.

**Interfaces:** Produces: for `manager == "pacman"` and `state == "present"` the install command is `pacman -Syu --noconfirm --needed{extra} -- <pkgs>` when `refresh` is true (the default) and `pacman -S --noconfirm --needed{extra} -- <pkgs>` when `refresh=False`. Removal commands are unchanged. `pacman -Sy` alone appears nowhere.

- [ ] **Step 1: Failing tests** in `tests/engine/test_packages.py`: change the pacman case at the parametrized table (`"pacman -S --noconfirm --needed -- tree"`) to `-Syu`, add `test_pacman_refresh_false_keeps_a_plain_install` and `test_pacman_never_runs_sy_alone` (build `Package(name="tree")` and `Package(name="tree", refresh=False)` with the file's existing "absent" current-state helper and assert on `type(p).fix_group([...])`). In `tests/core/test_tools.py` expect `pacman -Syu --noconfirm --needed dmidecode`. In `tests/engine/test_updates.py` add a case: a `checkupdates` exit code of 1 (error) raises `ReadError` with "couldn't check for updates"; if the existing fixtures already pin this, name that test in the commit message instead of adding one.
- [ ] **Step 2: See them fail**, then implement: pacman install `cmds` use `'-Syu' if first.refresh else '-S'`; same in `core/tools.py`; update the `refresh` description: *Arch: refresh and upgrade the whole system together (-Syu); false installs with plain -S, which fails or half-upgrades when the database is stale.*
- [ ] **Step 3: Run** `uv run pytest tests/engine tests/core/test_tools.py -q`; `ruff check src tests`.
- [ ] **Step 4: Commit** `Arch installs run pacman -Syu so a stale sync database no longer 404s (Task 7, not reviewed yet)`.

---

### Task 8: The `refresh: false` warning on Arch

**Files:** Modify `src/bastet/roles/builtin.py` (`_packages`); Create `tests/roles/test_packages_refresh_warning.py`.

**Interfaces:** Produces: when an Arch-like host's `packages` role has `refresh: false`, the `packages` batch carries a `Note("warning", "packages", ...)` naming `refresh: false` and saying a stale database can 404 or half-upgrade the system; it is built on every run. Other hosts get no note. (The lock check is deferred.)

- [ ] **Step 1: Failing tests:** an Arch `HostInfo` with `refresh: False` gets the note, and a Debian one does not; the note is present on each of two consecutive builds (not one-time).
- [ ] **Step 2: See them fail; implement** in `_packages` (the engine already uses `Note("warning"|"info", role, text)` attached to a `Batch`).
- [ ] **Step 3: Run** `uv run pytest tests/roles tests/engine -q -x`; `ruff check src tests`.
- [ ] **Step 4: Commit** `packages: loud warning for refresh: false on Arch (Task 8, not reviewed yet)`.

---

### Task 9: `pacman`: comes with Arch; reflector (stopgap) and the mirrorlist `NoExtract`

**Files:** Modify `src/bastet/data/roles/pacman/pacman role.md` (new option, entries, docs, `## Changes`, `version: 0.2.0`); Create `tests/roles/test_pacman_reflector.py`; `docs/roles.md` regenerated.

**Interfaces:** Produces: option `reflector` (bool, default `true`; **on by default, listed in the role's docs as an opinionated default**). With it true on an Arch host the role installs `reflector` and enables and starts `reflector.timer`. `etc/pacman.d/mirrorlist` is in `NoExtract` while reflector is on. This is a stopgap: nothing configures reflector (no `reflector.conf`), and the role's docs say so.

- [ ] **Step 1: Failing tests** (build the role like `tests/roles/test_time_role.py`): (a) with no options an Arch host gets `Package("reflector")` and `Unit("reflector.timer", enabled=True, state="up")`; (b) `reflector: false` emits neither; (c) the `pacman.conf` settings contain `NoExtract = etc/pacman.d/mirrorlist` with reflector on and no `no_extract` set, and do not contain it with `reflector: false`; (d) a note that sets its own `no_extract: [usr/share/doc/*]` keeps the user's list and the role leaves a `warning` check that the mirrorlist is then unprotected while reflector is on.
- [ ] **Step 2: Implement** in the role file: option `reflector`; a `packages:` entry `reflector` and a `systemd:` unit entry for `reflector.timer`, both `when: reflector`; the `NoExtract` default through the existing `no_extract` option's mechanism. **If the contract cannot express "mirrorlist protection only while reflector is on" in a few lines of the role file** (the role-level `overrides:` `when` can see merged options before defaults), stop and ask the owner; the fallback is a `no_extract` default of `[etc/pacman.d/mirrorlist]` that applies always, documented as such.
- [ ] **Step 3: Bring `pacman` with Arch.** Add `pacman: {}` to `roles:` in `src/bastet/data/oses/arch.yml` (the way `systemd` is there) and update the comment above it. Update `tests/roles/test_os_default_roles.py` (and any other test that expects Arch to come with only `systemd`) to expect both; the origin reads `OS default (arch)`. Because `pacman` already defaults `color` and `candy` to true and now `reflector` too, every Arch host changes `pacman.conf` and installs reflector with no options: the role's docs must list this.
- [ ] **Step 3b: Docs.** The role body gets a "What it does with no options" list (reflector installed, timer enabled and started, mirrorlist in `NoExtract`, plus the existing `color`/`candy` defaults) and a line that reflector is a stopgap. The timer starts on its schedule; the role does not run reflector once at apply time (noted in the docs and the roadmap).
- [ ] **Step 4: Run** `uv run pytest tests/roles -q`; `uv run python scripts/gen_roles_doc.py`; `ruff check src tests`.
- [ ] **Step 5: Commit** `pacman: reflector timer and mirrorlist NoExtract, on by default (Task 9, not reviewed yet)`.

---

### Task 10: Gather copies the generated groups into a user folder

**Files:** Modify `src/bastet/core/render.py` (group generation near `GROUPS_DIR = "_bastet/groups"` and `_write_group`), `src/bastet/core/inventory.py:267-271` (the type-name check); Create `tests/core/test_group_copy.py`.

**Interfaces:** Produces: the generated OS and type groups are written once to `groups/<ident>.md` (a user folder) instead of `_bastet/groups/`. An existing note of that name that is **not** a Bastet-generated one (`_generated(root, path)` is false) is never overwritten, so the user's copy wins. Generated notes under `_bastet/` do not count as "existing". A group named like a host type is accepted when its `match` is exactly that type's rule; a user's own group with that name and any other content still errors (`inventory.py`).

What exists today (verified): the owner's inventory already has `_bastet/groups/arch.md`, `vps.md`, `unifi.md`, `undefined.md`. `_write_group` skips when `inv.get(ident)` finds any note of that name, which would find those, and `inventory.py` raises an error for a non-generated group named like a type.

- [ ] **Step 1: Failing tests:** (a) refresh of an inventory with an Arch host and a `vps` host creates `groups/arch.md` (`match: {os: arch}`) and `groups/vps.md` (`match: {type: vps}`), and writes nothing under `_bastet/groups/`; (b) with a pre-existing generated `_bastet/groups/arch.md`, the copy still happens, and loading the inventory reports no error for the type-named `groups/vps.md`; (c) a user edit of `groups/arch.md` survives a second refresh byte for byte; (d) a user note named `arch` elsewhere is not overwritten and no `groups/arch.md` is created; (e) a user group named `vps` with a different `match` still errors.
- [ ] **Step 2: See them fail; implement.** Point `_write_group` at `root/"groups"/f"{ident}.md"`, test existence with "a note of that name whose path is not under `_bastet/`", and change the `inventory.py` check as described. The stale `_bastet/groups/*.md` files: once a copy exists the existing rule that drops a generated group when a user note of the same name exists removes them; add a test line for it. Change the body text from "Generated by Bastet" to say it is a copy the user may edit.
- [ ] **Step 3: Run** `uv run pytest tests/core tests/cli tests/roles -q -x`; `ruff check src tests`.
- [ ] **Step 4: Commit** `Generated groups are copied once into groups/ and never overwritten (Task 10, not reviewed yet)`.

---

### Task 11: The `base` role in Markdown

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
- [ ] **Step 3b: Ship it by default.** Add `base: {}` to `src/bastet/data/defaults.yml` (Task 6) so every managed host gets it; update `tests/roles/test_shipped_default_roles.py` to expect `packages` and `base`. Expect hosts with a CPU fact of an unknown vendor to see the `base` error check; that is the intended behaviour.
- [ ] **Step 4: Run** `uv run pytest tests/roles -q` (parse, docs and accounts tests see the new role); `uv run python scripts/gen_roles_doc.py`; `ruff check src tests`.
- [ ] **Step 5: Commit** `base: a Markdown role with the old role's tools and microcode (Task 11, not reviewed yet)`.

---

### Task 12: Roadmap and version

**Files:** `docs/ROADMAP.md`, version files via `scripts/version-bump`.

- [ ] **Step 1: Roadmap.** Tick the cleanup, AUR removal, `supersedes`, shipped default roles, Arch installs (`-Syu`, warning), `pacman` with Arch, reflector stopgap and `base` rows in step 3 of the VPS apps; leave the deferred rows (pacman lock, Debian round, optional deps, group generation, packages split, reflector configuration, sysctl, ssh/harden rebuilds, test audit) as written; set "next" to `caddy`, and write the "next session starts here" handoff line.
- [ ] **Step 2: Version.** This round changes code, roles and behaviour: `scripts/version-bump 0.3.0` (rewrites `pyproject.toml`, the time zone list, `role-hashes.txt`, `docs/roles.md`); `scripts/version-bump --check` must print nothing. Commit them together.
- [ ] **Step 3: Final checks.** `ruff check src tests`, `scripts/privacy-check`, `uv run pytest tests/roles tests/engine tests/core tests/cli -q`. Do **not** run the container contract suite or the full suite; give the owner `cd <worktree> && uv run pytest -q` and wait for his "passed". Note which contract tests were already failing before this plan (`test_roles_contract`, `test_arch_updates_reported`) in the ledger.
- [ ] **Step 4: Commit** `ROADMAP: base, supersedes and Arch installs done; Bastet 0.3.0 (Task 12, not reviewed yet)`.

## Self-review (2026-10-14)

- **Spec coverage:** in-round list (spec section 13): cleanup (2, 3), `supersedes` with typo check and display (4, 5), CLAUDE.md and skills (1), `-Syu`, lock check, warning (6, 7), reflector and `NoExtract` (8), groups copy (9), `base` (10), roadmap (11). `caddy`/`forgejo`/`vaultwarden` are named as separate plans.
- **Placeholders:** the `...` tests in Tasks 2, 4, 5, 7, 8 and 10 are named with the exact behaviour to assert; the implementer writes them out in full (each step says so).
- **Names:** `supersedes`, `Option.supersedes`, `remove_stale_lock`, `reflector`, `extra_tools`, `baseline` are used the same way in every task they appear in.
- **Open for the owner's read:** (a) `NoExtract` fallback in Task 9 if "only while reflector is on" cannot be expressed simply; (b) Task 5 applies the target role when it has no note; (c) Task 6 makes `packages` apply to every managed host, which adds the unaccounted report and reboot policy everywhere.
