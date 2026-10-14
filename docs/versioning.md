# Versioning

The version is written only in `pyproject.toml`; there are no git tags.

## The rules

- **Bastet is `0.X.Y`.** Any change that ships code or role changes gets a bump: Y for fixes, role changes and small
  features, X for a milestone. A new number is what `uv tool install --reinstall .` shows after an upgrade.
- **Roles are versioned on their own**, in the role file's `version:` and its `## Changes` list. A new role starts at
  `0.1.0`; semver after that (Y for fixes, X for new or changed options). A role becomes `1.0.0` when it has been
  checked on a real host. Role versions do not have to match Bastet's.
- **A changed role means a Bastet bump.** `scripts/version-bump` records a hash of every role's directory in
  `src/bastet/data/role-hashes.txt`; `--check` fails and names the roles that changed since the last bump. When a
  role changes, also raise its own `version:` and add a line to its `## Changes`.

## How to bump

1. Run `scripts/version-bump X.Y.Z` (use an up-to-date machine, see below). It writes the version into
   `pyproject.toml`, refreshes `src/bastet/data/roles/time/time zones.txt` from `timedatectl list-timezones`,
   and regenerates `docs/roles.md`.
2. Review the printed zone changes (number of zones, `added:` and `removed:`).
3. Commit `pyproject.toml`, `time zones.txt`, `role-hashes.txt` and `docs/roles.md` together.

`scripts/version-bump X.Y.Z --refresh` refreshes the zone list without changing the version.
`scripts/version-bump --check` writes nothing and fails if the zone list is missing, its first line is not
`# refreshed for bastet <version>`, or the zones are unsorted, duplicated, empty or unloadable, or if a role changed since the last bump.

## The zone list

The list is a snapshot of the machine that ran the bump. Run the bump on a machine with current time zone data.
The check verifies only the stamp and the shape of the file, not that the list is complete.
