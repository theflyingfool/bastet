# Gather tool survey

Date: 2026-10-01. Sources:
- `inv.sh` and `inv2.sh`: the user's discovery scripts, kept untracked in the Infra vault.
- Ansible's `setup` fact list, for comparison.

This feeds milestone 1, stage 2 (gather).

Bastet calls each tool itself, over SSH for remote hosts and locally for the controller, parses the output, and keeps the raw output as the snapshot. It prefers JSON output wherever a tool offers it.

## What the scripts collect

| Area | Commands in `inv2.sh` (and `inv.sh`) |
|---|---|
| System | `hostnamectl`, `/etc/os-release`, `uname`, `/proc/cmdline`, `uptime`, `timedatectl`, `machine-id`, `systemd-detect-virt`, `lsb_release`, `systemd --version` |
| Hardware | `dmidecode` (system, baseboard, bios, chassis, processor, memory, slots), `/sys/class/dmi/id/*`, `lscpu`, `/proc/cpuinfo`, microcode, `free`, `/proc/meminfo`, `lshw` (memory; `inv.sh` also runs full `lshw -json -sanitize`), `lspci` (`-nn`, `-nnk`, `-vv`, `-tv`), `lsusb`, GPU via `lspci` grep, `nvidia-smi` |
| Storage | `lsblk` (MODEL, SERIAL, ROTA, TRAN columns), `df`, `findmnt`, `/proc/mounts`, `blkid`, `udevadm info --export-db`, LVM (`pvs`, `vgs`, `lvs`), `mdstat`/`mdadm`, ZFS (`zpool list/status`, `zfs list`), `nvme list` / `list-subsys`, `smartctl --scan` |
| Network | `ip -details link/address`, brief forms, routes (v4/v6/all tables), rules, `ethtool` (per interface, plus driver), `ss -lntup`/`-antup`, `resolvectl`, `/etc/resolv.conf`, `nft`/`iptables-save` |
| Software | pacman (all, explicit, deps, foreign, repos), dpkg / `apt-mark showmanual/showauto`, flatpak, snap, pip; systemd units (running, enabled, failed, timers); docker/podman (info, ps, images, volumes, networks) |
| Proxmox | `pveversion -v`, `pvesh` (node status, nodes, storage), `pvecm status`, `qm list` / `pct list`, per-guest `config` and `status` |
| Security | `mokutil --sb-state`, TPM (`systemd-analyze has-tpm2`, `tpm2_pcrread`), `getcap`, AppArmor/SELinux status, `lsmod`, capabilities |
| Misc | python3/ansible versions, ansible facts JSON, `id`, `env`, `getent passwd/group` |

## Compared with Ansible's `setup` facts

Facts the scripts already cover:
- distribution and version;
- kernel and architecture;
- CPU and memory totals;
- block devices (model, serial, size, rotational);
- mounts;
- interfaces (MAC, MTU, addresses, speed, driver);
- default route, DNS;
- DMI system, board, chassis and BIOS;
- virtualization type;
- LVM;
- SELinux/AppArmor;
- Python version, uptime, timezone, machine ID, kernel cmdline.

Facts the scripts **miss**, and whether they matter for gather:

| Ansible fact | Matters? | How Bastet gets it |
|---|---|---|
| `ssh_host_key_*_public` | **Yes**: host-key recording and the bootstrap guardrails | `ssh-keyscan` from the controller, matched against `/etc/ssh/ssh_host_*_key.pub` on the host |
| `pkg_mgr`, `service_mgr` | Later (check) | derived from which of `pacman`/`apt`/`dnf` exists; `systemd` from `/proc/1/comm` |
| `iscsi_iqn`, `hostnqn`, `fibre_channel_wwn` | No (niche) | — |
| `env`, `user_*`, `date_time`, `loadavg` | No (volatile or noise) | — |

Things **neither** collects that a good hardware inventory needs:

