# Simplification and UX — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this repo, the `bastet-run-plan` skill supplies the Bastet-specific parts.

**Goal:** fewer commands, fewer concepts, one rule for who writes what, and a first run that guides you. Decided with the user on 2026-10-07 (notes: `.superpowers/simplify-notes.md`).
- **`bastet run`** replaces `gather`, `check` and `apply`, and takes host selectors.
- **Hardware notes get the same split as hosts:** your fields in your note, gathered facts in Bastet's. Attribution and `--take` disappear.
- **One Bastet note per host and per hardware item.**
- **Every command makes at most one commit.**
- **A templates folder replaces `add hardware`.**
- **`bastet doctor [--fix]`** finds and fixes problems.
- **Smaller UX fixes:** lenient yes/no and numbers, "did you mean", next-step hints, tab completion, clear push messages.
- **User documentation lives in the vault,** linked from `Homelab.md` and from the notes where it helps.

**Architecture:** this is mostly CLI reshaping on top of the existing engine and parallel runner. The note model extends subplan 1's `factsnote`/`hostview` pattern to hardware, and merges the summary and reports notes into the facts note. No new subsystems.

**Tech Stack:** as before (Python ≥3.12, uv, Typer, pytest).

**Spec:**
- `docs/specs/2026-09-30-bastet-design.md` §5.3 (hardware), §7 (gather and attribution, replaced here), §12 (commands);
- `docs/specs/2026-10-06-bastet-roles-design.md` §2 (who writes what).

Task 9 updates both.

**Roadmap:** `docs/ROADMAP.md`. This plan runs before roles subplan 2.

## Global Constraints

- **Unit tests:**
  - never touch the real inventory, `~/.config/bastet`, `~/.local/share/bastet`, `~/.ssh`, the real `~/.cache` or `$XDG_RUNTIME_DIR`;
  - no network;
  - `tmp_path` only;
  - placeholder data only (see "Example data" in `docs/ROADMAP.md`).
- **Who writes what:**
  - **Automatic commands** (`run` in any mode, `refresh`) never *modify* your notes: `hosts/`, `hardware/`, groups, locations, `Homelab.md`, `_roles/`.
  - They may **create** a note for something newly discovered: a hardware item, an offered guest. It's shown in the diff and asked about, as today.
  - Everything Bastet works out lives in its own notes under `_bastet/`.
- **Bastet isn't stable:** the old commands are removed, with no aliases.
- **Commit trailer:**
  ```
  Co-Authored-By: <model> <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01SgYSJBjMmf52EmoGk4d4zN
  ```
  Stage by name, never `git commit -a`. The privacy pre-commit hook runs on every commit.
- **Each task:** failing tests first and seen failing, then implement, then the full `uv run pytest -q` green.

## Review Focus

1. **`run` defaulting to apply.** A bare `bastet run` must show every host's plan and ask before changing anything. With `-y` it applies without asking, and that's the only way it does.
2. **Selectors that match nothing, or match more than meant.**
   - An unknown `@name` and an empty glob are errors.
   - `--exclude` is applied after the union.
   - A destroyed host is never selected unless named exactly.
3. **The hardware split loses nothing you typed.** Your fields on existing hardware notes stay where they are and are never rewritten. A gathered key still on an old hardware note is ignored and reported, like on host notes. `doctor --fix` removes it only once Bastet's note holds a value, and reports each removal.
4. **One commit per command,** including a `run` that writes facts notes, creates hardware notes and regenerates summaries. A refresh that can't run says why, in plain sight.
5. **Hardware that disappears** (the missing-DIMM case) is loud: on the dashboard's needs-attention list, on the host's note and on the item's note, until it's seen again or you change its status.

---

### Task 1: `bastet run` and host selectors

