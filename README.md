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
| `bastet refresh` | Regenerates page summaries and the dashboard (`_bastet/`) from your files; `show`, `add` and `gather` do this too |
| `bastet show [NAME]` | Lists the inventory and problems, or one object and what links to it |
| `bastet add role [ROLE…] [--to TARGET]` | Writes role files under `_roles/` after showing the diff; offers the roles and targets as lists when left out |
| `bastet check [HOST…]` | Shows what differs between each host and its roles; changes nothing |
| `bastet apply [HOST…] [-y] [--updates]` | Shows the check, asks, applies the changes and verifies them; `--updates` also installs pending updates on hosts whose policy is manual |

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
