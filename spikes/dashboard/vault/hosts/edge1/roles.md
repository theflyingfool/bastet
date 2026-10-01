---
generated: true
---
| Role | From | Option | Value | Source |
|---|---|---|---|---|
| ssh | type | password_auth | false | default |
| hardening | type | firewall | strict | group [[internet-facing]] |
| users | type | admin | nick | lab |
| updates | type | update_policy | security | group [[internet-facing]] |
| caddy | host | collects | git.example.com → git1:3000 | exposed by [[git1]] |
| caddy | host | update_policy | auto | default |
