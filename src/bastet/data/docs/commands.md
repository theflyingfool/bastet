# Commands

Every command Bastet has, and its options. See [[Bastet guide]] for the daily loop.

| Command | Does |
|---|---|
| `bastet init [--manage-this-machine] [--keep-days N] [-y]` | Config, Bastet's SSH key, the inventory repository and `Homelab.md`. `--keep-days N` sets how many days run records are kept in a new config (an existing config is left alone; edit `runs.keep_days` in it). It also turns on Obsidian's Bases plugin in the vault (the Runs tables need it; `bastet doctor --fix` does the same for an existing vault). With the flag (or a yes when asked), also sets up this computer as a managed host. |
| `bastet run [selectors] [-c\|-g\|-a] [--exclude …] [-y] [-j JOBS] [-v…] [--updates] [--accept-new-hostkey]` | Checks every selected host against its roles, shows the plan and, after you confirm, applies it. `-c` only checks and changes nothing. `-g` gathers facts first (on its own, or followed by `-c` or `-a`); without `-g` nothing is gathered. `--exclude` removes hosts a selector picked up. `--updates` also installs pending updates on hosts whose policy is manual. |
| `bastet log [--all]` | Lists the newest 20 past runs, or every run with `--all`, newest first: id, when it started, how it ended, the command and the number of hosts. |
| `bastet log export RUN [--out FILE]` | Prints one run's record (JSON lines), or writes it to `FILE`. `RUN` is an id from `bastet log`, or `latest`. |
| `bastet log note RUN [-y]` | Makes a run's note in the vault, or writes it again at the current detail (`runs.note_detail`, 1 to 3, default 1). It replaces the run's note file, and says "Already up to date." if nothing changed. |
| `bastet log show RUN [-v…]` | Replays a run's record in the terminal: changes and failures by default, `-vv` adds phases and items, `-vvv` adds commands with exit code and timing, `-vvvv` adds their output. |
| `bastet show [selectors]` | Read-only: lists the inventory and its problems, or shows the named hosts/hardware and what links to them. |
| `bastet add host [NAME] [--type …] [--local]` | Writes a minimal host file, asking for anything left out (`-y` to never ask). `--local` marks the computer Bastet runs on and sets it up as a managed host. |
| `bastet add role [ROLE…] [--to TARGET] [-y]` | Writes role files under `_roles/` after showing the diff; offers roles and targets as lists when left out. |
| `bastet secret` | The secret inventory: every secret, its host/role/option, whether it's set, who uses it, and a health summary. Never shows a value. |
| `bastet secret set [HOST ROLE OPTION]` | Walks secrets that need a value, or sets one by name. |
| `bastet secret show HOST ROLE OPTION` | The one deliberate way to see a value: display it or copy it to the clipboard. |
| `bastet secret unlock [HOST ROLE OPTION]` / `bastet secret lock` | Plain text in place for a bit, then re-encrypted. |
| `bastet doctor [--fix] [-y] [ROLE_DIR]` | Problems the inventory doesn't block on, found and (with `--fix`) fixed as one diff and commit. Given a folder instead, lints it as a role definition. |
| `bastet refresh` | Regenerates `_bastet/` (summaries, dashboard, docs, role pages, maps, templates) from your files; most other commands do this too. |
| `bastet help [COMMAND…]` | The same as `--help`, for Bastet or one command. |

## `-v` on `bastet run`

`-v` also lists items that are already compliant. `-vv` shows what happens as it happens: each
phase and each item with its status. `-vvv` adds every command with its exit code and how long it
took, and `-vvvv` adds the command's output. Without `-vv` the output is as it always was. Every
run is recorded in full whatever you pass; see [[Troubleshooting]].

## Run notes

A run that makes a commit also leaves a short note in the vault (see [[Hosts and facts]]).
`runs.note_detail` in `bastet.yml` sets how much it holds: 1 (the default) is the changes and
failures with why, 2 adds every item by phase, 3 adds the commands with exit code and timing. A
note never holds command output. Retention (`runs.keep_runs`, `runs.keep_days`) only limits the
records, never the notes.

## Selectors

`run` and `show` take any mix of: host names, `@group` (a group note), `@type` (every host of a
host type, e.g. `@vps`), `@lab` (every host), and shell-style globs. Leaving selectors out means
every host.

## `-y`

Every command that would otherwise ask (a missing field, confirming a diff, a new host key)
accepts `-y`/`--yes` to go ahead without asking, failing instead if something it needs wasn't given.
