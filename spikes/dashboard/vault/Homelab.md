---
bastet: lab
cssclasses: [bastet-dashboard]
name: Homelab
domains:
  public: example.com
  internal: lab.example.net
timezone: America/New_York
acme_email: admin@example.com
proxy:
  public: "[[edge1]]"
networks:
  mgmt:
    cidr: 10.0.10.0/24
    vlan: 10
    purpose: [infrastructure]
  servers:
    cidr: 10.0.20.0/24
    vlan: 20
    purpose: [apps]
---
# 🐈‍⬛ Homelab

![[_bastet/glance]]

![[_bastet/attention]]

![[_bastet/where]]

![[_bastet/domains]]

![[_bastet/hardware]]

![[_bastet/recent]]
