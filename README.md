# Bastet

A human-readable, Markdown-based homelab inventory and (later) orchestrator.
Your inventory is a folder of Markdown notes (an Obsidian vault works well);
Bastet fills in what it can discover, shows you every change as a diff first,
and commits its own changes to git.

Status: early. What's there now: inventory notes and views, gathering, a check/apply engine, nine built-in
roles (base, pacman, proxmox, packages, users, files, ssh, harden, systemd), and age-encrypted secret notes.

## Install

Requires Python ≥ 3.12, [uv](https://docs.astral.sh/uv/), git, and an OpenSSH client (`ssh`, `ssh-keygen`,
`ssh-keyscan`). Bastet runs from its source folder; installing it as a uv tool in editable mode means
`bastet` on your PATH always runs the code there — pulling or editing it takes effect on the next run.

    git clone <this repo> ~/Repos/bastet
    uv tool install --editable ~/Repos/bastet
    bastet --version

If `bastet` isn't found, run `uv tool update-shell` once (it adds `~/.local/bin` to your PATH) and open a
new shell. Reinstall only when `pyproject.toml` changes:

    uv tool install --editable --reinstall ~/Repos/bastet

Without installing, `uv run bastet …` from the source folder works the same way.

Shell completion: `bastet --install-completion` installs tab-completion for your shell; host names, role
names and secret paths complete too.

## Quick start

    bastet init
    bastet add host                 # walks you through it
    bastet add role packages        # or any other role
    bastet run                      # gather, check and apply, asking first
    bastet show

Config lives at `$BASTET_CONFIG`, else `$XDG_CONFIG_HOME/bastet/bastet.yml`, else
`~/.config/bastet/bastet.yml`.

Once `bastet init` has run, the inventory itself carries the rest of the documentation — open
`_bastet/docs/Bastet guide.md` in Obsidian (or [`src/bastet/data/docs/bastet_guide.md`](src/bastet/data/docs/bastet_guide.md)
in this repo, which is the same text the vault gets). It covers who writes what, the daily loop, and
links to every other doc: [Commands](src/bastet/data/docs/commands.md), [Hosts and facts](src/bastet/data/docs/hosts_and_facts.md),
[Hardware](src/bastet/data/docs/hardware.md), [Roles](src/bastet/data/docs/roles.md), [Secrets](src/bastet/data/docs/secrets.md),
[Troubleshooting](src/bastet/data/docs/troubleshooting.md) and [Writing roles](src/bastet/data/docs/writing_roles.md).

## Commands

| Command | Does |
|---|---|
| `bastet init [--manage-this-machine] [-y]` | Config, Bastet's SSH key, the inventory repository and `Homelab.md`. With the flag (or a yes when asked), also sets up this computer as a managed host. |
| `bastet run [selectors] [-c\|-g\|-a] [--exclude …] [-y] [-j JOBS] [-v] [--updates] [--accept-new-hostkey]` | Gathers facts, checks every selected host against its roles, shows the diff and applies it (the default). `-c`/`-g` stop after check/gather. See **Selectors** below. |
| `bastet show [selectors]` | Read-only: lists the inventory and its problems, or shows the named hosts/hardware and what links to them. |
| `bastet add host [NAME] [--type …] [--local]` | Writes a minimal host file, asking for anything left out (`-y` to never ask). |
| `bastet add role [ROLE…] [--to TARGET] [-y]` | Writes role files under `_roles/`, offering roles and targets as lists when left out. |
| `bastet secret [set\|show\|unlock\|lock]` | The secret inventory, and setting, viewing, unlocking and locking values. See [Secrets](src/bastet/data/docs/secrets.md). |
| `bastet doctor [--fix] [-y] [ROLE_DIR]` | Problems the inventory doesn't block on (stale keys, a skipped refresh, an unpushed commit), found and, with `--fix`, fixed as one diff and commit. Given a folder, lints it as a role definition. |
| `bastet refresh` | Regenerates everything under `_bastet/` from your files; most other commands do this too. |
| `bastet help [COMMAND…]` | The same as `--help`, for Bastet or one command. |

Full reference, with every option: [Commands](src/bastet/data/docs/commands.md).

## Selectors

`run` and `show` take any mix of host names, `@group`, `@type` (e.g. `@vps`), `@lab` (every host), and
shell-style globs; leaving them out means every host.

## Who writes what

Your notes (`Homelab.md`, `hosts/*.md`, `hardware/*.md`, `_roles/*`) are yours; Bastet only changes them
through a command that shows the diff first and asks. Everything under `_bastet/` is Bastet's own —
rewritten whenever it runs, so don't edit it by hand. See [Hosts and facts](src/bastet/data/docs/hosts_and_facts.md)
for the full split between your notes and gathered facts.

## Templates

`_templates/` (in the inventory, kept current by `bastet refresh`) holds a starting note for each host
type and hardware category, plus a role file, a group and a location — insert one with Obsidian's
"Templates: Insert template" command.

## Development

    uv run pytest                                   # unit tests (no network, no hosts)
    BASTET_CONTRACT=1 uv run pytest tests/contract  # engine contract tests: a throwaway Debian 13
                                                    # systemd container per test (needs podman)

Every engine resource must pass the contract test: apply it to a fresh container, apply again, and the
second run changes nothing. The contract suite also runs the package and user resources on an Arch Linux
container and needs network access for the Debian and Arch package mirrors.
