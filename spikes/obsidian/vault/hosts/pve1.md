---
bastet: host
type: proxmox-node
# this comment tests whether Obsidian keeps YAML comments
ip: 10.0.10.11
purchased: "2024-03-01"
unquoted_date: 2024-03-01
location: "[[Closet]]"
groups: ["[[pvenodes]]"]
interfaces:
  - {name: eno1, mac: "aa:bb:cc:dd:ee:01", speed: 1G}
  - name: enp65s0f0
    mac: "aa:bb:cc:dd:ee:02"
    speed: 10G
oob: {type: ipmi, address: 10.0.10.9}
zeta_last_key: keep-order
---
# pve1

This paragraph must never change.

## Hardware (embedded base)

![[hardware-here.base]]

## Hardware (inline base block)

```base
filters:
  and:
    - file.inFolder("hardware")
    - file.hasLink(this.file)
views:
  - type: table
    name: inline hasLink
    order:
      - file.name
      - serial
      - size
```
