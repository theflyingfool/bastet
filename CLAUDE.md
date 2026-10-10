# Bastet

- Status and what's next: `docs/ROADMAP.md`. Design: `docs/specs/`. Plans: `docs/plans/`.
- Running a plan: the `bastet-run-plan` skill.
- Tracked files use the example data in `docs/ROADMAP.md` ("Example data"), never real lab details;
  `scripts/privacy-check` enforces it.
- `refs/` (old Ansible roles, old plans, survey scripts) and `.superpowers/` are git-ignored and local only.
- Roles: the current design is `docs/specs/2026-10-10-bastet-roles-architecture-design.md` (building blocks stay
  Python, roles are Markdown, a host runs by phase across all roles). The six old roles subplans are superseded.
- Conventions: every message goes through `bastet.ui.out` (`tests/test_no_raw_echo.py` forbids `typer.echo` in `src/`);
  test file names must be unique across `tests/` (no `__init__.py`); the version is written only in `pyproject.toml`;
  nothing in Bastet deletes notes or records yet (removal is deferred).
