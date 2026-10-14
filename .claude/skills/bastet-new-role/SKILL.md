---
name: bastet-new-role
description: Use when adding or converting a Bastet role (a Markdown role note under src/bastet/data/roles/<name>/ that hands entries to the building blocks) — the checklist for the frontmatter, defaults, secrets, accounts, tests, generated docs and the roadmap row. Use before writing the time, base, caddy, forgejo, vaultwarden, harden or ssh roles.
---

# Adding a Bastet role

Roles are data (about 99% straight Markdown) over the Python building blocks. Read first:
`docs/specs/2026-10-10-bastet-roles-architecture-design.md` and `src/bastet/data/docs/writing_roles.md` (the user
docs for every key below, with a "contract at a glance" list), and use `src/bastet/data/roles/time/time role.md` (written
on the finished contract, see `docs/plans/2026-10-11-bastet-time-role.md`) as the model, with `.../pacman/pacman role.md`
and `.../apt/apt role.md` for package managers.
Write a short plan in `docs/plans/<date>-bastet-<role>-role.md` first and let the owner review it (see
`bastet-run-plan` to execute it).

## Where it lives and what it is called

- `src/bastet/data/roles/<name>/<name> role.md`. The folder name is the role name, and the frontmatter `name:` must
  match it. The body is the documentation (a `## Changes` list at the end).
- Frontmatter keys: `bastet: role-definition`, `name`, `version` (semver, `1.0.0` for a new role), `api: 0`,
  `description`, optional `os` (a list such as `[arch]`; the role is offered only where it fits, and `bastet add role`
  uses it for compatibility), `provides` (capabilities like `package-manager`), `accounts`, `starter`, `options`,
  `examples`, `checks`, `sections`, and the entry lists `packages`, `systemd`, `users`, `files`, `commands`. Reserved
  keys do nothing yet.
- Only one of a `<name> role.md` note and a `role.yml` may exist in a folder. Only the building-block roles (`users`,
  `files`, `packages`, `systemd`) stay Python: `role.yml` plus a builder in `roles/builtin.py`. The old Python `ssh`,
  `harden` and `base` are moved to `refs/` and rebuilt as Markdown (`docs/decisions.md` D-026; `base` first).

## The rules that matter

1. **Unset means leave alone, unless the role documents an opinionated default.** Bastet is opinionated but respects
   users' defaults (`docs/decisions.md` D-015). A default that changes a host (a bool that defaults to `true`, a tool
   list, a timer) is allowed only when the role's body lists exactly what it does with no options and a note can turn
   it off; it applies to every host the role reaches, including ones an OS default or a lab note applies it to, so
   keep such defaults few. Every other option has no default. Write a test that builds the role with no options and
   asserts either that it emits nothing (see `tests/roles/test_systemd_default_is_neutral.py`) or exactly the
   documented defaults.
