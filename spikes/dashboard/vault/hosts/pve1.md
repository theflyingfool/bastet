---
bastet: host
cssclasses: [bastet-host]
type: proxmox-node
ip: 10.0.10.12
purchased: 2024-03-02
unquoted_date: 2024-03-01
location: "[[Closet]]"
groups:
  - "[[pvenodes]]"
interfaces:
  - name: eno1
    mac: aa:bb:cc:dd:ee:01
    speed: 1G
  - name: enp65s0f0
    mac: aa:bb:cc:dd:ee:02
    speed: 10G
oob:
  type: ipmi
  address: 10.0.10.9
zeta_last_key: keep-order
newkey: hello
---
# pve1
Proxmox node in the closet. Runs the lab's guests.

![[pve1/summary]]

## Roles
![[pve1/roles]]

## Hardware
![[hardware-here.base]]

## Status
![[pve1/status]]
