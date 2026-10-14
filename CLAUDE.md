# Bastet

- Status and what's next: `docs/ROADMAP.md`. Design: `docs/specs/`. Plans: `docs/plans/`.
- Running a plan: the `bastet-run-plan` skill. Adding or converting a role: the `bastet-new-role` skill.
- Git: no lasting worktrees. Work on a plain branch in the real checkout or on `main`. A background session that
  cannot edit the checkout may use a temporary worktree (pushed branch, removed after). The owner runs the full test
  suite himself and says when it passed.
- Tracked files use the example data in `docs/ROADMAP.md` ("Example data"), never real lab details;
  `scripts/privacy-check` enforces it.
- `refs/` (old Ansible roles, old plans, survey scripts) and `.superpowers/` are git-ignored and local only.
- Roles: the current design is `docs/specs/2026-10-10-bastet-roles-architecture-design.md` (building blocks stay
  Python, roles are Markdown, a host runs by phase across all roles). The six old roles subplans are superseded.
- Building blocks are the actions that roles use. Technically they are roles too, the special ones; they are the only
  place with real code (Python), and every other role is data that the blocks act on. Built: `packages` (installs,
  removals, updates, reboot need), `users`, `files` (whole files, lines, blocks, section settings, templates), `systemd`,
  `commands`, `reports`. Planned: JSON state (APIs), power control. The `users`, `files`, `packages` and `systemd` roles
  are the special ones that stay Python. Anything that belongs to one package manager, repositories included, is that
  manager's own role (`apt`, `pacman`, and each future manager), not part of `packages`.
- Roles: a role leaves things alone unless an option is set, and anything applied to every host by default (an OS
  default role, a default entry) must change nothing with no options. A role lists the accounts it brings in
  `accounts:`; accounts every host of an OS has go in `src/bastet/data/oses/<os>.yml`, which can also make an OS come
  with a role. `bastet add role` writes a role's `starter:` and required secret references into the new note.
- Lint: `ruff check src tests` (config in `pyproject.toml`) must pass; run it before committing.
- Conventions: every message goes through `bastet.ui.out` (`tests/test_no_raw_echo.py` forbids `typer.echo` in `src/`);
  test file names must be unique across `tests/` (no `__init__.py`); the version is written only in `pyproject.toml` and bumped with `scripts/version-bump` (it refreshes the time zone list; `--check` verifies);
  nothing in Bastet deletes notes or records yet (removal is deferred).
