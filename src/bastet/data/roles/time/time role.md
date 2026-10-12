---
bastet: role-definition
name: time
version: 1.0.0
api: 0
description: 'The time zone (every system) and, on Arch, time sync with systemd-timesyncd: servers and poll settings go in a drop-in at /etc/systemd/timesyncd.conf.d/bastet.conf. Unset = leave things as they are.'
starter:
  timezone: UTC
  ntp: true
options:
  timezone:
    type: string
    description: 'IANA time zone, e.g. Europe/Berlin (checked against a list of known zones)'
    choices_from: time zones.txt
  ntp:
    type: bool
    description: 'Time sync: unset leaves it alone, true configures and starts systemd-timesyncd (Arch), false stops and disables it'
  ntp_servers:
    type: list
    description: 'NTP: servers to ask (they come after per-interface servers; the stock servers stay as fallback)'
    items:
      type: string
    key: NTP
    section: Time
    as: list
    requires:
      ntp: true
  ntp_fallback_servers:
    type: list
    description: 'FallbackNTP: servers used only when no other server is known (replaces timesyncd''s built-in list)'
    items:
      type: string
    key: FallbackNTP
    section: Time
    as: list
    requires:
      ntp: true
  root_distance_max_sec:
    type: string
    description: 'RootDistanceMaxSec: largest acceptable distance to the reference clock (default 5s)'
    key: RootDistanceMaxSec
    section: Time
    single_line: true
    requires:
      ntp: true
  poll_interval_min_sec:
    type: string
    description: 'PollIntervalMinSec: shortest time between polls (default 32s, at least 16s)'
    key: PollIntervalMinSec
    section: Time
    single_line: true
    requires:
      ntp: true
  poll_interval_max_sec:
    type: string
    description: 'PollIntervalMaxSec: longest time between polls (default 34min 8s, larger than the minimum)'
    key: PollIntervalMaxSec
    section: Time
    single_line: true
    requires:
      ntp: true
  connection_retry_sec:
    type: string
    description: 'ConnectionRetrySec: wait before trying a new server (default 30s, at least 1s)'
    key: ConnectionRetrySec
    section: Time
    single_line: true
    requires:
      ntp: true
  save_interval_sec:
    type: string
    description: 'SaveIntervalSec: how often the clock is saved to disk when nothing syncs (default 60s; infinity = never)'
    key: SaveIntervalSec
    section: Time
    single_line: true
    requires:
      ntp: true
examples:
- title: Time zone only (works on every system)
  yaml: |
    timezone: Europe/Berlin
- title: Arch host synced against a local server
  yaml: |
    timezone: Europe/Berlin
    ntp: true
    ntp_servers:
      - 10.1.1.1
- title: A host on an SD card, writing the clock as little as possible
  yaml: |
    ntp: true
    poll_interval_min_sec: 1d
    save_interval_sec: infinity
checks:
- name: ntp set lab-wide
  when: ntp and applied.origin.ntp.startswith('lab')
  level: warning
  message: 'time sync is only implemented for Arch; setting `ntp` lab-wide makes every Debian/Proxmox host fail. Set `ntp` on an Arch group instead, or add an `overrides:` entry (`when: not host.arch_like`, `ntp: null`) to the lab note, or write `ntp: null` in the Debian/Proxmox group''s note.'
- name: container sync
  when: host.container and ntp is not none
  level: info
  message: 'time sync on a container is provided by its host; only the time zone is applied'
- name: sync needs Arch
  when: not host.container and not host.arch_like and ntp
  level: error
  message: 'time sync is implemented for systemd-timesyncd on Arch only; chrony for Debian/Proxmox is planned. Set `ntp: null` for this host or group to apply only the time zone.'
- name: sync off elsewhere
  when: not host.container and not host.arch_like and ntp is not none and not ntp
  level: info
  message: '`ntp: false` is not applied on this system yet; nothing changed'
systemd:
- kind: time
  timezone: '{{ timezone }}'
sections:
- name: timesyncd (Arch)
  when: host.arch_like and not host.container
  files:
  - path: /etc/systemd/timesyncd.conf.d/bastet.conf
    edit: ini
    when: ntp
    restart:
    - systemd-timesyncd.service
  systemd:
  - kind: unit
    name: systemd-timesyncd.service
    enabled: '{{ ntp }}'
    state: "{{ 'up' if ntp else 'down' }}"
    when: ntp is not none
