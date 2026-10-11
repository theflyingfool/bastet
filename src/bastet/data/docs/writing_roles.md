# Writing roles

Not yet written in full. This doc will cover the role file format, options, examples and
engine resources, once the roles format and library work lands.

See [[Using roles]] for how roles are used today.

## Markdown roles (draft)

A Markdown role is one note, "<name> role.md", in a folder named after the role. The frontmatter is the contract:
`bastet: role-definition`, `name` (the folder name), `version` (1.2.3), `api`, `description`, optional `os`,
`provides`, `options` and `examples`, and a `files` list. `api: 0` means a draft: it may still change without
notice. pacman and apt are the Markdown-only roles; the others still use `role.yml` and Python builders.

Building blocks are the actions roles use (packages, users, files, systemd, commands, reports). Technically they are
roles too, the special ones, and the only place with real code. Every other role is data the blocks act on. The
`users`, `files`, `packages` and `systemd` roles stay Python; the generic builder knows generic formats only
(ini, deb822, ini_section), never apt or pacman names.

Each option can say where it is written: `key` (the setting name), `section`, `as` (`flag`, `value`, `list` or
`entries`), plus `min`, `max` and `single_line`. A value with a line break is refused.

Each `files` entry names a `path` and exactly one mode:
- `edit: ini` changes settings in an existing ini file (pacman.conf). Per section, Bastet writes one managed block
  (`### Bastet Managed ###` ... `### End Bastet Managed ###`) right after the section header and comments out the
  original lines of every key the role manages, inside that section only, with `#bastet: `. A setting switched off
  (false, or an empty list) comments out the original and writes nothing. A setting left unset leaves the file alone.
  If you later unset a setting, its line leaves the block but the commented original is not restored (removal is
  deferred). The file's owner, group and mode are left as they are;
- `render: apt` writes a whole file from the options (apt's `90-bastet`).

Other entry knobs: `validate` (a command run on the new file before it is swapped in; `%s` is the file), `backup: true`
(only with `edit`: the original is copied once to `<path>.bastet-orig`, never overwritten, and never taken of a file
Bastet wrote), `mode`, `owner` and `group` (only with `render`; with `edit` they are an error), and `before` / `after`
(name a block; the entry runs just before or after that block's slot; not both). A role that configures a package
manager sets `provides: package-manager`, so its entries run before packages.

An option with `as: entries` is a list of objects, each written as one entry of a file format. It needs `format`
(`deb822`: one file per entry; `ini_section`: one marked block per entry in a shared file) and `path` (it may contain
`{name}`); `ini_section` also takes `marker` and `before` / `after` place the entries. A package manager's repositories
are this: the apt role writes `.sources` files, the pacman role writes `bastet repo <name>` blocks in pacman.conf, both
before packages are installed. Repositories belong to the package manager's own role, and every future manager owns
its own; the `packages` role has none.

A role file can also list `commands:`. Each entry has a `name`, a `run` command and an `unless` check (the command
runs only when the check fails), and optionally `when` (the name of a true/false option) and `before` or `after`.
The apt role's `modernize_sources` option uses one to run `apt modernize-sources -y`.

`bastet doctor <folder>` lints a Markdown role.
