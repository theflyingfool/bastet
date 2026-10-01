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
| OpenSSH client (`ssh-keygen`) | `bastet init` creates Bastet's SSH key |
| Obsidian (optional, tested with 1.13.7) | browsing the inventory; Bases need ≥ 1.9 |

### On managed hosts

Nothing yet. Stage 1 doesn't touch hosts. Gather (stage 2) will list here the
tools it uses, which are required and which are optional, and what each optional one adds.

## Getting started

    git clone <this repo> && cd bastet
    uv run bastet init
    uv run bastet add host edge1 --type vps --provider linode --ip 203.0.113.10
    uv run bastet show

Config lives at `$BASTET_CONFIG`, else `$XDG_CONFIG_HOME/bastet/bastet.yml`,
else `~/.config/bastet/bastet.yml`.

## Commands

| Command | Does |
|---|---|
| `bastet init` | Config, Bastet's SSH key, the inventory repository and `Homelab.md` |
| `bastet add host NAME --type …` | Writes a minimal host file |
| `bastet add hardware NAME --category …` | Writes a hardware file |
| `bastet show [NAME]` | Lists the inventory and problems, or one object and what links to it |