---

# time role

The time zone, and on Arch time sync with systemd-timesyncd. Unset = leave things as they are: a host with no options
gets no change at all.

## Supported systems

- **Time zone: every system** where `timedatectl` works, containers included. The value must be a known IANA zone
  (`Europe/Berlin`, `UTC`, ...); anything else is refused. The list of zones is a snapshot taken when Bastet's version is
  bumped (`time zones.txt` in this role's folder), so a zone added by a very recent tzdata release may be missing until
  the next release.
- **Arch (and Arch-based): systemd-timesyncd.** `ntp` and the timesyncd options below are written to a drop-in,
  `/etc/systemd/timesyncd.conf.d/bastet.conf` (created, with its `[Time]` section, when it does not exist), and the
  service is enabled and started.
- **Debian and Proxmox: chrony is planned, not built.** Needs expanding: until then `ntp: true` (or any timesyncd
  option, which needs `ntp: true`) on such a host is an **error**, and `ntp: false` is only an info note ("not applied on
  this system yet; nothing changed"). The time zone still applies. An unknown OS is treated like Debian.
- **LXC containers: time sync belongs to the Proxmox node.** If `ntp` is set the role says so (info) and applies only the
  time zone; it never claims to have configured sync.

## Options

`timezone` and `ntp` are described above. The other seven are the settings of `timesyncd.conf(5)` under their upstream
names, written in the `[Time]` section, and each needs `ntp: true` (a note that sets one without it is refused):

| Option | timesyncd key | Value |
| --- | --- | --- |
| `ntp_servers` | `NTP` | list of host names or addresses |
| `ntp_fallback_servers` | `FallbackNTP` | list of host names or addresses |
| `root_distance_max_sec` | `RootDistanceMaxSec` | time span, e.g. `5s` |
| `poll_interval_min_sec` | `PollIntervalMinSec` | time span, e.g. `32s`, `1d` |
| `poll_interval_max_sec` | `PollIntervalMaxSec` | time span, e.g. `34min` |
| `connection_retry_sec` | `ConnectionRetrySec` | time span, e.g. `30s` |
| `save_interval_sec` | `SaveIntervalSec` | time span, or `infinity` |

Time spans are plain text for timesyncd (see `systemd.time(7)`): `32` is 32 seconds, `1d` a day. Write numbers in quotes
(`"32"`) so they stay text. Only the settings you give are written, in a Bastet block in the drop-in.

## What a change does

- Changing the drop-in **restarts** `systemd-timesyncd.service`, but only if it is running. No daemon-reload is needed or
  done: the file is the service's configuration, not a unit definition.
- A stopped or failed service is not started by a change to the file. `ntp: true` itself does start it (and enables it
  at boot).
- `ntp: false` stops and disables the service. It writes nothing and leaves an existing drop-in in place, because Bastet
  does not delete files yet; turning `ntp` on again uses it as it was.
- `ntp` unset leaves the service and the drop-in completely alone.

## Servers

systemd-timesyncd asks per-interface servers first (from systemd-networkd or DHCP). The servers in `NTP=` are added after
them and tried in turn until one answers. The stock servers are timesyncd's built-in `FallbackNTP` list: they are used
only when no other server is known, so they stay in place when `NTP=` is set. `ntp_fallback_servers` replaces that
built-in list.

## Writing less to an SD card

timesyncd saves the clock to `/var/lib/systemd/timesync/clock` at every sync and every 60 seconds. On an SD card or a
read-only root, cut the writes down:

```yaml
ntp: true
poll_interval_min_sec: 1d
save_interval_sec: infinity
```

## One note for the whole lab

Time sync is only built for Arch. Setting `ntp: true` in the lab note makes every Debian and Proxmox host fail with an
error, and the role warns about it. Either set `ntp` in a group of Arch hosts, or keep it in the lab note and opt the
others out with an override, so they only get the time zone and no sync message:

```yaml
timezone: Europe/Berlin
ntp: true
overrides:
  - when: "not host.arch_like"
    ntp: null
```

A group or host note with `ntp: null` does the same for just those hosts.

## Changes

- 1.0.0: first version; replaces the time options of the `systemd` role.
