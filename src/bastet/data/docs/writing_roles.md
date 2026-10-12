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
runs only when the check fails), and optionally `when` (a condition, see below) and `before` or `after`. The `run`
and `unless` texts are literal: `{{ }}` in them is not filled in.
The apt role's `modernize_sources` option uses one to run `apt modernize-sources -y`.

### Options that need or exclude each other

An option can say which other options it depends on:
- `requires: [a, b]`: if this option is set, `a` and `b` must be set too;
- `requires: {a: true}` or `{a: [x, y]}`: `a` must also have that value (or be one of those values);
- `conflicts: [a]`: this option and `a` must not both be set.

"Set" means the note gives the option a value (not null): `false`, `0`, `""` and `[]` count as set. A default never
counts, because the check looks at what the notes wrote, merged across the lab, group and host notes of one host (a
lab note and a host note can complete each other), before defaults are added. Inside an `object` option the names are
the object's sibling fields; at the top they are other top-level options. A rule that names an option or field that
does not exist is refused when the role is read; a rule that is broken is refused when the values are checked, for
example `time: ntp_servers needs ntp to be true`.

```yaml
options:
  ntp:
    type: bool
  ntp_servers:
    type: list
    items: {type: string}
    requires: {ntp: true}
  ntp_pool:
    type: string
    conflicts: [ntp_servers]
```

### Opting a host or group out of an inherited option

A host or group note can undo something a broader note set by giving the option an explicit null (`key:` or
`key: null`). The null is kept as an ordinary value while the notes are merged, so the usual rules decide: the
highest-ranked note wins (a host's `false`, or any real value, beats a group's null; a group's null beats the lab's
`true`), and two notes of the same rank that disagree (one null, one `true`) clash like any other disagreement. Only
after every rank is merged is a winning null turned into "unset": the option then takes its default, or nothing. Nothing
is removed during the merge, so the result never depends on the order of the notes. The same holds for a field inside a
`map` or `object` option (a map entry set to null drops that entry).
A null with nothing inherited does nothing. A cleared option is not listed among the origins, and `requires` and
`conflicts` see it as unset.

A bare `key:` with nothing after it is a null, so never write one expecting "no value yet": it clears whatever the
lab or a group set. Shipped starters and `bastet add role` never write one. An option name that does not exist is
refused even with a null.

### Different values on different hosts (overrides)

Any role note (lab, group, type or host) may carry `overrides:`, a list of entries `{when: <expression>, <option>:
<value>, ...}`. For a host where `when` is true, the entry's values replace that same note's own values for those
options, at that note's rank. A higher-ranked note still wins as usual. Entries apply in listing order, so a later
matching entry wins over an earlier one. A value may be `null`, with the meaning described above.

```yaml
# the lab's note for the time role
ntp: true
overrides:
  - when: not host.arch_like
    ntp: null        # blank (unset) on hosts that are not Arch-like
```

`when` sees only the `host` facts (`name`, `type`, `os_id`, `arch_like`, `debian_like`, `container`, `physical`,
`cpu`) and `lab`, never the options (the options are what is being decided), so a `when` that names an option is
refused. Everything is checked when the note is read: the `when` syntax, the fact names, that every other key is an
option of the role, and each value through that option's normal checks (a `secret:` reference is allowed). An error
names the note file and the key `overrides`. In the origins, a value that came from an entry reads `lab (override)`.

### Long lists of allowed values (choices_from)

For a long list of allowed values (time zones, say), an option may say `choices_from: <file>` instead of `choices:`.
The file sits in the role's own folder (no absolute path, no `..`), holds one value per line, and ignores blank lines,
lines starting with `#` and surrounding spaces. It is checked when the role is read: it must be readable text with at
least one value and no value twice, and `choices_from` together with `choices` is refused. It applies to string
options, and to list or map options whose items are strings (put it on the option or on `items`). A value that is not
in the file is refused with the option and file named and at most the closest match, never the whole list. The
generated reference shows more than 20 values in a collapsed "N allowed values" block.

```yaml
options:
  timezone: {type: string, choices_from: time zones.txt}
```

### Accounts, defaults and starters

`accounts:` (top level, a list of account names) lists the accounts a role brings; the unaccounted-users report treats
them as expected on hosts the role is applied to. OS defaults are shipped per OS (`src/bastet/data/oses/`); for
example Arch comes with the `systemd` role and the always-present Arch accounts. An OS default ranks below the lab: a
lab, group or host note (and a host type's default) can still change that role's options, and the resolved table names
the origin as "OS default (arch)".

An option with `merge_default: true` (a map option) keeps its default entries when a note sets some of its own: the
`users` role's default `root` and `bastet` entries stay when a note adds `alice`, and `root: {password: ...}` merges
with the default `root` entry instead of replacing it.

`starter:` (a map of option values) is written into the frontmatter of a new role note by `bastet add role`; the
`users` role starts with `root`'s password as a `secret:` reference and `bastet` as a system account. To drop one of
those entries, delete the whole entry (or write `root: {}`), not just its password line. Setting root's password keeps
an already locked root locked; add `locked: false` to unlock it. A top-level option that is `secret: true` and
`required: true` is written into the new note as a `secret:` reference automatically, which spares you from adding the
reference by hand and from the "missing secret" lookup (an unset secret option already reads the same secret name, so it
is not needed to make it work); for a nested one, add it under `starter:`.

### Calling the building blocks

A role file can also list `packages:`, `users:` and `systemd:` entries, which call the blocks of the same names; a role
that needs several lists several. Blocks never call each other, and the engine runs the entries in block order
(packages, users, files, systemd), whatever order the role lists them in. Every entry takes `when:`, a condition
written as a Jinja2 expression over the options and the host and lab facts (`host`, `lab`), and values may contain
`{{ }}` over the same names.

```yaml
options:
  domain: {type: string, required: true}
packages: [example-app]
users:
  - {kind: user, name: web, system: true}
files:
  - path: /etc/example-app/app.conf
    content: "{{ domain }} {\n}\n"
    reload: [example-app.service]
systemd:
  - {kind: unit, name: example-app.service, enabled: true, state: up}
```

A lone `{{ option }}` keeps its type, and an option left unset drops that field (or, for a list item or a required
field, is an error). An unset option inside other text, as in `zone={{ tz }}`, is an error too, so write an optional
part as `{% if tz %}zone={{ tz }}{% endif %}`. Every field of a `files:` entry is filled in, paths and modes
included, and a `files:` entry can't write Bastet's own `/etc/sudoers.d/bastet` or `authorized_keys`.

`files:` entries also come as `template` (a file in the role's folder, checked when the role is read, and rendered
in the same sandbox as the expressions), `directory`, `link`, `line` and `block`. A password given to a `users:`
entry from a secret is hashed on the controller in the host's own scheme.

`bastet doctor <folder>` lints a Markdown role.