**Files:**
- `src/bastet/cli/run.py` (absorbs `gather`'s entry point; the gather internals stay in `cli/gather.py` as functions).
- `src/bastet/cli/app.py` (register `run`; remove `gather`, `check`, `apply`, `map`; hide `refresh` from the main help).
- Delete `src/bastet/cli/map.py`.
- Create `src/bastet/core/selectors.py`.
- `src/bastet/cli/show.py` (accepts selectors).
- Tests: `tests/core/test_selectors.py`, `tests/cli/test_run_cli.py`. Adapt every CLI test that invokes `gather`, `check`, `apply` or `map`.

**Interfaces (produces):**
```python
def select_hosts(inv: Inventory, types: dict[str, HostType], selectors: list[str], exclude: list[str]) -> list[Document]
# "name" exact host; "@lab" every host; "@<type>" hosts of that type; "@<group>" members by the same rules roles use
# (groups:, nesting, match:); a glob ("arch-*") on host names. Union, deduplicated, inventory order; then exclude.
# Errors: unknown @name (lists groups and types), a glob matching nothing, an exact name that isn't a host.
# No selectors = every host that isn't state: destroyed; a destroyed host only when named exactly.
```

**Behaviour:**
- **Modes:**

  | Command | Does |
  |---|---|
  | `bastet run [selectors…]` | Today's `apply`: check, show every plan, ask once, apply, verify, reboot per policy |
  | `bastet run -c / --check [selectors…]` | Today's `check` |
  | `bastet run -g / --gather [selectors…]` | Today's `gather` |
  | `bastet run -g -a` | Gather, then apply, in one run, with one commit |
  | `bastet run -c -a` | An error: "check or apply, not both" |

  `-g -c` means gather, then check.
- **Options:**
  - `-y`, `-j/--jobs`, `-v`, `--exclude` (repeatable) and `--accept-new-hostkey` apply to every mode that connects;
  - `--updates` only when applying.
- **`-y` means one thing everywhere:** "don't ask; go ahead with the defaults". Remove it from anywhere nothing asks. Help text says exactly that.
- **`show [selectors…]`:** one name shows that object as today; a selector shows a table of the matching hosts.
- **`refresh`** stays as a command, hidden from `bastet --help`, and always regenerates the maps.

**Tests:**
- Each selector form.
- Union and order.
- `--exclude`.
- Each error.
- The destroyed-host rule.
- Each mode dispatches to the right existing code path. Assert with the fakes the current check/apply/gather tests use.
- `-c -a` errors.
- Bare `run` asks before applying, and `-y` doesn't.
- `map`, `gather`, `check` and `apply` no longer exist.
- `refresh` works and is absent from the main help.

### Task 2: Type names: `proxmox`, reserved

**Files:**
- Rename `src/bastet/data/types/proxmox-node.yml` → `proxmox.yml` (`name: proxmox`).
- Every `proxmox-node` reference in `src/`, `tests/`, `docs/` and `README.md`.
- `src/bastet/core/inventory.py`: a group note whose name equals a type name is an error.

**Behaviour:**
- **The type is `proxmox`.** The `proxmox` role keeps its name; roles and types are different namespaces.
- **A group note named like any type** gives: "groups/lxc.md: 'lxc' is a host type; type groups are automatic, so rename this group".
- **A host still saying `type: proxmox-node`** is an inventory error: "unknown type 'proxmox-node' (renamed to proxmox)". No migration code beyond that message.

**Tests:**
- Type loading.
- The reserved-name error.
- The old-name message.
- `@proxmox` selects nodes.

### Task 3: Hardware notes split

**Files:**
- `src/bastet/core/hardware.py` (`plan_hardware`), `src/bastet/core/factsnote.py` (hardware facts notes), `src/bastet/core/hostview.py` (`hardware_data`).
- `src/bastet/core/render.py`, `src/bastet/core/cabling.py` (read hardware through `hardware_data`).
- `src/bastet/core/gatherplan.py`, `src/bastet/cli/gather.py`.
- Delete `src/bastet/core/attribution.py` and `merge_facts`; remove `--take`.
- Tests: `tests/core/test_hardware.py`, `tests/core/test_hardware_plan.py`, `tests/cli/test_gather.py`. Delete the attribution tests.

**Interfaces (produces):**
```python
HARDWARE_YOURS = ("price", "vendor", "purchased", "location", "warranty_until", "status", "notes")  # always present on your note
def hardware_facts_path(root: Path, item: str) -> Path     # _bastet/facts/<item> facts.md
def hardware_data(inv: Inventory, doc: Document) -> dict    # facts overlaid with your fields; gathered keys on your note ignored
def stale_hardware_keys(doc: Document) -> list[str]
```

**Behaviour:**
- **Your hardware note holds:** `bastet: hardware`, `category`, the item's name (title), every `HARDWARE_YOURS` key (empty when unknown), and your body text.
- **Bastet's `<item> facts` note holds:** serial, model, make, size, firmware, slot, `installed_in` as observed, speeds, and everything else gather reads, with the summary cards in its body (see Task 4).
- **New hardware found by gather:** gather *creates* your note with the empty `HARDWARE_YOURS` fields, plus Bastet's note. Both appear in the one diff.
- **Existing hardware is matched** by its serial and keys from Bastet's note, falling back to an old hardware note's serial (as with `ssh_host_key`).
- **Gather never modifies your hardware note.** Its `installed_in` now lives in Bastet's note (where it was last seen). Your note's `location` is where you say it is, which matters for spares.
- **A hardware item recorded in a host but not seen** (the existing completeness check) gets `missing_since: <date>` in its Bastet note. That's shown as a warning on:
  - the item's summary;
  - the host's summary;
  - the dashboard's needs-attention list.

  It persists across refreshes until the item is seen again, or you set `status` to `failed`, `retired`, `sold` or `spare`.
- **Removed:** attribution and `--take`, everywhere.

**Tests:**
- New hardware creates both notes, with the empty fields.
- Re-gather leaves your note byte-identical.
- Your `status`/`price` are never touched.
- A stale gathered key on your note is ignored and reported.
- **Missing hardware (four DIMMs recorded, two seen):**
  - `missing_since` is set on the two;
  - the warning appears in all three places and survives a refresh;
  - it clears when they're seen again, and when the status is set to `failed`.
- Moved hardware updates Bastet's `installed_in`.

### Task 4: One Bastet note per host and per hardware item

**Files:**
- `src/bastet/core/factsnote.py`, `src/bastet/core/render.py`, `src/bastet/core/security_note.py`.
- `src/bastet/core/views.py`, `src/bastet/core/scaffold.py`.
- Tests across render, summary, security note, scaffold and refresh.

**Behaviour:**
- **`<host> facts.md` (and `<item> facts.md`) is the single Bastet note per object:**
  - frontmatter: the gathered facts, plus `warnings`, `drift` and `missing_since`;
  - body:
    1. the summary cards (today's summary note);
    2. warnings;
    3. the resolved-roles table (hosts);
    4. the security report (hosts; today's reports note).
- **Retired:** `_bastet/summary/` and `_bastet/reports/`. `refresh` deletes their old notes when the frontmatter says `generated: true`.
- **Embeds:**
  - host pages embed `![[<host> facts]]` once, plus the hardware and roles Bases;
  - `add host` writes that;
  - an existing page still embedding `![[<host> summary]]` gets a `doctor` problem with a fix (Task 6).
- **Warnings and drift are stored in the facts note's frontmatter** when gather finds them. Refresh re-renders from what's stored, so a later refresh can't drop them. They're cleared only by a later gather of that host.
- **Check and apply** write the security section by rewriting the facts note's body, not a separate note.

**Tests:**
- One note per host and per item, with all sections.
- Old summary and reports notes are deleted only when generated.
- Warnings survive a plain refresh.
- The `add host` page embeds.
- No `_bastet/summary/` or `_bastet/reports/` paths are left in `src/`.

### Task 5: One commit per command; visible refresh

**Files:** `src/bastet/cli/common.py` (`refresh_generated` returns its changes instead of committing; a `finish(ctx, changes, message)` commits everything once), every command that writes, and tests.

**Behaviour:**
- **A command collects** its own changes and the regenerated notes, then makes **one** commit: `<command summary> (+N generated)`, e.g. `gather: pve1, media01 (+8 generated)` or `apply: vps1 (+3 generated)`.
  - A `run -c` that only regenerates commits `check: <hosts> (+N generated)`.
  - A command with nothing to write makes no commit.
- **A refresh that can't run** prints one normal (stdout) line saying why:
  - a secret is unlocked;
  - a merge is in progress;
  - the pull failed;
  - an error, with its message.

  `doctor` lists the same reason until a refresh succeeds.
- **Push failure** is one consistent line everywhere: `committed locally; push failed (offline?); it'll be pushed next time`. It never changes the exit code, and the next command pushes everything pending.

**Tests:**
- `run -g` with a host and new hardware makes exactly one commit.
- `run -c` makes one.
- `add role` makes one.
- Nothing-to-write makes none.
- Each skip reason prints.
- The push-failure line and exit code.

### Task 6: `bastet doctor [--fix]`

**Files:**
- Create `src/bastet/cli/doctor.py`, `src/bastet/core/doctor.py`.
- `src/bastet/cli/app.py`.
- `src/bastet/cli/secret.py` (fold `audit` into bare `secret`).
- Tests: `tests/core/test_doctor.py`, `tests/cli/test_doctor_cli.py`, the secret CLI tests.

**Interfaces (produces):**
```python
@dataclass
class Problem: where: str; message: str; severity: str; fix: Change | None = None; fix_note: str | None = None
def diagnose(ctx) -> list[Problem]
```

**Behaviour:**
- **`bastet doctor`** (read-only) lists, grouped:
  - inventory problems (today's list);
  - stale gathered keys on host and hardware notes;
  - pages still embedding retired notes;
  - type-name problems;
  - why the last refresh was skipped;
  - push pending.

  Library-role checks join here in roles subplan 2.
- **`bastet doctor --fix`** applies every problem that has a `fix`, shown as **one diff**, asked once (`-y` skips the question), **one commit**. It then prints exactly what it did, per file:
  `hosts/vps1.md: removed os, kernel, cpu (now in vps1 facts)`.
  - **Stale keys are removed only when Bastet's note already holds a value for that key.** Otherwise there's no fix, just a hint to run `bastet run -g` first.
  - **Retired embeds** are replaced with `![[<host> facts]]`.
- **`bastet doctor <dir>`** lints a role folder. In this plan, only "the folder parses as today's role definition"; roles subplan 2 fills it in, replacing that plan's `role check`.
- **`bastet secret`** prints the inventory plus every health finding (today's `audit` output), and `secret audit` is removed.

**Tests:**
- `diagnose` finds each problem kind.
- `--fix` produces one diff and one commit, and the report lines.
- A stale key with no value in the facts note isn't removed.
- The retired-embed fix.
- `secret` shows audit findings, and `secret audit` is gone.

### Task 7: Templates folder; `add hardware` removed; `add host --local`

**Files:**
- Create `src/bastet/core/templates.py`, and the template content under `src/bastet/data/templates/`.
- `src/bastet/core/initialize.py` and `src/bastet/core/render.py` (refresh keeps the templates current).
- `src/bastet/cli/add.py` (remove `add hardware`; `add host --local` skips the IP and address questions).
- Tests: `tests/core/test_templates.py`, `tests/cli/test_add*.py`, `tests/cli/test_init.py`.

**Behaviour:**
- **`_templates/` in the inventory,** one note per kind:
  - `Host - <type>.md` for every type;
  - `Hardware - <category>.md` for every category (drive, memory, cpu, nic, gpu, hba, psu, usb, machine categories…);
  - `Role file.md`, `Group.md`, `Location.md`.
- **Each template** has the right frontmatter keys, with empty values or placeholders, and a short body explaining each field. Hardware templates include every `HARDWARE_YOURS` field.
- **The templates are Bastet's own (generated):** `refresh` rewrites them, and the folder says so in a `README` note.
- **`init` points Obsidian's built-in Templates plugin at the folder** (`.obsidian/templates.json` with `folder: "_templates"`, enabling the core plugin in `.obsidian/core-plugins.json`), the same way it installs the stylesheet, and only when the inventory has a `.obsidian` folder or `init` creates one.
- **The guide** says to use "Templates: Insert template" in a new note. It doesn't mention right-click (that's a community plugin).
- **`add hardware` is removed.**
- **`add host --local`** writes `connection: local`. It doesn't ask for an IP or an address, and writes neither (the address is implied).

**Tests:**
- Every type and category gets a template.
- Templates parse as their kind.
- Refresh rewrites a changed template.
- `init` writes the plugin settings.
- `add hardware` is gone.
- `add host --local` asks no address questions.

### Task 8: Small UX fixes, and tab completion

**Files:**
- `src/bastet/roles/contract.py` (lenient values).
- `src/bastet/core/inventory.py` and `src/bastet/core/render.py` (errors surfaced).
- `src/bastet/core/scaffold.py` (empty role file body).
- `src/bastet/cli/*.py` (next-step hints).
- `src/bastet/cli/app.py` (completion).
- Create `src/bastet/cli/complete.py`.
- Tests.

**Behaviour:**
- **Lenient values** (Obsidian stores a property as text once it was text anywhere):
  - a `bool` option accepts `"true"`/`"false"`/`"yes"`/`"no"` in any case;
  - `int` and `number` accept numeric text.

  Values are normalised before validation. Anything else still errors, as today.
- **"Did you mean":** an unknown option names up to three closest matches (`difflib`), e.g. "did you mean `permit_root_login`?", instead of listing every option. Unknown roles, hosts and selectors do the same.
- **Role-file errors surface everywhere:**
  - in the terminal for any command that loads roles;
  - on the dashboard's needs-attention list;
  - in the host's facts note.

  Not only the summary.
- **Next-step hints** (one line, `next:`):
  - after `init`: `bastet add host`;
  - after `add host`: `bastet run -g <host>`;
  - after a host's first gather: `bastet add role --to <host>`;
  - after `add role`: `bastet run -c`.

  Not printed with `-y`, or when stdout isn't a terminal.
- **Role files written by `add role` with no values** get a body line: "No values set; this role uses its defaults. Options: ![[<role> role#Options]]".
- **Tab completion:**
  - enable Typer's completion (`bastet --install-completion`);
  - complete host names, `@groups`, `@types` and `@lab` for `run` and `show`;
  - role names for `add role`;
  - host → role → option for `secret set`/`show`.

  All read from the inventory, with no network and no git operations.

**Tests:**
- Lenient bool and number values.
- Still-invalid values error.
- The did-you-mean text.
- An error appears in all three places.
- Hints appear only on a tty without `-y`.
- The empty role-file body.
- Completion functions return the expected candidates for a fixture inventory.

### Task 9: Docs

**Files:**
- `README.md`: install and quick start, plus the command table, as agreed (`init`, `run`, `show`, `add host|role`, `role`, `secret`, `doctor`, plus `refresh`/`help`); selectors; `doctor`; templates; who writes what; completion.
- The guide note.
- `docs/specs/2026-09-30-bastet-design.md` §5.3 (hardware fields and split), §7 (attribution removed; gather writes only Bastet's notes), §12 (commands).
- `docs/specs/2026-10-06-bastet-roles-design.md` §2 (the hardware row, the one-note rule), §13 (`role check` → `doctor <dir>`).
- `docs/plans/2026-10-07-bastet-roles-2-format-library.md`: rename `bastet role check` → `bastet doctor <dir>` throughout, and `role` keeps `list`/`update`.
- `docs/ROADMAP.md`: this plan in "Now"; mark it done after the merge.

**Behaviour:** docs only. `scripts/privacy-check` must be clean.

### Task 10: User documentation lives in the vault

**Files:**
- Create `src/bastet/data/docs/*.md`, the single source of user documentation, replacing `src/bastet/data/guide/guide.md`.
- `src/bastet/core/render.py` (refresh writes them to `_bastet/docs/`).
- `src/bastet/core/scaffold.py`, `src/bastet/core/templates.py`, `src/bastet/roles/pages.py` (contextual links).
- `src/bastet/core/initialize.py` (the `Homelab.md` link).
- `README.md` (shortened to install and quick start, linking to the docs).
- Tests.

**Behaviour:**
- **The docs are written once,** as Markdown notes in the package, and shipped into every inventory by `refresh` as `_bastet/docs/<Title>.md` (Bastet's own, `generated: true`). They always match the installed version. GitHub renders the same files from the repo. The notes:
  - `Bastet guide` (start here: who writes what, the daily loop);
  - `Commands` (every command and option, the selectors, `-y`);
  - `Hosts and facts` (host notes, the facts notes, drift, stale keys);
  - `Hardware` (your fields, missing hardware, templates);
  - `Roles` (role files, precedence, presets once they exist, the library once it exists);
  - `Secrets`;
  - `Troubleshooting` (`doctor`, skipped refreshes, push failures);
  - `Writing roles` (filled in by roles subplan 2).
- **Developer docs** (specs, plans, research) stay in the repo, and are never copied into a vault.
- **`Homelab.md`** gets one line under its title, `Docs: [[Bastet guide]]`, added by `init` (and offered by `doctor --fix` on existing inventories, since `Homelab.md` is your note).
- **The dashboard** links the guide, as today.
- **Contextual links**, where they help:
  - role files written by `add role`: `Docs: [[Roles]] · Options: [[<role> role#Options]]`;
  - templates: the matching doc (`[[Hardware]]`, `[[Hosts and facts]]`, `[[Roles]]`);
  - every Bastet facts note: `[[Hosts and facts]]`;
  - `doctor` output and errors: the relevant doc note's name, so it can be opened in Obsidian (as a clickable link once milestone 3b's output layer exists).
- **Old notes:** `refresh` deletes the old `_bastet/Bastet guide.md` (generated) when it writes the new docs.

**Tests:**
- Every doc ships to `_bastet/docs/` and is regenerated when the package version changes.
- Each contextual link is present in a new role file, a template and a facts note.
- The `Homelab.md` line from `init`, and the `doctor --fix` offer for an existing lab.
- No dangling `[[…]]` targets in the shipped docs (every link resolves to a doc, a generated note or a heading).

---

## After this plan

Roles subplan 2 (role format and library), updated for the `doctor` rename.

### Task 11 (added 2026-10-10): Type groups generated; an `other` type

**Files:**
- `src/bastet/core/render.py` (generated groups).
- `src/bastet/core/inventory.py` (reserved-name check).
- `src/bastet/cli/add.py` (`_role_targets`).
- Create `src/bastet/data/types/other.yml`.
- Tests: the touched test files only.

**Behaviour:**
- **Type groups as notes.** `refresh` generates a group note per host type present in the inventory, next to the OS groups: `_bastet/groups/<type>.md`, `generated: true`, `match: {type: <type>}`. The body says "Every <type> host. Generated by Bastet."
  - The reserved-type-name check exempts these generated notes.
  - A user group note with a type's name is still an error.
- **A name shared by an OS group and a type group** (e.g. `proxmox`): only the type group is generated, and its body mentions it covers that OS too.
- **`add role` offers every generated group as a target:** type groups ("every <type> host") and OS groups ("every <os> host"), before your own groups and the hosts.
- **The `other` host type** is for anything on the network Bastet doesn't manage, like game consoles, TVs or printers:
  - `physical: true`, `gather: false`, `managed: false`, `managed_by: nothing (shown on maps only)`;
  - fields: `ip`, `mac`, `address`, `location` (all `yours`), plus `links`.
  - Hosts of this type appear on the network and cabling maps and the dashboard. `run` skips them with "not managed" and never tries to connect.

**Tests (3–6):**
- A type group is generated for each type present.
- `add role` lists the type and OS groups.
- A user group named like a type still errors, while the generated one doesn't.
- An `other` host is on the maps and skipped by `run`.
