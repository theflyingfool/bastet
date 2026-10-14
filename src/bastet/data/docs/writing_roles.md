# Writing roles

Not yet written in full. This doc will cover the role file format, options, examples and
engine resources, once the roles format and library work lands.

See [[Using roles]] for how roles are used today.

## The contract at a glance

One line per key; each links to the section that explains it.

Option keys (under `options:`):
- `type`, `default`, `required`, `choices`, `min`, `max`, `single_line`, `merge_default`: [Markdown roles](#markdown-roles-draft)
  and [Accounts, defaults and starters](#accounts-defaults-and-starters).
- `key`, `section`, `as` (plus `format`, `path`, `marker` for `as: entries`): [Markdown roles](#markdown-roles-draft).
- `choices_from`: a long list of allowed values in a file, [Long lists of allowed values](#long-lists-of-allowed-values-choices_from).
- `requires`, `conflicts`: [Options that need or exclude each other](#options-that-need-or-exclude-each-other).
- `supersedes`: an option that overrides another role's option, [One role's option overriding another's](#one-roles-option-overriding-anothers-supersedes).

Role keys (top level of the role note):
- `packages`, `users`, `files`, `systemd`, `commands`: [Calling the building blocks](#calling-the-building-blocks).
- `checks`: info, warning or error from a role, [Stopping or warning instead of skipping silently](#stopping-or-warning-instead-of-skipping-silently).
- `sections`: [Grouping entries](#grouping-entries-sections).
- `overrides`: options the role itself sets or clears on some hosts, [Overrides defined by the role itself](#overrides-defined-by-the-role-itself).
- `accounts`, `starter`: [Accounts, defaults and starters](#accounts-defaults-and-starters).
- `examples`: example values shown in the generated reference ([Markdown roles](#markdown-roles-draft)).

Entry keys (on a `packages`, `users`, `files`, `systemd` or `commands` entry):
- `when`: [Calling the building blocks](#calling-the-building-blocks) and [Unset, false and empty](#unset-false-and-empty).
- `before`, `after`: [What a role runs, in order](#what-a-role-runs-in-order).
- `each`: [One entry per list item](#one-entry-per-list-item-each).
- `restart`, `reload`, `daemon_reload`, `on_change` (on `files` entries): [Reacting to changes](#reacting-to-changes).

Names an expression (`when:`, `{{ }}`, a check) can use:
- `options`: every option of the role by its name; an option left unset is `none`.
- `host.<fact>`: `name`, `type`, `os_id`, `arch_like`, `debian_like`, `container`, `physical`, `cpu`.
- `lab`: the lab note's data.
- `applied.origin.<option>`: where the value came from, [Stopping or warning instead of skipping silently](#stopping-or-warning-instead-of-skipping-silently).
- `item` and `key`: only inside an entry that has `each:`.

Keys in a role note (the values a lab, group, type or host writes):
- `overrides`: different values on some hosts, [Different values on different hosts](#different-values-on-different-hosts-overrides).
- `null` as a value: opts out of an inherited value, [Opting a host or group out](#opting-a-host-or-group-out-of-an-inherited-option).

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

### Unset, false and empty

An option the notes leave out is unset (`none` in an expression). `false`, `0`, `""` and `[]` are values, not unset:
the role is told "the person said no", not "the person said nothing". A role leaves things alone for an unset option
and acts on a value, including `false` (`ntp: false` means stop syncing; no `ntp` means don't touch it).

So `when: ntp` is not the same as `when: ntp is not none`. A bare `when: ntp` is plain truthiness: it is false for
unset and for `false`, `0`, `""` and `[]` alike, so use it for "do this only when it is on". When `false` must also do
something, test for unset on purpose:
- `ntp is none`: nothing was said;
- `ntp is not none`: something was said (`true` or `false`);
- `ntp is true`, `ntp is false`: exactly that value (unset matches neither).

For example, a unit entry with `when: ntp is not none` and `enabled: "{{ ntp }}"` enables the unit for `true` and
disables it for `false`, and does nothing when `ntp` is unset. `requires` and `conflicts` use the same idea: they count
`false`, `0`, `""` and `[]` as set.

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
`map` or `object` option (a map entry set to null drops that entry; for a `merge_default` map it falls back to the default entry, if any).
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

### Overrides defined by the role itself

The role file may carry its own `overrides:`, for a limit the role knows about (a system it does not support yet)
instead of every lab having to write the same note-level override. It is a different thing from the `overrides:` of a
lab, group, type or host note above, and it applies to this role's own options only. Each entry is `{when, note?,
<option>: <value or null>, ...}`:

```yaml
# in the role file's frontmatter
overrides:
  - when: not host.arch_like
    note: sync is only built for Arch, so the sync settings are ignored on this host
    ntp: null
    ntp_servers: null
```

It is evaluated for each host once all notes are merged and their nulls cleared, after every note-level `overrides:`
entry, before the `requires`/`conflicts` check and before defaults are added. So it wins over every note, and a value
it clears is never seen by the relation rules. Entries apply in listing order, and a later entry sees the options as
the earlier ones left them. A matching entry sets the options it lists; `null` removes the option, as if no note had set
it. In the origins, a value it set reads `role override`, and a cleared one is not listed.

`when` may use the role's option names (their merged values before defaults, `none` when unset), `host` and `lab`, but
not `applied`. If a matching entry changed at least one option that had a value, the host gets one info note: the
entry's `note` (which may use `{{ }}` over the same names) or `role <name> ignores <options> on this host`. If nothing
had a value, no note. The note is shown like any note from a `checks:` entry, once per host.

Everything is checked when the role is read: unknown keys (the options are the only other keys), option names that do
not exist, each value through the option's normal check, the `when` syntax and names, and the `note` text. An error
names the role, the role file, the key `overrides` and the entry number (`overrides[0]`, counting from 0).

### One role's option overriding another's (supersedes)

A package manager role often wants to set something a building block already has an option for (`pacman` and the
`packages` reboot policy, say). `supersedes: <role>.<option>` on one of the role's own options says "my value for this
is also that role's value". The named role and option must exist (checked when the roles load, with the role file and
the key `supersedes` named). The option may leave out its `type`, `description`, `items`, `fields` and `choices`: they
are copied from the target. A `type` it does set must match the target's. It applies to the role's own options only,
not to fields or list items.

When both roles are on a host and each has a value, the note with the higher rank wins; on a tie the role with
`supersedes` wins. This happens before the target role's own `overrides:`, so an override can still clear the value.
The target role does not need a note of its own: it is applied with just that value. An unset superseding option
changes nothing.

```yaml
options:
  reboot: {supersedes: packages.reboot}
```

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

### Grouping entries (sections)

`sections:` is a list of maps `{name, when, packages, users, files, systemd, commands}`; the five block keys take the
same entry lists as the role's top-level keys of the same name. A section's optional `when` (an expression over the
options and the host, lab and applied facts, checked when the role is read) is ANDed with each entry's own `when`; a
section without `when` only organises. `name` is optional text that appears in error messages, for example
`sections[1] (arch): files[0]: ...`.

Sections and the top-level lists coexist. The engine still orders entries by block (packages, users, files, systemd,
commands); within a block the top-level entries come first, then each section in order. `before:` and `after:` on an
entry work as usual. A section inside a section, an unknown key, a value that is not a list and a section with no entries
are refused when the role is read, naming the role file and `sections`.

```yaml
sections:
  - name: arch
    when: host.arch_like
    packages: [ntp]                                  # install
    files:
      - path: /etc/ntp.conf                          # configure
        content: "server {{ ntp_server }}\n"
        reload: [ntpd.service]                       # reload when the file changed
    systemd:
      - {kind: unit, name: ntpd.service, enabled: true, state: up}   # enable and start
```

Install, configure, enable and reload run in block order whatever the order they are written in. An error raised while a
role is built (an option that resolves to nothing, say) names the entry by its position among all entries of that block.

### One entry per list item (each)

`each: <option>` on a `packages`, `users`, `systemd`, `files` (content, template, directory, link, line or block) or
`commands` entry, also inside `sections:`, builds the entry once per item of a `list` option, or once per pair of a `map`
option. In the entry, `item` is the list element (or the map value) and `key` the map key (maps only). `item` and `key`
are names only inside an entry that has `each`, in its `when:`, its `{{ }}` values and its template; anywhere else they
are refused when the role is read like any name that is no option. `each` must name an option of type `list` or `map`
(refused when the role is read otherwise), and is refused on a `files` entry with `edit:` or `render:`, which are built
from the options as a whole. An unset or empty option builds nothing. In a looped `commands` entry `name`, `run` and
`unless` can use `{{ }}` too (in other commands they stay literal text).

The entry's `when:` (including a section's) is judged per item, so it may use `item` and `key`. A secret option used as
`each` makes everything built from it secret. Two items that build the same thing (the same file path, unit, account,
package or command name) are refused with the role, the entry (like `files[2]`) and both item numbers.

```yaml
options:
  sites:
    type: list
    items:
      type: object
      fields:
        domain: {type: string}
        upstream: {type: string}
files:
  - path: /etc/caddy/sites/{{ item.domain }}.caddy
    each: sites
    content: |
      {{ item.domain }} {
          reverse_proxy {{ item.upstream }}
      }
    reload: [caddy.service]
```

There is deliberately no index variable: reordering the list changes nothing that is built. Item numbers appear only in
error messages. An item that is removed or renamed leaves the file it once built behind, because Bastet does not delete
files yet; remove it by hand.

### Accounts, defaults and starters

`accounts:` (top level, a list of account names) lists the accounts a role brings; the unaccounted-users report treats
them as expected on hosts the role is applied to. OS defaults are shipped per OS (`src/bastet/data/oses/`); for
example Arch comes with the `systemd` role and the always-present Arch accounts. The `systemd` role is there only for its
accounts (the systemd-* system users every Arch install has); with no options it changes nothing. An OS default ranks below the lab: a
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

A role file can also list `packages:`, `users:`, `files:`, `systemd:` and `commands:` entries, which call the blocks of
the same names; a role that needs several lists several. Blocks never call each other, and the engine runs the entries
in block order (see below), whatever order the role lists them in. Every entry takes `when:`, a condition
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

### What a role runs, in order

On one host, all the roles applied to it run together, by phase and not role by role. Within a phase the order is
fixed by block, whatever order a role lists its entries in:

1. `packages`: install, remove, update;
2. `users`: accounts, groups, keys, sudoers;
3. `files`: write and edit files;
4. `systemd`: units (enable, start), drop-ins, hostname, time zone, locale;
5. `commands`.

Then the triggers run once, at the end: daemon-reload first, then restarts and reloads (in the order the entries
changed), then `on_change` commands (in that order too).

That is the usual workflow written out: install the package, configure it (a file), enable the unit, and reload or
restart it when its configuration changed. `before:` and `after:` on an entry name a block (`before: files`) and move
that entry to just before or just after that block's slot; they adjust the order inside this list, they do not add steps
(a role that configures a package manager sets `provides: package-manager` and runs before packages). Entries from
`sections:` and `each:` follow the same rule: block first, then listing order.

### Reacting to changes

When a file changes, the host often has to be told. There are four classes, and each has its own key:

- **daemon-reload** is for unit definitions and drop-ins under `/etc/systemd/system`, and Quadlet files. Write
  `daemon_reload: true` on the `files:` entry. A `systemd:` entry of `kind: dropin` does this for you.
- **restart and reload** are for an application's own config (a file under `/etc/example-app/` or a `conf.d`
  folder). Write `restart: [unit]` or `reload: [unit]`. Only a running unit is touched: a stopped or failed unit is left alone,
  and the report says "skipped: not running". To bring a unit up, add a `systemd:` unit
  entry with `state: up`.
- **enable, disable, start and stop** belong to the `systemd:` unit entry (`enabled:`, `state:`), not to a file.
- **`on_change`** runs a command of your own for anything else, such as `sysctl --system` or
  `update-ca-certificates`: `on_change: [{name: apply sysctl, run: sysctl --system}]`. Both `name` and `run` are
  required text and may use `{{ }}`.

`daemon_reload`, `restart`, `reload` and `on_change` work on `content`, `template`, `line`, `block`, `edit` and `render`
entries, not on `directory` or `link`. Triggers run once per host, after all the changes, in this order:
daemon-reload first, then restarts and reloads, then `on_change` commands; within each group, in the order the
entries changed. An identical trigger named by several entries
runs once. A trigger only fires for an entry that changed and did not fail.

Known limitation: a unit that was started in this same run is restarted once more when its config also changed.

### Stopping or warning instead of skipping silently

This is planning-time checking. The role file is checked when it is read (syntax, names, the facts), and a check's
`when` is judged when a host is planned, from the options and the facts. Run-time protection is something else: it asks
the host as it is right now. It is `validate:` on a file (a command run on the new file before it replaces the old
one), `unless:` on a command, and the only-if-running test on restart and reload triggers.

Nothing is skipped without a message, unless the setting itself says to skip. When a role leaves something out, or
cannot do what a value asks for on this host, say so with `checks:`, a list of `{name?, when, level, message}`:

- `info`: context the person may want (shown, does not matter to the outcome).
- `warning`: something to look at (shown in yellow; the run goes on).
- `error`: stops that host before anything is planned or applied, like any other error in the role.

`when` is an expression and `message` may use `{{ }}`, both over the role's options and the facts `host`, `lab` and
`applied`; they are checked when the role is read, including `host.<fact>` against the known host facts. A check can't
look at the remote host, so protection that depends on the host's current state stays with `validate:`, `unless:` and
the trigger checks. Notes show in both `run -c` and `run`, once per host and message.

```yaml
checks:
  - name: ntp needs a zone
    when: ntp and not timezone
    level: error
    message: "set a timezone together with ntp"
  - when: host.container and ntp
    level: warning
    message: "{{ host.name }} is a container; its NTP comes from the Proxmox node"
```

`applied.origin.<option>` tells where this host's value came from: `lab`, `group <name>`, `type <name>`, `host <name>` or
`OS default (<os>)`, with ` (override)` added when an `overrides:` entry set it, and an empty string when the option is
unset. It works in `checks:`, `when:` and `{{ }}`. A role.yml (Python) role has no checks. The `time` and `hostname`
entries on a container already say what they leave to the Proxmox node as `info` notes.
