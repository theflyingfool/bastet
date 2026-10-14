# Bastet

- Status and what's next: `docs/ROADMAP.md`. Design: `docs/specs/`. Plans: `docs/plans/`.
- Decisions: `docs/decisions.md`. Add an entry whenever the owner decides something that is not obvious from the code
  (a reversed one is marked superseded, never deleted). Ending a session: the `bastet-end-session` skill.
- Writing or changing tests: read `docs/testing.md` first (one layer per behaviour, parametrize, no sleeps, a small
  budget per feature).
- Running a plan: the `bastet-run-plan` skill. Adding or converting a role: the `bastet-new-role` skill. Checking
  behaviour on a real host before writing it down: the `bastet-host-check` skill.
- Git: no lasting worktrees. Work on a plain branch in the real checkout or on `main`. A background session that
  cannot edit the checkout may use a temporary worktree (pushed branch, removed after). A background session cannot
  merge or push to `main`: it pushes its branch and opens a draft PR, and the owner merges. The owner runs the full test
  suite himself and says when it passed.
- Tracked files use the example data in `docs/ROADMAP.md` ("Example data"), never real lab details;
  `scripts/privacy-check` enforces it.
- `refs/` (old Ansible roles, old plans, survey scripts), `.superpowers/` and `.serena/` are git-ignored and local only.
  A new worktree does not have the ignored files: right after creating one, copy `.serena/` from the main checkout
  (`cp -r <main checkout>/.serena <worktree>/`) before using Serena's tools there, and never commit it. Copy
  `.privacy-patterns` the same way only if `scripts/privacy-check` is to run there, and delete the copy afterwards.
- Roles: the current design is `docs/specs/2026-10-10-bastet-roles-architecture-design.md` (building blocks stay
  Python, roles are Markdown, a host runs by phase across all roles). The six old roles subplans are superseded.
- Building blocks are the actions that roles use. Technically they are roles too, the special ones; they are the only
  place with real code (Python), and every other role is data that the blocks act on. Built: `packages` (installs,
  removals, updates, reboot need), `users`, `files` (whole files, lines, blocks, section settings, templates), `systemd`,
  `commands`, `reports`. Planned: JSON state (APIs), power control. The `users`, `files`, `packages` and `systemd` roles
  are the special ones that stay Python. Anything that belongs to one package manager, repositories included, is that
  manager's own role (`apt`, `pacman`, and each future manager), not part of `packages`.
- Roles: Bastet is opinionated, but tries to respect users choosing their own defaults most of the time. A role leaves
  things alone unless an option is set, except where its own documentation lists exactly what it does with no
  options (for example `base`'s tool list and microcode, `pacman`'s reflector timer); a note can always turn such a
  default off. Anything else applied to every host by default (an OS default role, a default entry) must change
  nothing with no options. A role lists the accounts it brings in
  `accounts:`; accounts every host of an OS has go in `src/bastet/data/oses/<os>.yml`, which can also make an OS come
  with a role. `bastet add role` writes a role's `starter:` and required secret references into the new note.
- Collectors: a role with `collects: {proxy: <list option>}` (the `caddy` role) receives the `proxy` exposures other
  hosts' roles declare, routed by its `serves` option or an explicit `via`; design in
  `docs/specs/2026-10-14-bastet-caddy-and-collectors-design.md`. A role that creates accounts through a package lists
  them in `accounts:` (D-040 plans to derive them).
- Lint: `ruff check src tests` (config in `pyproject.toml`) must pass; run it before committing.
- Conventions: every message goes through `bastet.ui.out` (`tests/test_no_raw_echo.py` forbids `typer.echo` in `src/`);
  test file names must be unique across `tests/` (no `__init__.py`); the version is written only in `pyproject.toml` and bumped with `scripts/version-bump` (it refreshes the time zone list and records role hashes; `--check` verifies both, and a changed role needs a bump);
  nothing in Bastet deletes notes or records yet (removal is deferred).
