---
bastet: host
cssclasses: [bastet-host]
type: lxc
runs_on: "[[pve1]]"
network: servers
ip: 10.0.20.21
cores: 2
ram: 2 GB
disk: 16 GB
---
# git1
Gitea for the lab.

## Roles
| Role | From | Option | Value | Source |
|---|---|---|---|---|
| ssh, hardening, users, updates | type | — | defaults | |
| gitea | host | expose | git.example.com (public) | host file |
| gitea | host | admin_password | ‹secret · generated 2026-09-30› | |
| gitea | host | settings | 2 set · 412 available | [[git1/gitea.settings]] |
