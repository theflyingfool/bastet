---
bastet: role-definition
name: caddy
version: 0.1.0
api: 0
description: 'The Caddy web server and reverse proxy (Arch): the main Caddyfile, one self-contained file per site in /etc/caddy/conf.d, and sites collected from the proxy option of other hosts'' roles. Every file is validated before it is written, and Caddy is reloaded only after the whole config validates. Unset = leave things as they are, except for the documented defaults in "What it does with no options".'
os:
- arch
collects:
  proxy: sites
options:
  serves:
    type: list
    description: 'The lab scopes (keys of the lab note''s domains) this Caddy answers for: exposures of other roles'' proxy option for these scopes become sites here'
    items:
      type: string
      single_line: true
  sites:
    type: list
    description: 'Sites written by hand (the sites collected from other hosts are added to this list); each becomes /etc/caddy/conf.d/<name>.caddy'
    items:
      type: object
      fields:
        name:
          type: string
          required: true
          single_line: true
          description: 'The hostname the site answers for, e.g. router.example.com (letters, digits, dots, dashes and a leading * only)'
        upstream:
          type: any
          description: 'Where to proxy to: one host:port, or a list of them. A site with none writes no reverse_proxy (use extra for the rest)'
        tls_skip_verify:
          type: bool
          description: 'Do not verify the backend''s certificate (a backend with a self-signed certificate)'
        allow:
          type: list
          description: 'Addresses or networks that may use the site; everyone else gets 403. [] writes no restriction'
          items:
            type: string
            single_line: true
        headers:
          type: map
          description: 'Headers added to the request sent to the backend (name: value)'
          items:
            type: string
            single_line: true
        encode:
          type: bool
          description: 'true compresses responses (encode zstd gzip)'
        extra:
          type: string
          description: 'Raw Caddyfile text added inside the site block'
  email:
    type: string
    single_line: true
    description: 'ACME account email, written as the email line of the global block'
  admin:
    type: string
    single_line: true
    description: 'The admin endpoint: off, or an address. Unset keeps the package''s unix socket'
  log_level:
    type: string
    choices: [DEBUG, INFO, WARN, ERROR, PANIC, FATAL]
    description: 'Global log level, written as a log block in the global block'
  trusted_proxies:
    type: list
    description: 'Networks of proxies in front of Caddy whose forwarded headers are trusted (servers / trusted_proxies static)'
    items:
      type: string
      single_line: true
  snippets:
    type: map
    description: 'Name to raw text, each written as a (name) { ... } block in the Caddyfile, for hand-written config to import'
    items:
      type: string
  extra:
    type: string
    description: 'Raw Caddyfile text added at the end of the global block'
examples:
- title: A reverse proxy with one site written by hand
  yaml: |
    email: admin@example.com
    sites:
      - name: router.example.com
        upstream: 10.1.0.1:443
        tls_skip_verify: true
        allow:
          - 10.1.0.0/16