2. **Every option is exposed under the upstream name** (`key:`, `section:`, `as: flag|value|list|lines|text|entries`),
   with `type`, `choices`, `min`/`max`, `single_line` where they apply. A value with a line break is refused. Use
   `choices_from: <file>` (one value per line, in the role's folder) for a long list such as time zones, and
   `requires:`/`conflicts:` on an option instead of cross-checking in Python. Test `none` on purpose
   (`when: x is not none`): `false`, `0`, `""` and `[]` are values, and plain `when: x` is false for them.
3. **Entries** call the blocks, never each other: `packages:` (a name, or a name that resolves to a list), `systemd:`
   (`kind: unit|time|hostname|locale|dropin`), `users:` (`user|group|key|sudoer`; the `bastet` account is refused),
   `files:` (`edit: ini`, `render: apt`, `content`, `template` from the role's own folder, `directory`, `link`, `line`,
   `block`; `restart:`/`reload:` unit lists become triggers). Every entry takes `when:` (a Jinja expression) and
   `before:`/`after:` (a block slot, never both). Values may use `{{ option }}`, `host.*` and `lab.*`; an unset option
   used inside text is an error (write the optional part with `{% if option %}`), and a lone `{{ x }}` that is
   unset drops the field. A new `edit:` type, systemd kind or block feature is added only when this role needs it,
   with its own tests, and recorded in the roadmap. A role never needs Python unless a new block is needed.
   Use `sections:` (with a `when:`) for the parts that differ per OS, and `each: <list or map option>` for one entry
   per item (`item`, `key`). File reload classes: `daemon_reload: true` for unit definitions and Quadlet files,
   `restart:`/`reload:` for application config (only a running unit is touched), `on_change:` commands for the rest;
   enable/disable and start/stop belong to the `Unit` entry.
4. **Secrets.** Mark a value `secret: true`. A top-level option that is also `required: true` is written into a new
   role note as `secret:<name>` automatically; a nested one needs an explicit `starter:` (for example
   `starter: {users: {root: {password: "secret:root_password"}}}`). Secrets hold plain text when unlocked; hashing,
   if any, happens on the controller. Only entries that use a secret option are marked secret.
5. **Accounts.** A role that brings system accounts lists them in `accounts:` so the unaccounted-users report treats
   them as expected on hosts where the role is applied (pacman: `alpm`). Accounts every host of an OS has go in
   `src/bastet/data/oses/<os>.yml` instead (with default `roles:` if the OS should come with a role).
6. **Nothing is skipped silently.** When the role leaves something out or cannot do what a value asks, say so with
   `checks:` (`info` for work delegated elsewhere, `warning` for probably wrong, `error` for cannot be done). Checks run
   at planning time over options and facts (`host.*`, `lab`, `applied.origin.<option>`); protection against the host's
   current state is `validate:`, `unless:` and trigger checks. For a lab-wide option that only fits some systems,
   a note can opt out with `overrides:` (a `when:` over host facts) or `key: null`; the role's checks should name that
   way out. A limit that belongs to the role itself (a system it does not support yet) goes in the role file's own
   `overrides:` instead, which clears the options on those hosts and leaves one info note.
7. **Compatibility.** Set `os:` when the role only makes sense on some systems; roles with no `os:` are offered
   everywhere.

8. **Overriding another role's option (planned).** `supersedes: <role>.<option>` on an option names the option of
   another role it overrides (`docs/plans/2026-10-14-bastet-base-role.md`, Tasks 4 and 5); it does not exist until
   that plan has landed. Rank first, a tie goes to the role with `supersedes`.
9. **Default role notes (planned).** The lab gets `packages` and `base` notes, every group and host a `base` note
   (`docs/decisions.md` D-034); a new role that should reach every host is added to the lists in `roles/notes.py`
   once that plan has landed.

## Lessons from the `caddy` role (2026-10-14)

- **Secrets are marked by top-level option name.** A file is hidden in diffs when its text uses an option that holds a
  `secret:` reference, so a nested secret hides every file that mentions the parent option. Keep secrets in their own
  top-level option (`dns_secrets`, not `dns.secrets`) and keep the files that only need plain settings off it. An unset
  `secret: true` option reads its own note, so do not put `secret: true` on an optional map; the references inside it
  mark it.
- **`commands:` entries cannot hold `{{ }}`** (only with `each:`). Put values that vary in a templated script a command
  calls (`build current`, `build rebuild`), or use a pair of entries with opposite `when:`. A `Command` runs only when
  its `unless` fails: a read-only standing check is `unless` and `run` set to the same command.
- **Triggers (`on_change:` with `name:` and `run:`) run once per host after all fixes, as a root `sh -e` script, and are
  de-duplicated by value:** share one YAML anchor so every entry carries identical text. Do not use `reload:`/`restart:`
  when the unit must not be touched before a validation passes.
- **Order across blocks is fixed** (packages, users, files, systemd, commands): a command that must run before a unit
  starts needs `before: systemd`, and it has to run `systemctl daemon-reload` itself because the trigger does it later.
- **A package that creates an account** needs that account in the role's `accounts:` (`git` for `base`, `caddy` for
  `caddy`); D-040 plans to derive these.
- **Role templates and checks:** an unset option written into text is an error (`{% if x is not none %}`); a check on
  an optional field of an object option uses `.get('field')`; `{% set _ = … %}` inside a loop is refused, so use an
  expression statement (`{{ list.append(x) or "" }}`); a shell script rendered from a template must avoid `{#` and `{{`.
- **Docs:** shipped docs and role pages may not contain `[[x]]` that is not a doc (`tests/core/test_docs.py`); describe a
  link form in words. `docs/roles.md` is regenerated by `scripts/gen_roles_doc.py`.
- **Versions:** a changed role needs `scripts/version-bump <version> --refresh` (same version) or a new bump, and its
  own `version:` and `## Changes` line; `--check` names what is stale.
- **Verify host behaviour before writing it down.** Systemd, pacman and Caddy behave in ways a diff cannot show (a
  `DynamicUser` cache or state directory cannot exec files; the packaged `ExecStartPre` validates with the stock
  binary). Use the `bastet-host-check` skill.

## Checklist

- [ ] Plan reviewed by the owner (new keys or blocks are decisions, not details).
- [ ] Role note written; `parse_role` accepts it (`uv run pytest tests/roles -q`).
- [ ] Checked against the rules: no Python, `checks:` for every skipped or delegated case, `requires`/`conflicts` for
      option rules, `overrides:`/null documented for lab-wide options, `choices_from` for long lists.
- [ ] Tests (follow `docs/testing.md`): the entries build what you expect, the no-options case emits nothing or exactly the documented defaults, errors name the file and key,
      secrets are marked only where used, `when:` skips cleanly. Test file names are unique across `tests/`.
- [ ] `uv run python scripts/gen_roles_doc.py` and commit `docs/roles.md` (a repo test checks it is current).
- [ ] `ruff check src tests` passes; `scripts/privacy-check` is clean (copy the ignored `.privacy-patterns` into a
      fresh worktree first, then delete the copy).
- [ ] `docs/ROADMAP.md`: tick the role, update the VPS-apps step, add what the work revealed to "Planned additions".
- [ ] The owner runs the full suite (give him the command); the controller never merges before his "passed".
