# Troubleshooting

## `bastet doctor`

Run it any time. Without `--fix` it only lists problems: stale gathered keys on a host or
hardware note, a page still embedding a retired note, why the last refresh was skipped, and a
pending push. With `--fix`, it applies every problem that has a fix, as one diff and one commit —
a stale key is only removed once the facts note already holds the value, so nothing is lost.

Given a folder instead of running against the inventory, `bastet doctor <dir>` lints it as a role
definition.

## Skipped refreshes

If `_bastet/` falls behind your files (for example, a command was interrupted), Bastet remembers
why and `bastet doctor` reports it. Running any command that refreshes (`run`, `add`, `refresh`
itself) catches it back up.

## Push failures

Bastet commits its own changes locally even when it can't reach the remote; `bastet doctor` lists
unpushed commits so you notice, and the next successful push catches up.

## Colour

Bastet colours its output on a terminal. Set `NO_COLOR=1` to turn that off. Piped or redirected
output is always plain text.

## Getting unstuck

See [[Bastet guide]] for who writes what, [[Hosts and facts]] for the notes/facts split, and
[[Using secrets]] if a command refuses to run because a secret is unlocked.