- title: The Caddy that answers for the public scope (other hosts' roles expose their apps to it with their proxy option)
  yaml: |
    serves:
      - public
    email: admin@example.com
- title: Behind another proxy, with a snippet for hand-written config
  yaml: |
    trusted_proxies:
      - 10.1.0.0/16
    snippets:
      security: |
        header X-Frame-Options DENY
checks:
- name: bad hostname
  when: sites is not none and (sites | map(attribute='name') | join('') | list | reject('in', 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-*') | list | length) > 0
  level: error
  message: 'a site name is not a valid hostname (letters, digits, dots, dashes and a leading * only; no scheme, port or path)'
- name: bad snippet name
  when: snippets is not none and (snippets | list | join('') | list | reject('in', 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-') | list | length) > 0
  level: error
  message: 'a snippets name has a character other than letters, digits, dots, dashes and underscores'
- name: site without upstream
  when: sites is not none and (sites | selectattr('upstream', 'defined') | selectattr('upstream') | list | length) < (sites | length)
  level: warning
  message: 'a site has no upstream, so its file has no reverse_proxy; give it an upstream or put the directive in its extra'
- name: stale site files
  when: sites
  level: info
  message: 'a site removed from the list leaves its file in /etc/caddy/conf.d (Bastet does not delete files yet); remove it by hand and reload Caddy'
packages:
- caddy
files:
- path: /etc/caddy/Caddyfile
  template: Caddyfile.j2
  mode: '0644'
  owner: root
  group: root
  on_change: &reload
  - name: reload caddy (after validating the whole config)
    run: |
      systemctl is-active --quiet caddy.service || exit 0
      runuser -u caddy -- env XDG_DATA_HOME=/var/lib XDG_CONFIG_HOME=/etc caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile
      systemctl reload caddy.service
- path: /etc/caddy/conf.d
  directory: true
  mode: '0755'
  owner: root
  group: root
- path: /etc/caddy/conf.d/{{ item.name | lower }}.caddy
  template: site.j2
  each: sites
  mode: '0644'
  owner: root
  group: root
  validate: caddy validate --adapter caddyfile --config %s
  on_change: *reload
systemd:
- kind: unit
  name: caddy.service
  enabled: true
  state: up
commands:
- name: caddy config is valid
  run: runuser -u caddy -- env XDG_DATA_HOME=/var/lib XDG_CONFIG_HOME=/etc caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile
  unless: runuser -u caddy -- env XDG_DATA_HOME=/var/lib XDG_CONFIG_HOME=/etc caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile
---

# caddy role

The Caddy web server as a reverse proxy, on Arch. The role manages the main `/etc/caddy/Caddyfile` and writes one
small, self-contained file per site into `/etc/caddy/conf.d`. Sites are either written by hand in `sites`, or collected
from the `proxy` option of other hosts' roles: an app role says "expose me as `vault.example.com`", and the Caddy that
`serves` that scope gets the site (`collects` in the role's frontmatter).

## What it does with no options

On an Arch host with no options at all, this role does exactly this (a documented default, there is nothing to turn
off but the role itself):

- Installs the `caddy` package.
- Writes `/etc/caddy/Caddyfile` with a global block that keeps the package's own `admin "unix//run/caddy/admin.socket"`
  (so the admin API never falls back to TCP port 2019), then `import /etc/caddy/conf.d/*`. The package's welcome-page
  site is **not** kept: the role owns this file outright.
- Creates `/etc/caddy/conf.d` (other roles may put files there too).
- Enables and starts `caddy.service`.
- Checks on every run that the whole config on disk is valid (see "Validation and reloads").

Everything below is written only when you set the option.

## Options

| Option | Written as |
| --- | --- |
| `serves` | nothing of its own: the scopes (keys of the lab note's `domains`) this Caddy receives exposures for |
| `sites` | one file per site, see below |
| `email` | `email <value>` in the global block |
| `admin` | `admin <value>` in place of the package's socket (`off` or an address) |
| `log_level` | `log { level <value> }` in the global block |
| `trusted_proxies` | `servers { trusted_proxies static <list> }` (an empty list writes nothing) |
| `snippets` | a `(name) { ... }` block per entry, between the global block and the import, for hand-written files to `import` |
| `extra` | raw text at the end of the global block |

A line break in `email`, `admin`, `log_level`, a `trusted_proxies` entry or a site's `name`, `allow` or `headers` value
is refused; `extra` and `snippets` are raw text and may have many lines.

## Sites

Each site (manual or collected) becomes `/etc/caddy/conf.d/<hostname>.caddy`, a complete site block that needs nothing
from the main Caddyfile (no `import`). A site uses only its own values; the fields are:

| Field | Written as |
| --- | --- |
| `name` | the site address (the hostname) and the file name |
| `upstream` | `reverse_proxy <upstream>` (one `host:port`, or a list) |
| `tls_skip_verify` | `transport http { tls_insecure_skip_verify }` inside `reverse_proxy` |
| `allow` | `@denied not remote_ip <list>` and `respond @denied 403` (`[]` writes nothing) |
| `headers` | a `header_up` line per entry inside `reverse_proxy` |
| `encode` | `encode zstd gzip` when `true` |
| `extra` | raw text inside the site block |

A collected site also carries `host` (the exposing host) and `source` (the note that exposed it); both are only
information. One Caddy never gets the same hostname twice: two sources for one name (collected or manual) are an error
that names both. A site removed from the list leaves its file behind, because Bastet does not delete files yet; the role
says so (info). The same hostname on two different Caddies is fine (split horizon).

## Validation and reloads

Bastet never reloads Caddy without validating first.

- **Each site file is validated alone** (`caddy validate --adapter caddyfile --config <file>`) before it is written, so
  a bad file never lands on disk.
- **A changed Caddyfile or site file runs one gated reload**, once per host, after everything else: if `caddy.service`
  is not running nothing happens; otherwise the whole config is validated as the `caddy` user and only then
  `systemctl reload caddy.service` runs. When validation fails the reload is never attempted and the run fails with
  Caddy's own error. The role uses no plain `reload:`/`restart:` trigger.
- **A standing check** (`caddy config is valid`) validates the whole config on disk on every run and is silent while it
  is valid, so a config that was left invalid (a run that failed earlier, or a hand edit) is reported each time. On the
  very first run of a host it shows once as a change, because Caddy is not installed yet when the check is planned.

## Changes

- 0.1.0: first version: the Caddyfile, `conf.d` site files, collected sites, validation before every write and reload.
