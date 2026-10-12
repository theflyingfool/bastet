---
name: bastet-new-role
description: Use when adding or converting a Bastet role (a Markdown role note under src/bastet/data/roles/<name>/ that hands entries to the building blocks) — the checklist for the frontmatter, neutral defaults, secrets, accounts, tests, generated docs and the roadmap row. Use before writing the time, base, caddy, forgejo, vaultwarden, harden or ssh roles.
---

# Adding a Bastet role

Roles are data (about 99% straight Markdown) over the Python building blocks. Read first:
`docs/specs/2026-10-10-bastet-roles-architecture-design.md` and `src/bastet/data/docs/writing_roles.md` (the user
docs for every key below), and use `src/bastet/data/roles/pacman/pacman role.md` and `.../apt/apt role.md` as models.
Write a short plan in `docs/plans/<date>-bastet-<role>-role.md` first and let the owner review it (see
`bastet-run-plan` to execute it).

## Where it lives and what it is called

- `src/bastet/data/roles/<name>/<name> role.md`. The folder name is the role name, and the frontmatter `name:` must
  match it. The body is the documentation (a `## Changes` list at the end).
- Frontmatter keys: `bastet: role-definition`, `name`, `version` (semver, `1.0.0` for a new role), `api: 0`,
  `description`, optional `os` (a list such as `[arch]`; the role is offered only where it fits, and `bastet add role`
  uses it for compatibility), `provides` (capabilities like `package-manager`), `accounts`, `starter`, `options`,
  `examples`, and the entry lists `packages`, `systemd`, `users`, `files`, `commands`. Reserved keys do nothing yet.
- Only one of a `<name> role.md` note and a `role.yml` may exist in a folder. The old Python roles (`users`, `files`,
  `packages`, `systemd`, plus ssh/base/harden until converted) stay `role.yml` plus a builder in `roles/builtin.py`.

## The rules that matter

1. **Unset means leave alone, and a default applied to every host must change nothing.** A bool that defaults to
   `true` or a value that defaults to something forces it on every host the role reaches, including ones an OS
   default or a lab note applies it to. Prefer no default. Write a test that builds the role with no options set and
   asserts it emits nothing (see `tests/roles/test_systemd_default_is_neutral.py`).
2. **Every option is exposed under the upstream name** (`key:`, `section:`, `as: flag|value|list|lines|text|entries`),
   with `type`, `choices`, `min`/`max`, `single_line` where they apply. A value with a line break is refused.
3. **Entries** call the blocks, never each other: `packages:` (a name, or a name that resolves to a list), `systemd:`
   (`kind: unit|time|hostname|locale|dropin`), `users:` (`user|group|key|sudoer`; the `bastet` account is refused),
   `files:` (`edit: ini`, `render: apt`, `content`, `template` from the role's own folder, `directory`, `link`, `line`,
   `block`; `restart:`/`reload:` unit lists become triggers). Every entry takes `when:` (a Jinja expression) and
   `before:`/`after:` (a block slot, never both). Values may use `{{ option }}`, `host.*` and `lab.*`; an unset option
   used inside text is an error (write the optional part with `{% if option %}`), and a lone `{{ x }}` that is
   unset drops the field. A new `edit:` type, systemd kind or block feature is added only when this role needs it,
   with its own tests, and recorded in the roadmap.
4. **Secrets.** Mark a value `secret: true`. A top-level option that is also `required: true` is written into a new
   role note as `secret:<name>` automatically; a nested one needs an explicit `starter:` (for example
   `starter: {users: {root: {password: "secret:root_password"}}}`). Secrets hold plain text when unlocked; hashing,
   if any, happens on the controller. Only entries that use a secret option are marked secret.
5. **Accounts.** A role that brings system accounts lists them in `accounts:` so the unaccounted-users report treats
   them as expected on hosts where the role is applied (pacman: `alpm`). Accounts every host of an OS has go in
   `src/bastet/data/oses/<os>.yml` instead (with default `roles:` if the OS should come with a role).
6. **Compatibility.** Set `os:` when the role only makes sense on some systems; roles with no `os:` are offered
   everywhere.

## Checklist

- [ ] Plan reviewed by the owner (new keys or blocks are decisions, not details).
- [ ] Role note written; `parse_role` accepts it (`uv run pytest tests/roles -q`).
- [ ] Tests: the entries build what you expect, the no-options case emits nothing, errors name the file and key,
      secrets are marked only where used, `when:` skips cleanly. Test file names are unique across `tests/`.
- [ ] `uv run python scripts/gen_roles_doc.py` and commit `docs/roles.md` (a repo test checks it is current).
- [ ] `ruff check src tests` passes; `scripts/privacy-check` is clean (copy the ignored `.privacy-patterns` into a
      fresh worktree first, then delete the copy).
- [ ] `docs/ROADMAP.md`: tick the role, update the VPS-apps step, add what the work revealed to "Planned additions".
- [ ] The owner runs the full suite (give him the command); the controller never merges before his "passed".
