# Roles

A role is a menu of options for one thing: `systemd` (time, hostname, locale, services),
`packages`, `users`, `files`, `ssh`, `harden` and more. `bastet add role` writes a role file for
you; its page in `_bastet/roles/` lists every option, with its default and description.

## Role files

You pick values in role files under `_roles/`: one for the whole lab (`_roles/lab/<role>.md`), a
group (`_roles/groups/<group>/<role>.md`) or a host (`_roles/hosts/<host>/<role>.md`).

## Precedence

More specific wins: the host type's own defaults, then the lab, then groups (inner groups over
outer ones), then the host. Lists add up across levels rather than replacing.

The packages role also reports pending updates (installing them per `updates:`, or with
`bastet run --updates` for manual hosts), whether a reboot is needed, and packages installed
outside Bastet.

## Presets and the library

Not yet shipped. This section will cover ready-made presets and a wider role library once they
land.

See [[Writing roles]] to write your own.
