# Roles Redesign 2: Role Format and Library — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this repo, the `bastet-run-plan` skill supplies the Bastet-specific parts.

**Goal:**
- **Roles are Markdown notes.** The contract is the frontmatter, the documentation is the body, with a generated options section.
- **Roles come from sources:** bundled, `~/.config/bastet/roles`, and a configured folder.
- **The roles a lab uses are copied into the inventory** (`_roles/library/<role>/`), and only those copies run.
- **New commands:** `bastet role` (list), `bastet doctor <dir>` (lint, with `--fix` to regenerate docs) and `bastet role update [name]` (preview, then copy).
- **The nine shipped roles are converted to the new format.** Their Python builders keep running unchanged until subplan 6.

**Architecture:**
- **`bastet.roles.contract`** parses `<name> role.md` instead of `role.yml`. `RoleDef` gains the identity and compatibility fields. Option parsing is unchanged apart from three new keys (`key`, `section`, `common`).
- **A new `bastet.roles.library`** finds sources, copies a role into `_roles/library/<role>/` (recording `source` and `source_hash`), detects edited copies, and loads the library.
- **`load_roles(root)`** returns the inventory's library. `bundled_roles()` returns the shipped roles, for docs and as a source.
- **A new `bastet.roles.docs`** renders the options section between markers.
- **A new `bastet.cli.role`** holds the `role` sub-commands.
- **Behaviour comes later:** fields whose behaviour belongs to later subplans (`needs`, `provides`, `contributes`, `requires`, `presets`, `vars`, `packages`, `templates`, `units`, `hooks`, `data`) are parsed, shape-checked and stored, but do nothing yet.

**Tech Stack:** as before (Python ≥3.12, uv, Typer, pytest, PyYAML, the existing frontmatter reader and writer).

**Spec:** `docs/specs/2026-10-06-bastet-roles-design.md` §3 (format), §3.1 (contract rules), §3.2 (body and generated section), §4 (sources, the copy, updates), §13 (`doctor`), §14 (pages).

**Roadmap:** `docs/plans/2026-10-06-bastet-roles-roadmap.md`, subplan 2.

## Global Constraints

- **Unit tests:**
  - never touch the real inventory, `~/.config/bastet`, `~/.local/share/bastet`, `~/.ssh`, the real `~/.cache` or `$XDG_RUNTIME_DIR`;
  - no network;
  - `tmp_path` only;
  - placeholder data only (see "Example data" in `docs/ROADMAP.md`).
