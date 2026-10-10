# Bastet guide

Start here. Bastet keeps this vault as a readable inventory of your lab, and fills in what it can.
This page, and the rest of `_bastet/docs/`, ships with the Bastet you run, so it always matches it.

## Who writes what

- **Yours:** `Homelab.md`, `hosts/*.md`, `hardware/*.md`, `_roles/*`, and any other note. Bastet only
  changes them through a command that shows you the diff first and asks.
- **Bastet's:** everything under `_bastet/`: these docs, the dashboard, facts notes, role reference
  pages and the Bases views. They're rewritten whenever Bastet runs; don't edit them by hand.
- Bastet commits its own changes to git, as "Bastet". When a command is about to change your notes,
  any uncommitted edits of yours to those same notes are offered to be committed first.

## The daily loop

1. `bastet run` gathers facts, checks every host against its roles, shows the diff and applies it
   (after asking, unless you pass `-y`). Point it at a subset with selectors, or `-c`/`-g`/`-a` to
   stop after checking or gathering.
2. `bastet show` lists the inventory and its problems, or one host/hardware item and what links to it.
3. `bastet doctor` finds anything the inventory doesn't block on (stale keys, a skipped refresh,
   unpushed commits) and fixes what it safely can with `--fix`.

See [[Commands]] for every command and option, [[Hosts and facts]] for the notes/facts split,
[[Hardware]] for physical inventory, [[Roles]] for configuration, and [[Secrets]] for secret values.
