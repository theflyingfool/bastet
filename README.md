# Bastet

A human-readable, Markdown-based homelab inventory and (later) orchestrator.
Your inventory is a folder of Markdown notes (an Obsidian vault works well);
Bastet fills in what it can discover, shows you every change as a diff first,
and commits its own changes to git.

Status: early. Milestone 1 ("See your lab"): inventory files, gather, views.

## Requirements

### On the machine you run Bastet from

| Tool | Why |
|---|---|
| Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/) | runs Bastet |
| git | the inventory is a git repository; Bastet commits its changes |
| OpenSSH client (`ssh`, `ssh-keygen`, `ssh-keyscan`) | Bastet's key, host-key checks, gathering over SSH |
| Obsidian (optional, tested with 1.13.7) | browsing the inventory; Bases need ≥ 1.9 |

### On managed hosts

Gather runs one POSIX `sh` script per host, over SSH (or locally on the computer you run Bastet from).
No agent, no Python and no Ansible are needed on hosts.

| Tool | Package | Required? | Gives |
|---|---|---|---|
| `sh`, `cat`, `uname`, `/etc/os-release` | base system | required | OS, kernel, architecture |
| `ip` | iproute2 | required | interfaces, MACs, addresses, default gateway |
| `lscpu`, `lsblk` | util-linux | required | CPU model, cores and threads; disks and total storage |
| `/proc/meminfo` | kernel | required | RAM |
| `hostnamectl`, `systemd-detect-virt` | systemd | optional | chassis type (laptop/server/vm/container), hardware vendor and model, virtualization |
| `/sys/class/dmi/id/*` | kernel | optional | chassis type and vendor when systemd tools are missing |
| `pveversion` | Proxmox VE | optional | recognises Proxmox nodes |

The first gather can set up a `bastet` user on each host, from your own SSH login (it asks first). That user has
key login only (no password) and passwordless sudo. Setting it up needs `useradd`, `usermod`, `install`, `getent`
and `visudo` on the host (shadow-utils/passwd, coreutils, sudo).

## Getting started

    git clone <this repo> && cd bastet
    uv run bastet init
    uv run bastet add host          # walks you through it
    uv run bastet show

Config lives at `$BASTET_CONFIG`, else `$XDG_CONFIG_HOME/bastet/bastet.yml`,
else `~/.config/bastet/bastet.yml`.

## Commands

| Command | Does |
|---|---|
| `bastet init` | Config, Bastet's SSH key, the inventory repository and `Homelab.md` |
| `bastet add host [NAME] [--type …]` | Writes a minimal host file; asks for anything you leave out (`-y` to never ask) |
| `bastet add hardware [NAME] [--category …]` | Writes a hardware file; asks for anything you leave out |
| `bastet gather [HOST…]` | Collects facts and writes them into host files after a diff; `--take FIELD` accepts a value you'd set by hand |
| `bastet show [NAME]` | Lists the inventory and problems, or one object and what links to it |
