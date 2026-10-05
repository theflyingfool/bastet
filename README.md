# Bastet

A human-readable, Markdown-based homelab inventory and (later) orchestrator.
Your inventory is a folder of Markdown notes (an Obsidian vault works well);
Bastet fills in what it can discover, shows you every change as a diff first,
and commits its own changes to git.

Status: early. What's there now: inventory notes and views, gather, a check/apply engine, nine built-in
roles (base, pacman, proxmox, packages, users, files, ssh, harden, systemd), and age-encrypted secret notes.

## Requirements

### On the machine you run Bastet from

| Tool | Why |
|---|---|
| Python ≥ 3.12 and [uv](https://docs.astral.sh/uv/) | runs Bastet |
| git | the inventory is a git repository; Bastet commits its changes |
| OpenSSH client (`ssh`, `ssh-keygen`, `ssh-keyscan`) | Bastet's key, host-key checks, gathering over SSH |
| Obsidian (optional, tested with 1.13.7) | browsing the inventory; Bases need ≥ 1.9 |

Secrets use [pyrage](https://pypi.org/project/pyrage/) (bundled; nothing to install). `age` itself is optional,
only for by-hand recovery straight from a secret note (see [Secrets](#secrets)); `wl-copy` or `xclip` are optional,
for `bastet secret show`'s clipboard option.

### On managed hosts

Gather runs one POSIX `sh` script per host, over SSH -- including the computer you run Bastet from,
reached at `127.0.0.1`: its sshd needs to be active and answering there (`ListenAddress 127.0.0.1` is
enough even if it listens nowhere else). `bastet init` sets up the local `bastet` user for this, and
can start sshd for you if it isn't running yet.
No agent, no Python and no Ansible are needed on hosts.

**Run `bastet init` and your first `bastet apply` on a laptop while it's disconnected from any
network.** Until the `ssh` role is applied (with `listen_address: 127.0.0.1` in the laptop's own
host note), a stock sshd listens on every interface and may still allow password logins -- exactly
what `bastet init`'s local setup and the `ssh` role's lockout guard exist to close off. Do the setup
and the first `apply` offline, then reconnect.

| Tool | Package | Required? | Gives |
|---|---|---|---|
| `sh`, `cat`, `uname`, `/etc/os-release` | base system | required | OS, kernel, architecture |
| `ip` | iproute2 | required | interfaces, MACs, addresses, default gateway |
| `lscpu`, `lsblk` | util-linux | required | CPU model, cores and threads; disks and total storage |
| `/proc/meminfo` | kernel | required | RAM |
| `hostnamectl`, `systemd-detect-virt` | systemd | optional | chassis type (laptop/server/vm/container), hardware vendor and model, virtualization |
| `/sys/class/dmi/id/*` | kernel | optional | chassis type and vendor when systemd tools are missing |
| `/run/systemd/container`, `/proc/1/environ` | base system | optional | recognises containers when `systemd-detect-virt` is missing |
| `pveversion` | Proxmox VE | optional | recognises Proxmox nodes |
| `dmidecode` (as root) | dmidecode | optional | machine make/model/serial, board, BIOS, CPUs, each DIMM (slot, size, speed, part, serial), PCIe slots, power supplies |
| `smartctl` (as root) | smartmontools | optional | drive model, serial, firmware, health (SATA, SAS and NVMe) |
| `lspci` | pciutils | optional | add-in cards (GPU, HBA, NIC) and which slot they're in |
| `/sys/class/net`, `/dev/disk/by-id` | kernel, udev | optional | NIC link speeds and PCI addresses; ZFS member disks |
| `ipmitool` (as root) | ipmitool | optional | BMC/IPMI address and MAC, BMC firmware, power supplies from the FRU data (gather loads the `ipmi_devintf`/`ipmi_si` kernel modules first; offered when the board has a BMC: SMBIOS IPMI record, `/dev/ipmi*`, or BMC graphics such as ASPEED) |
| `zpool` | OpenZFS | optional | pools and their member drives |
| `ethtool` | ethtool | optional | each port's fastest supported speed and NIC firmware |
| `ip -d link` | iproute2 | optional | bridges, bonds and VLANs (guest ports left out) |
| `/sys/bus/usb` | kernel | optional | USB devices (removable ones get files; hubs left out) |
| `/proc/cpuinfo`, `/sys/firmware`, `/sys/class/tpm` | kernel | optional | CPU microcode, UEFI or BIOS boot, Secure Boot, TPM version |
| `pvesh`, `/etc/pve` guest configs (as root) | Proxmox VE | optional | guests on a Proxmox node, with their static IPs and MACs |
| `ip neigh` | iproute2 | optional | addresses the node currently sees for its guests (DHCP guests) |
| `checkupdates` | pacman-contrib | optional | Arch: pending updates without touching the package database |

Root-only tools run through passwordless sudo (the `bastet` user has it). When gathering the computer you run Bastet
from, gather asks for your sudo password once (not with `-y`, which never asks). Without root, those facts are skipped
and gather says so.

**Installing missing tools.** When a host lacks a tool gather would use (only where it's useful: e.g.
`dmidecode`/`pciutils`/`smartmontools` on physical hosts, `ethtool` on physical hosts with PCI NICs, `ipmitool` only if the board has a BMC; never on
VPS/VM/LXC), gather can install it with the host's package manager (apt, pacman, dnf, zypper or apk) and
records it in the host's `bastet_tools`. Control it in `bastet.yml`:

    gather:
      install_tools: ask      # ask (default; -y never installs) | always | never

and per host with `install_tools: false` in the host file. Every host file carries `gather: true`; set it to
`false` and a plain `bastet gather` skips the host (naming the host still gathers it).

The first gather can set up a `bastet` user on each host, from your own SSH login (it asks first). That user has
key login only (no password) and passwordless sudo. Setting it up needs `useradd`, `usermod`, `install`, `getent`
and `visudo` on the host (shadow-utils/passwd, coreutils, sudo).

## Install

Bastet runs from its source folder. Install it as a uv tool in editable mode, so `bastet` on your PATH always runs
the code in that folder: pulling or editing it takes effect on the next run, with no reinstall.

    git clone <this repo> ~/Repos/bastet
    uv tool install --editable ~/Repos/bastet
    bastet --version

If `bastet` isn't found, run `uv tool update-shell` once (it adds `~/.local/bin` to your PATH) and open a new shell.

Reinstall only when Bastet's dependencies change (`pyproject.toml`):

    uv tool install --editable --reinstall ~/Repos/bastet

Without installing, `uv run bastet …` from the source folder works the same way.

## Getting started

    bastet init
    bastet add host                 # walks you through it
    bastet show

Config lives at `$BASTET_CONFIG`, else `$XDG_CONFIG_HOME/bastet/bastet.yml`,
else `~/.config/bastet/bastet.yml`.

## Commands

| Command | Does |
|---|---|
| `bastet init` | Config, Bastet's SSH key, the inventory repository and `Homelab.md` |
| `bastet add host [NAME] [--type …]` | Writes a minimal host file; asks for anything you leave out (`-y` to never ask) |
| `bastet add hardware [NAME] [--category …]` | Writes a hardware file; asks for anything you leave out |
| `bastet gather [HOST…]` | Collects facts and writes them into host files after a diff; `--take FIELD` accepts a value you'd set by hand |
| `bastet refresh` | Regenerates page summaries and the dashboard (`_bastet/`) from your files; `add` and `gather` do this too |
| `bastet show [NAME]` | Read-only: lists the inventory and its problems, or shows one object and what links to it |
| `bastet help [COMMAND…]` | The same as `--help`, for Bastet or one command (e.g. `bastet help secret set`); bare `bastet` prints it too |
| `bastet add role [ROLE…] [--to TARGET]` | Writes role files under `_roles/` after showing the diff; offers the roles and targets as lists when left out |
| `bastet check [HOST…]` | Shows what differs between each host and its roles, and every inventory problem; changes nothing |
| `bastet apply [HOST…] [-y] [--updates]` | Shows the check, asks, applies the changes and verifies them, printing every inventory problem too; `--updates` also installs pending updates on hosts whose policy is manual |
| `bastet map` | Regenerates the cabling and network maps under `_bastet/maps/` (`refresh` does this too, along with everything else) |
| `bastet secret` | The secret inventory: every secret, its host/role/option, whether it's set, who uses it, secrets roles need but don't have, and a health summary. Never values. |
| `bastet secret set [HOST ROLE OPTION]` | Numbered list of secrets that need a value (`0` = all, `q` = quit), or the same for one named secret. Type or paste a value, Enter to generate (when the contract allows), or `e` to fill it in yourself. Reads from stdin when piped. |
| `bastet secret show HOST ROLE OPTION` | The one deliberate way to see a value: display it or copy it to the clipboard (cleared after 45s). Refuses when output isn't a terminal. |
| `bastet secret unlock [HOST ROLE OPTION]` | Plain text in place, for one secret or all; locks itself after a countdown (or run `secret lock`). |
| `bastet secret lock` | Encrypts every plain-text secret note and commits what changed. |
| `bastet secret audit` | Secret hygiene: every finding, grouped by kind. Never shows a value; writes the dashboard's audit section. |

## Secrets

A secret is a Markdown note under `_secrets/`: readable frontmatter (host, role, source, dates), and a body
that's exactly one armored `age` message. `secret:<path>` in a role option points at one. `bastet init` creates
a recovery `age` key the first time it sets up `Homelab.md` (or offers to add one to an inventory that doesn't
have one yet), prints its private half **once** — keep it offline, it's the only way back if this laptop is
lost — and adds its public half, plus your own SSH key, to `secrets.recipients`. Bastet's own key is always a
recipient too (it's not listed in the file).

Recovering a value by hand, without Bastet, needs only `age` and your SSH private key: strip the frontmatter and
decrypt the body.

    sed '1,/^---$/{/^---$/!d};1,/^---$/d' note.md | age -d -i ~/.ssh/id_ed25519

The inventory's own guide (`_bastet/Bastet guide.md`, from `src/bastet/data/guide/guide.md`) has a short walkthrough.

## Roles

Every role Bastet ships, with its options and examples: [docs/roles.md](docs/roles.md).

## Development

    uv run pytest                                   # unit tests (no network, no hosts)
    BASTET_CONTRACT=1 uv run pytest tests/contract  # engine contract tests: a throwaway Debian 13
                                                    # systemd container per test (needs podman)

Every engine resource must pass the contract test: apply it to a fresh container, apply again, and the second run
changes nothing.

The contract suite also runs the package and user resources on an Arch Linux container and needs network access for
the Debian and Arch package mirrors.