- **Note names must be unique in a vault.** A role's definition file is `<role> role.md`, both in sources and in the library (`_roles/library/ssh/ssh role.md`). Links are `[[ssh role#permit_root_login]]`. The generated `_bastet/roles/<role> role.md` pages go away, since they would collide.
- **The library copy is never rewritten by Bastet, except when copying or updating.** The generated options section is produced in the *source* (by `bastet doctor <dir> --fix`), so copies stay byte-identical apart from the two recorded fields.
- **Updates are never silent.** Automatic commands may *add* a missing role to the library (a first copy, reported, and committed in the command's own single commit, never a commit of its own). They never replace an existing copy; only `bastet role update` does, after a preview.
- **The existing Python builders stay as they are** (`builtin.BUILDERS`, keyed by role name). A role with no builder fails its host with the existing error `role <name> has no implementation yet` (`builtin.batches_for`), so an assigned role never appears to apply while configuring nothing. Other hosts continue. Task 1 pins this with a test.
- **Commit trailer:**
  ```
  Co-Authored-By: <model> <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01DBkyXRsdxwovkRErg9n9wt
  ```
  Stage by name, never `git commit -a`. Run `scripts/privacy-check` before each commit; the pre-commit hook enforces it.
- **Output goes through the console:** every message printed by the new `role` commands (and by `ensure_library`) uses `from bastet.ui import out` (`out.echo`, `out.secho`, `out.table`, `out.diff`), never `typer.echo`. `tests/test_no_raw_echo.py` fails the build if `typer.echo`, `typer.secho` or `click.echo` appears anywhere in `src/`.
- **Library copies and the run record:** `ensure_library` adds its copies to `ctx.written`, so a command's run note (if it makes one) and the library copies share the command's one commit. Nothing here emits events; the recorder is a no-op where no run is recording.
- **Each task:** failing tests first and seen failing, then implement, then the full `uv run pytest -q` green.

## Review Focus

1. **An existing inventory with role files but no library** (the user's real lab). The first command that loads roles (never `show`) must copy exactly the roles its role files reference, from the right source, and report that copy and commit it in the command's one commit, with nothing else changed. Check and apply must then behave exactly as before. A command that fails before it commits leaves the copy uncommitted; the next command must pick it up into its commit, not offer it as "your" uncommitted edit.
2. **Hashing and edits.**
   - `source_hash` must be computed so that the copy's own recorded fields (`source`, `source_hash`) don't change it.
   - Line endings and a trailing newline the user's editor adds must not register as an edit.
   - A real edit to the frontmatter, body, `templates/` or `role.py` must register.
3. **The same name in several sources.** Copy precedence is configured folder > `~/.config/bastet/roles` > bundled. After the first copy, `source:` sticks: an update comes from that source even if a higher-priority folder later gains the same name.
4. **Links in existing role files.** They embed `![[<role> role#Options]]` and `#Examples`. The converted roles keep `## Options` and `## Examples` headings, so these embeds keep working.
5. **`role update` for a major version that renames or removes an option a role file sets.** It's named per file and key before anything is copied. Declining copies nothing.

---

### Task 1: The Markdown contract, and the nine roles converted

**Files:**
- Modify `src/bastet/roles/contract.py`.
- Create `src/bastet/data/roles/<name>/<name> role.md` for base, files, harden, packages, pacman, proxmox, ssh, systemd and users. Delete each `role.yml` (`git rm`).
- Modify `scripts/gen_ssh_role.py` so it writes the ssh role's options into the frontmatter of `ssh role.md`.
- Tests: `tests/roles/test_role_contract.py` (and the existing role tests, adapted only where they named `role.yml`).

**Interfaces (produces):**
```python
API_VERSIONS = (1,)
DEFINITION_KEYS = {"bastet", "name", "version", "api", "description", "cssclasses", "os", "os_min", "types", "not_types",
                   "requires", "tags", "needs", "provides", "contributes", "collects", "data", "vars", "options", "presets",
                   "examples", "packages", "templates", "units", "hooks", "source", "source_hash"}
OPTION_KEYS += {"key", "section", "common"}

@dataclass
class RoleDef:
    name: str
    description: str
    options: dict[str, Option]
    path: Path                  # the "<name> role.md" file
    examples: list[dict]
    version: str = "0.0.0"
    api: int = 1
    os: tuple[str, ...] = ()
    types: tuple[str, ...] = ()
    not_types: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    source: str | None = None   # set on library copies
    raw: dict = field(default_factory=dict)  # every definition key, for later subplans

def parse_role(path: Path) -> RoleDef                       # one "<name> role.md"
def load_role_dir(directory: Path) -> dict[str, RoleDef]   # every <name>/<name> role.md under directory
def bundled_roles() -> dict[str, RoleDef]                    # load_role_dir(the package's data/roles)
def per_os(value: object, os_id: str | None, family: tuple[str, ...]) -> object
# a {arch: …, debian: …, default: …} map → exact id, then family in order, then default; any other value is
# returned unchanged; no match and no default raises BastetError("no value for <os_id>")
```

**Behaviour:**
- **What `parse_role` requires:**
  - frontmatter with `bastet: role-definition`;
  - `name` equal to the folder name (and to the file stem minus ` role`);
  - `version` in semver form `X.Y.Z`;
  - `api` in `API_VERSIONS`;
  - `description` as text.

  Unknown top-level keys are an error naming them.
- **Flat lists:** `os`, `types`, `not_types` and `tags` must be flat lists of strings, so Bases can show them.
- **Shape checks only** for the later fields: `needs`, `provides`, `contributes`, `collects`, `data`, `vars`, `presets`, `packages`, `templates`, `units` and `hooks` must be maps or lists, as the spec shows; they're stored in `raw` and do nothing yet.
- **Options:** parsed exactly as today, with `key`, `section` and `common` allowed (`common` a bool, the other two text). Reserved names stay reserved.
- **A parse error** names the file and the key, as today.
- **The nine roles are converted mechanically:**
  - **Frontmatter:**
    - `bastet: role-definition`, `name`, `version: 1.0.0`, `api: 1`, `cssclasses: [bastet-role]`;
    - the existing `description`, `options` and `examples` unchanged;
    - `os`/`types` where today's builder or docs imply them: `pacman: [arch]`, `proxmox: [proxmox]`, the rest empty (meaning "any").
  - **Body:**
    - `# <name> role`;
    - the description as a paragraph;
    - `## Options` with the generated-section markers. The content is filled in by Task 2's `--fix`; until then a placeholder line, so the embeds resolve.
    - `## Examples` rendering each example as a heading plus a `yaml` code block;
    - `## Changes` with `- 1.0.0: converted from role.yml`.
- **`load_roles()` with no argument returns `bundled_roles()` in this task,** so nothing else changes yet.

**Tests:**
- A minimal valid role parses.
- Each required-field error.
- An unknown top-level key.
- A nested `os`.
- `key`/`section`/`common` accepted.
- `per_os`: exact, family, default, missing, plain value.
- A role in the library with no builder fails its host with `has no implementation yet` while another host in the same run continues (pins the behaviour the constraint describes).
- All nine bundled roles parse, with the same options as before. Compare against a snapshot of each role's option names and types, taken from the current `role.yml` files before deleting them.
- `docs/roles.md`, regenerated by `scripts/gen_roles_doc.py`, is unchanged apart from anything the new fields add.

### Task 2: The generated options section, and `bastet doctor`

**Files:**
- Create `src/bastet/roles/docs.py`, `src/bastet/cli/role.py` (a `role` Typer sub-app, registered in `app.py`).
- Run `bastet doctor <dir> --fix` over each of the nine bundled role dirs, and commit the regenerated sections.
- Tests: `tests/roles/test_role_docs.py`, `tests/cli/test_role_cli.py`.

**Interfaces (produces):**
```python
OPTIONS_START = "<!-- bastet:options -->"
OPTIONS_END = "<!-- /bastet:options -->"
def options_section(role: RoleDef) -> str          # what goes between the markers
def with_options_section(text: str, role: RoleDef) -> str | None   # the note with the section regenerated; None without markers
def lint(role_dir: Path) -> list[Finding]           # Finding(severity: "error"|"warning", message: str)
```

**Behaviour:**
- **The options section** has one `### <option>` heading per option, in contract order, grouped under `#### <section>` when sections exist, with `common` options first.
  - Each option shows: type (as today's role pages show it), default, choices, upstream `key`, and its description.
  - Nested object fields are listed under their option.
- **`bastet doctor <dir>`** prints the lint findings and exits 1 if any are errors. `--fix` rewrites the role's `.md` with the regenerated section and changes nothing else in the file.
- **What lint checks now:**
  - the contract parses (an error);
  - with markers: the section is up to date (an error, "run `bastet doctor <dir> --fix`");
  - without markers: every option has a `### <option>` heading somewhere in the body (a warning per missing option);
  - `vars` maps use the per-OS form consistently: every `vars` value that's a map with `default` or OS-id keys covers every OS in `os`, or has a `default` (an error naming the var and the OS);
  - unused `vars`: a name never referenced as `{{ name }}` anywhere in the frontmatter text (a warning);
  - `version` is semver and `api` supported (errors; already enforced by the parser, reported here nicely);
  - **no implementation yet:** the role's name has no builder in `builtin.BUILDERS` (a warning: "no builder yet; an assigned host will fail until subplan 3");
  - **declared but not executed yet:** each of `needs`, `provides`, `contributes`, `collects`, `data`, `packages`, `templates`, `units`, `hooks` and `presets` that is non-empty (a warning per field: "`templates` is declared but not executed yet (subplan 3/4)"). An empty field says nothing, so the nine bundled roles are quiet;
  - **later checks,** listed as "not checked yet (subplan 3/4)": templates render, hooks have a mode, units declare `access`, service roles declare `data`, and options no resource reads.
- **`bastet role`** with no sub-command prints the help (as the main app does).

**Tests:**
- The section renders headings, sections and common-first.
- `with_options_section` replaces only between the markers, and returns None without them.
- `doctor <dir>`:
  - clean;
  - an out-of-date section;
  - a missing heading without markers;
  - a per-OS gap;
  - an unused var.
- `--fix` makes an out-of-date role clean, and leaves the rest of the file byte-identical.
- All nine bundled roles lint clean after `--fix`.
- A role with no builder warns; a populated `templates:` warns once; empty fields stay quiet.

### Task 3: Sources and the inventory library

**Files:**
- Create `src/bastet/roles/library.py`.
- Modify `src/bastet/core/config.py` (`roles: {path: <dir or null>}`), `src/bastet/roles/contract.py` (`load_roles(root)`).
- Modify every call site of `load_roles()` (`grep -rn "load_roles(" src/`): pass the inventory root from the context or inventory at hand. `roles/system.py`'s ssh guard reads the ssh contract the same way.
- Modify `src/bastet/cli/add.py` (`add role` copies a role that isn't in the library yet, as part of the same diff and commit).
- Tests: `tests/roles/test_library.py`, plus CLI tests.

**Interfaces (produces):**
```python
LIBRARY_DIR = "_roles/library"
@dataclass
class Source: name: str; directory: Path          # name: "config" | "custom" | "bundled"
def role_sources(config: Config) -> list[Source]    # configured folder (as "custom"), ~/.config/bastet/roles ("config"), bundled
def find_role(name: str, sources: list[Source]) -> tuple[Source, Path] | None      # first source holding <name>/<name> role.md
def content_hash(role_dir: Path) -> str
# sha256 over every file in the folder, sorted by path. The .md's `source`/`source_hash` lines are left out,
# line endings are normalised to \n, and trailing whitespace at the end of each file is ignored.
def copy_role(root: Path, name: str, source: Source, src_dir: Path) -> list[Change]   # the whole folder; frontmatter gains source, source_hash
def library_roles(root: Path) -> dict[str, RoleDef]
def is_edited(root: Path, name: str) -> bool        # content_hash != recorded source_hash
def referenced_roles(inv: Inventory) -> set[str]     # every `role:` in role files
def ensure_library(ctx) -> list[str]                 # copy referenced roles missing from the library; returns names copied
```

**Behaviour:**
- **`load_roles(root)`** returns `library_roles(root)`. `bundled_roles()` stays for docs and as a source.
- **`ensure_library` runs at the start of `refresh`, `check`, `apply`, `gather`, `add role` and the `role` commands,** whenever the inventory is a git repo and not busy. It never runs in `show`, which stays read-only and reports a missing role as a problem. For every role a role file references that's missing from the library:
  1. find it in the sources;
  2. copy it;
  3. write the copies at once (roles must load from them) and add their paths to `ctx.written`, so `finish()` commits them in the command's single commit. There is no separate `library:` commit;
  4. print one line per role: `library: added ssh 1.0.0 (bundled)`.

  A leftover copy from a command that failed before `finish()` is already on disk and uncommitted. `ensure_library` recognises library paths that are on disk but uncommitted and adds them to `ctx.written` too, so they are committed by the next command and never treated as the user's own edits.

  A referenced role found in no source is an inventory error for each role file naming it ("role 'x' isn't in this lab's library or any role source").
- **`ensure_library` never replaces an existing copy.**
- **`add role`:**
  - **Choices:** its list of roles offers the library, plus every source role not yet in it, marked "(new to this lab)".
  - **A role not in the library yet:** its copy joins the role-file diff and commit.
- **An edited copy** (`is_edited`) is a warning in `print_problems`: `_roles/library/ssh: edited since it was copied from bundled 1.0.0 (updates will need a manual merge)`.
- **Library copies are inventory notes** of kind `role-definition`. The inventory must accept them: no "unknown kind" warning, and no duplicate-name clash with role files, since their file names differ (`ssh role.md` vs `ssh.md`).

**Tests:**
- Source precedence (custom > config > bundled).
- The copy writes the whole folder, plus the two recorded fields.
- `content_hash` ignores the recorded fields, CRLF and an added trailing newline, and detects real edits in the frontmatter, body, a template, and `role.py`.
- **`ensure_library` on a fixture inventory** with role files for `packages` and `ssh` and no library: exactly those two are copied; a `check` makes exactly one commit that contains the copies; the output lines; a second run copies nothing and makes no commit.
- **A leftover uncommitted copy** (the first command failed before it committed) is committed by the next command, and no "uncommitted edits" prompt appears.
- **Source gone:** `check` and `apply` still work after the custom source directory is deleted, and the "newer version" line skips a missing source silently.
- A referenced role with no source gives the inventory error.
- `add role` of a new role puts the copy in the same commit.
- **Check and apply on the fixture behave as before:** the existing check/apply tests pass with `ensure_library` running in their fixtures.
- An edited-copy warning.

### Task 4: `bastet role` and `bastet role update`

**Files:** `src/bastet/cli/role.py`, `src/bastet/roles/library.py`, tests in `tests/cli/test_role_cli.py`.

**Interfaces (produces):**
```python
def contract_diff(old: RoleDef, new: RoleDef) -> list[str]
# "+ option x (int)", "- option y", "~ option z: default 1 → 2", "~ option z: type int → string", "~ description",
# "~ os: [] → [arch]", "~ version 1.0.0 → 1.1.0"; options in order, then other fields
def options_in_use(inv: Inventory, role: str) -> dict[Path, list[str]]   # role file → option keys it sets
def changed_files(old_dir: Path, new_dir: Path) -> list[str]
# "+ path", "~ path", "- path" for added/modified/deleted files (compared by normalised content, as content_hash
# does); `role.py` is suffixed "  (executable code)"
```

**Behaviour:**
- **`bastet role`** (no sub-command) prints help. `bastet role list` prints a table: role, version in the lab, source (a custom folder's path is shown; "source unavailable" when it no longer exists, never an error), newer version available (from that copy's `source:`), edited, and implementation (`yes`, or `none yet` for a role with no builder). Print it with `out.table`.
- **`bastet role update [name…]`.** With no names, every role that has a newer version in its source. For each:
  1. **The contract diff, and the changed files:** one line per file in the role folder that is added, modified or deleted (`~ role.py  (executable code)`, `+ templates/network.xml.j2`). No file contents.
  2. **Options in use that the new version removes, or whose type changes,** listed per role file and key, in red.
  3. **A check with the new version:** `check` runs for the hosts the role reaches, with this role swapped for the new version in a temporary copy of the library. Show its output.
  4. **"Update <role> to <version>?"** With `-y`, the answer is yes unless step 2 found something, in which case it refuses and names the files.
  5. **On yes:** replace the copy (`copy_role`), and commit `library: update <role> <old> → <new> from <source>`.
- **An edited copy** stops `update` for that role with "edited since it was copied; merge by hand, then run `bastet role update --accept-edited <role>`." The `--accept-edited` flag means: overwrite with the new version, after printing the old copy's diff against the old source version, if that's still available, or else a note saying it isn't.
- **`check` notes newer versions:** one line at the end, `roles: ssh 1.1.0 available (you have 1.0.0); run bastet role update`, read from the sources without network.

**Tests:**
- `contract_diff` on each kind of change.
- `changed_files`: added, modified, deleted, an unchanged file not listed, `role.py` flagged, line-ending-only changes ignored.
- `options_in_use`.
- `list` output, including a role with no builder (`none yet`) and a source folder that no longer exists.
- `update`:
  - a minor version, yes;
  - a minor version, no (nothing changes);
  - a major version renaming a set option, refused under `-y` with the file named;
  - an edited copy stopped, then `--accept-edited`;
  - the source no longer exists: a clear message, the library copy byte-identical.
- The check line for available updates.
- A temp-library check that never writes the real library.

### Task 5: Pages and index from the library

**Files:**
- `src/bastet/roles/pages.py`, `src/bastet/core/render.py`.
- `src/bastet/core/views.py` (a Roles Base).
- `scripts/gen_roles_doc.py` and `docs/roles.md` (from `bundled_roles()`).
- Tests: `tests/roles/test_role_pages.py`, `tests/cli/test_refresh.py`.

**Behaviour:**
- **`refresh` stops generating `_bastet/roles/<role> role.md`.** It deletes existing ones only if their frontmatter says `generated: true` (Bastet's own), in the same commit as the rest of the refresh.
- **`_bastet/Roles.md` becomes:**
  1. a Base over notes with `bastet: role-definition` under `_roles/library`: name (linked), description, os, tags, version, source;
  2. a generated table, "Used by", with role → hosts (as today's index);
  3. a line per role with a newer source version, or an edited copy.
- **A Base file `_bastet/roles-library.base`,** written by `ensure_views` like the other bases.
- **Role files' embeds** (`![[<role> role#Options]]`, `#Examples`) resolve to the library copies. A test asserts both headings exist in every converted role.
- **The resolved-options table on host summaries** links option names to `[[<role> role#<option>]]`.

**Tests:**
- Refresh writes no `_bastet/roles/` pages.
- It deletes generated ones and leaves a non-generated file there alone.
- `Roles.md` content.
- The base file.
- The summary links.
- `docs/roles.md` regenerated and in sync (the existing sync test).

### Task 6: Docs

**Files:**
- `src/bastet/data/docs/using_roles.md` and `writing_roles.md` (the user docs shipped into every vault): where roles come from; the library and that it is what runs; `bastet role`, `bastet doctor <dir>`, `bastet role update`; "edit a copy only if you accept merging by hand"; the Markdown role format for authors.
- `src/bastet/data/docs/commands.md`: the command table gains `bastet role`, `bastet doctor <dir> [--fix]` and `bastet role update [name…] [-y] [--accept-edited]`.
- `src/bastet/data/docs/bastet_guide.md`: one paragraph on the library.
- `README.md`: no change beyond a one-line mention, if any (it is only install and quick start now).
- `docs/ROADMAP.md`, `docs/plans/2026-10-06-bastet-roles-roadmap.md`: leave subplan 2 ◐; the controller marks it ☑ after the merge.

**Behaviour:** docs only. Plain text, example data only, every `[[link]]` must resolve to a shipped doc (the docs tests check it).

---

## After this plan

Subplan 3 (the execution model: one merged desired state, building-block phases, hooks, contributions, needs/provides, compatibility) is written against the code as it stands after this plan merges. It also adds the `doctor <dir>` items marked "not checked yet".
