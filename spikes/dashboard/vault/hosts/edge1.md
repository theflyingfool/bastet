---
bastet: host
cssclasses: [bastet-host]
type: vps
provider: linode
ip: 203.0.113.10
hostname: edge1
os: Debian 13
ram: 4 GB
location: "[[Linode]]"
groups:
  - "[[internet-facing]]"
---
# edge1
Public entry point. Caddy in front of the lab.

![[edge1/summary]]

## Roles
![[edge1/roles]]

## Status
![[edge1/status]]