| Need | Tool |
|---|---|
| Out-of-band address (IPMI/BMC) | `ipmitool lan print` (needs `/dev/ipmi*`) |
| Per-drive identity and health | `smartctl -a -j <dev>` per device (`--scan` only lists devices) |
| NVMe detail | `nvme list -o json`, `nvme id-ctrl -o json` |
| Guest list with VMIDs and configs | `pvesh get /nodes/<node>/lxc` and `/qemu` with `--output-format json` |
| Permanent MAC (bonded or renamed NICs) | `ethtool -P` or `ip -j link` `permaddr` |

## Proposed collection for milestone 1

**Required on every Linux host** (from base packages):
- POSIX `sh`, `cat`, `uname`;
- `ip` (iproute2);
- `lsblk` and `lscpu` (util-linux);
- `/etc/os-release`.

**Used when present:**
- `hostnamectl` / `systemd-detect-virt` (systemd), falling back to `/sys/class/dmi/id/chassis_type` and `/proc`;
- `sudo` (or root) for the tools that need it.

| Tool (package) | Gives | JSON | Needs root | Optional? |
|---|---|---|---|---|
| `hostnamectl --json=short` (systemd ≥ 250) | hostname, chassis type, OS, kernel, hardware vendor and model | yes | no | falls back to `/sys` + `/etc/os-release` |
| `systemd-detect-virt` | vm / container / none, and which hypervisor | text, one word | no | optional |
| `lscpu -J` (util-linux) | CPU model, sockets, cores, threads | yes | no | required |
| `/proc/meminfo` | total RAM as the OS sees it | text | no | required |
| `dmidecode -t system,baseboard,bios,chassis,memory` (dmidecode) | serials, board, BIOS version, **each DIMM: slot, size, speed, part number, serial** | text, parsed | yes | optional; on physical hosts its absence is a warning |
| `lsblk -J -b -o NAME,PATH,TYPE,SIZE,MODEL,SERIAL,WWN,ROTA,TRAN,VENDOR,REV` | disks with identity | yes | no | required |
| `smartctl -a -j <dev>` (smartmontools) | model, serial, firmware, capacity, health, power-on hours | yes | yes | optional; physical hosts only |
| `nvme list -o json` (nvme-cli) | NVMe model, serial, firmware | yes | yes | optional |
| `lspci -vmm -nn -k` (pciutils) | PCIe devices (class, vendor, device, driver): HBA, GPU, NIC | machine-readable | no | optional |
| `ip -j -d link` / `ip -j addr` / `ip -j route` (iproute2) | interfaces, MACs (incl. `permaddr`), bridges/bonds/VLANs, addresses, default route | yes | no | required |
| `ethtool <if>` (ethtool) | link speed, port type | text | no | optional |
| `zpool status -P` / `zpool list -H -p` (zfsutils) | pools and member disks (by-id paths) | parseable | no | optional |
| `ipmitool lan print 1` (ipmitool) | BMC IP, MAC, source (static/DHCP) | text | yes | optional; physical hosts only |
| `pveversion` / `pvesh get … --output-format json` (Proxmox) | PVE version; guest list (VMID, name, type, status) | yes | yes (pvesh) | Proxmox nodes only |
| `ssh-keyscan` (controller, OpenSSH) | host key fingerprints | text | no | required on the controller |

**Left for milestone 2 (check):** packages, services, containers, listening ports, firewall rules, security state. **Left out:** `lsusb`, full `lspci -vv`, `udevadm` export, `lshw` (its `-sanitize` mode strips serials, and dmidecode, lsblk and smartctl cover the rest), `env`, `getent`.

## Host type from chassis

`hostnamectl` reports `Chassis` (systemd's classification from DMI and virtualization detection), with the fallback `/sys/class/dmi/id/chassis_type` (an SMBIOS number). Bastet maps it in this order; the first match wins:

1. `pveversion` present → `proxmox`.
2. Chassis `container` → `lxc`.
3. Chassis `vm` → `vps` if the DMI vendor or product names a VPS provider (e.g. "Linode", "Akamai", "DigitalOcean", "Hetzner"); otherwise `vm`.
4. Chassis `laptop`, `convertible`, `tablet` (SMBIOS 8–10, 14, 30–32) → `laptop`.
5. Chassis `server`, `desktop` (SMBIOS 3–7, 17, 23) → `server`.
6. Anything else → `unknown`.

The proposal only appears in the gather diff. It never changes `type` silently.
