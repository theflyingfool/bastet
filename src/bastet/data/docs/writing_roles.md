# Writing roles

Not yet written in full. This doc will cover the role file format, options, examples and
engine resources, once the roles format and library work lands.

See [[Using roles]] for how roles are used today.

## Markdown roles (draft)

A Markdown role is one note, "<name> role.md", in a folder named after the role. The frontmatter is the contract:
`bastet: role-definition`, `name` (the folder name), `version` (1.2.3), `api`, `description`, optional `os`,
`provides`, `options` and `examples`, and a `files` list. `api: 0` means a draft: it may still change without
notice. pacman and apt are the Markdown-only roles; the others still use `role.yml` and Python builders.

Each option can say where it is written: `key` (the setting name), `section`, `as` (`flag`, `value` or `list`),
plus `min`, `max` and `single_line`.

Each `files` entry names a `path` and exactly one mode:
- `edit: ini` changes individual settings in an existing ini file (pacman.conf);
- `render: apt` writes a whole file from the options (apt's `90-bastet`).

Other entry knobs: `mode`, `owner`, `group`, `validate` (a command run on the new file before it is swapped in),
and `before` / `after` (name a block; the entry runs just before or after that block's slot). A role that
configures a package manager sets `provides: package-manager`, so its entries run before packages.
