# Bastet guide

Bastet keeps this vault as a readable inventory of your lab, and fills it in for you.
This page is generated from the Bastet version you run, so it always matches it.

## Your files and Bastet's

- **Yours:** `Homelab.md` (lab settings in its properties), `hosts/*.md`, `hardware/*.md`, and any other
  notes. Bastet only changes them through a command that shows you the diff first and asks.
- **Bastet's:** everything under `_bastet/`: page summaries, this guide, the dashboard and the Bases views.
  They're rewritten whenever Bastet runs; don't edit them (your changes would be replaced).
- Bastet commits its own changes to git, as "Bastet". When a command is about to change your notes,
  your uncommitted edits to Bastet-managed notes are offered to be committed as you first. Anything you
  change under `_bastet/` is simply regenerated.

## Everyday commands

| Command | Does |
|---|---|
| `bastet add host` | Adds a host; asks for anything you leave out (`-y` never asks) |
| `bastet add hardware` | Adds a hardware item, e.g. a spare drive |
| `bastet gather` | Collects facts from every host (or the ones you name), shows the diff, writes |
| `bastet refresh` | Rebuilds summaries and the dashboard from your files; no hosts contacted |
| `bastet show [name]` | Lists the inventory and problems, or one item and what links to it |

## Facts, desired values and yours

- **Facts** (OS, CPU, RAM, drives, serials…) come from gather. If you set one by hand and the machine
  disagrees, Bastet keeps your value and tells you who set it; `bastet gather --take <field>` accepts
  the observed one.
- **Desired** values (e.g. an LXC's RAM) are what you want; Bastet reports differences (applying them
  comes later).
- **Your** values (purchase date, location, status, notes) are never touched.

## Host switches you can set

- `gather: true` is on every host file. Set it to `false` to skip the host when you run `bastet gather` for
  everything (naming it still gathers it).
- `install_tools: false` stops gather from installing its helper tools on that host. What gather has
  installed is listed in the host's `bastet_tools`.

## Drift

Your files are the source of truth. When something changes outside Bastet (say, a guest's IP edited in
Proxmox), Bastet reports it as **drift**: in gather's output, in a Drift box on that host's page, and in
the dashboard's "Needs attention". Bastet never changes your file to match. The drift stays listed until
the file and reality agree again.

## Hardware

Physical hosts get a file per machine, drive, add-in card, CPU, memory stick, power supply and removable USB
device under `hardware/`, linked to the host with `installed_in`. Built-in parts (integrated graphics, built-in
USB devices) and firmware (BIOS, BMC, microcode, TPM, Secure Boot) are listed on the machine's file; each port
shows its fastest supported speed. Bridges, bonds and VLANs are on the host's file. Hardware that moves keeps its file; hardware that disappears is reported, never deleted.
Set `status:` (`spare`, `failed`, `retired`, `sold`) yourself.

## Reading the pages

- ⚠ lines under a summary are warnings from that host's last gather.
- The dashboard's "Needs attention" collects them for every host.
- Proxmox nodes list their guests; gather offers to add guests that aren't in the inventory yet.
