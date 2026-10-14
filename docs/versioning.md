# Versioning

The version is written only in `pyproject.toml`. Bump it at each milestone; there are no git tags.

## How to bump

1. Run `scripts/version-bump X.Y.Z` (use an up-to-date machine, see below). It writes the version into
   `pyproject.toml`, refreshes `src/bastet/data/roles/time/time zones.txt` from `timedatectl list-timezones`,
   and regenerates `docs/roles.md`.
2. Review the printed zone changes (number of zones, `added:` and `removed:`).
3. Commit `pyproject.toml`, `time zones.txt` and `docs/roles.md` together.

`scripts/version-bump X.Y.Z --refresh` refreshes the zone list without changing the version.
`scripts/version-bump --check` writes nothing and fails if the zone list is missing, its first line is not
`# refreshed for bastet <version>`, or the zones are unsorted, duplicated, empty or unloadable.

## The zone list

The list is a snapshot of the machine that ran the bump. Run the bump on a machine with current time zone data.
The check verifies only the stamp and the shape of the file, not that the list is complete.
