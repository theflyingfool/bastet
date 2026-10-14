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
  site_defaults:
    type: object
    description: 'Values every site of this Caddy inherits when it does not set its own: a site''s own value wins, then this one, then nothing is written. Set it in a group or host note to give one proxy different defaults from another'
    fields:
      tls_skip_verify:
        type: bool
        description: 'Default for a site''s tls_skip_verify'
      allow:
        type: list
        description: 'Default for a site''s allow (a site''s own list replaces it; [] on a site drops it)'
        items:
          type: string
          single_line: true
      headers:
        type: map
        description: 'Headers every site sends to its backend; a site''s header of the same name wins'
        items:
          type: string
          single_line: true
      encode:
        type: bool
        description: 'Default for a site''s encode'
      extra:
        type: string
        description: 'Raw Caddyfile text added inside every site block, before the site''s own extra'
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
  dns:
    type: object
    description: 'Build Caddy with a DNS-challenge plugin on this host so certificates can be issued with DNS-01 (names that are not reachable from the internet, wildcards). Unset = stock Caddy, nothing below exists on the host. The credentials go in dns_secrets'
    fields:
      provider:
        type: string
        required: true
        single_line: true
        description: 'The caddy-dns module name: github.com/caddy-dns/<provider> (linode, cloudflare and namecheap are documented below; any other caddy-dns module works with its fields passed through as given)'
      version:
        type: string
        single_line: true
        description: 'The plugin release to build: latest (the default, rebuilt when a newer one appears) or a tag such as v0.8.0'
      settings:
        type: map
        description: 'The provider''s plain fields, written as they are in the acme_dns block (for example user, or api_endpoint for Namecheap)'
        items:
          type: string
          single_line: true
      propagation_delay:
        type: string
        single_line: true
        description: 'How long to wait before checking that the challenge record is visible, e.g. 2m (written in each site''s tls block)'
      propagation_timeout:
        type: string
        single_line: true
        description: 'How long to wait for the record to propagate, e.g. 5m, or -1 for no check'
      ttl:
        type: string
        single_line: true
        description: 'TTL of the challenge record, e.g. 30s (written as dns_ttl)'
      resolvers:
        type: list
        description: 'DNS servers used to check the challenge record, e.g. 1.1.1.1; needed when this host''s own resolver answers differently for the name (split-horizon)'
        items:
          type: string
          single_line: true
  dns_secrets:
    type: map
    description: 'The provider''s secret fields, by their name in the acme_dns block, each a secret: reference (for example api_token: secret:linode_token). They are written to /etc/caddy/dns.env (root only, mode 0600) as DNS_<FIELD>, and the Caddyfile refers to them as {env.DNS_<FIELD>}. A separate option from dns so that only the files that hold or name a secret are hidden in diffs'
    items:
      type: string
      single_line: true
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
- title: Certificates with the DNS challenge, Linode (Caddy is rebuilt on this host with the plugin)
  yaml: |
    serves:
      - internal
    dns:
      provider: linode
      resolvers:
        - 1.1.1.1
      ttl: 30s
    dns_secrets:
      api_token: secret:linode_token
- title: The same with Cloudflare, pinned to a plugin release
  yaml: |
    dns:
      provider: cloudflare
      version: v0.2.1
    dns_secrets:
      api_token: secret:cloudflare_token
- title: The same with Namecheap (a user name and an API key; try the sandbox endpoint first)
  yaml: |
    dns:
      provider: namecheap
      settings:
        user: example-user
        api_endpoint: https://api.sandbox.namecheap.com/xml.response
    dns_secrets:
      api_key: secret:namecheap_key
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
- name: bad dns provider
  when: dns is not none and ((dns.provider | length) == 0 or (dns.provider | list | reject('in', 'abcdefghijklmnopqrstuvwxyz0123456789-_') | list | length) > 0)
  level: error
  message: 'dns.provider must be a caddy-dns module name (lower-case letters, digits, dashes and underscores), for example linode'
- name: bad dns field name
  when: (dns is not none and dns.get('settings') is not none and (dns.get('settings') | list | join('') | list | reject('in', 'abcdefghijklmnopqrstuvwxyz0123456789_') | list | length) > 0) or (dns_secrets is not none and (dns_secrets | list | join('') | list | reject('in', 'abcdefghijklmnopqrstuvwxyz0123456789_') | list | length) > 0)
  level: error
  message: 'a dns settings or dns_secrets name has a character other than lower-case letters, digits and underscores (use the provider''s field name, for example api_token)'
- name: dns secrets without dns
  when: dns is none and dns_secrets
  level: error
  message: 'dns_secrets is set but dns is not: nothing would use them (set dns.provider, or remove dns_secrets)'
- name: dns provider not documented
  when: dns is not none and dns.provider not in ['linode', 'cloudflare', 'namecheap']
  level: info
  message: 'this dns provider is not documented in the caddy role: its settings and dns_secrets are passed through as given and are not validated (the plugin must exist under github.com/caddy-dns)'
- name: documented dns provider without its secret
  when: dns is not none and ((dns.provider in ['linode', 'cloudflare'] and 'api_token' not in (dns_secrets or {})) or (dns.provider == 'namecheap' and 'api_key' not in (dns_secrets or {})))
  level: warning
  message: 'this dns provider needs a secret field that dns_secrets does not have (api_token for linode and cloudflare, api_key for namecheap), so the certificate request would fail'
- name: stale site files
  when: sites
  level: info
  message: 'a site removed from the list leaves its file in /etc/caddy/conf.d (Bastet does not delete files yet); remove it by hand and reload Caddy'
packages:
- caddy
- name: go
  when: dns is not none
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
      runuser -u caddy -- env XDG_DATA_HOME=/var/lib XDG_CONFIG_HOME=/etc {% if dns is not none %}/usr/local/bin/caddy-bastet{% else %}caddy{% endif %} validate --adapter caddyfile --config /etc/caddy/Caddyfile
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
  validate: "{% if dns is not none %}if [ -x /usr/local/bin/caddy-bastet ]; then /usr/local/bin/caddy-bastet validate --adapter caddyfile --config %s; fi{% else %}caddy validate --adapter caddyfile --config %s{% endif %}"
  on_change: *reload
- path: /etc/caddy/dns.caddy
  template: dns.caddy.j2
  when: dns is not none
  mode: '0644'
  owner: root
  group: root
  on_change: *reload
- path: /etc/caddy/dns.env
  template: dns.env.j2
  when: dns is not none and dns_secrets
  mode: '0600'
  owner: root
  group: root
  on_change: &restart
  - name: restart caddy (after validating the whole config)
    run: |
      systemctl is-active --quiet caddy.service || exit 0
      runuser -u caddy -- env XDG_DATA_HOME=/var/lib XDG_CONFIG_HOME=/etc /usr/local/bin/caddy-bastet validate --adapter caddyfile --config /etc/caddy/Caddyfile
      systemctl try-restart caddy.service
- path: /usr/local/lib/caddy-bastet
  directory: true
  when: dns is not none
  mode: '0755'
  owner: root
  group: root
- path: /usr/local/lib/caddy-bastet/build
  template: build.sh.j2
  when: dns is not none
  mode: '0755'
  owner: root
  group: root
- path: /etc/systemd/system/caddy-bastet-build.service
  when: dns is not none
  mode: '0644'
  owner: root
  group: root
  daemon_reload: true
  content: |
    # Managed by Bastet (the caddy role); changes made here are overwritten.
    [Unit]
    Description=Build Caddy with the DNS plugin (Bastet)
    After=network-online.target
    Wants=network-online.target

    [Service]
    Type=oneshot
    DynamicUser=yes
    CacheDirectory=caddy-bastet
    RuntimeDirectory=caddy-bastet
    RuntimeDirectoryPreserve=no
    Environment=GOCACHE=/var/cache/caddy-bastet/go-build GOPATH=/var/cache/caddy-bastet/gopath GOMODCACHE=/var/cache/caddy-bastet/gopath/pkg/mod GOBIN=/run/caddy-bastet/bin GOTMPDIR=/var/cache/caddy-bastet/tmp TMPDIR=/var/cache/caddy-bastet/tmp GOTOOLCHAIN=local XDG_CONFIG_HOME=/var/cache/caddy-bastet/xdg
    ProtectSystem=strict
    ProtectHome=yes
    PrivateTmp=yes
    NoNewPrivileges=yes
    TimeoutStartSec=30min
    ExecStartPre=/usr/bin/mkdir -p /var/cache/caddy-bastet/tmp /run/caddy-bastet/bin
    ExecStart=/usr/local/lib/caddy-bastet/build build
    ExecStartPost=+/usr/local/lib/caddy-bastet/build install
- path: /etc/systemd/system/caddy.service.d
  directory: true
  when: dns is not none
  mode: '0755'
  owner: root
  group: root
- path: /etc/systemd/system/caddy.service.d/bastet-dns.conf
  when: dns is not none
  mode: '0644'
  owner: root
  group: root
  daemon_reload: true
  on_change: *restart
  content: |
    # Managed by Bastet (the caddy role); changes made here are overwritten.
    [Service]
    EnvironmentFile=-/etc/caddy/dns.env
    ExecStartPre=
    ExecStartPre=/usr/local/bin/caddy-bastet validate --config /etc/caddy/Caddyfile
    ExecStart=
    ExecStart=/usr/local/bin/caddy-bastet run --config /etc/caddy/Caddyfile
    ExecReload=
    ExecReload=/usr/local/bin/caddy-bastet reload --config /etc/caddy/Caddyfile --force
- path: /etc/pacman.d/hooks
  directory: true
  when: dns is not none
  mode: '0755'
  owner: root
  group: root
- path: /etc/pacman.d/hooks/caddy-bastet.hook
  when: dns is not none
  mode: '0644'
  owner: root
  group: root
  content: |
    # Managed by Bastet (the caddy role); changes made here are overwritten.
    [Trigger]
    Operation = Install
    Operation = Upgrade
    Type = Package
    Target = caddy
    Target = go

    [Action]
    Description = Rebuilding Caddy with the DNS plugin (Bastet)
    When = PostTransaction
    Exec = /usr/bin/systemctl start --no-block caddy-bastet-build.service
systemd:
- kind: unit
  name: caddy.service
  enabled: true
  state: up
commands:
- name: build caddy with the dns plugin
  when: dns is not none
  before: systemd
  run: /usr/local/lib/caddy-bastet/build rebuild
  unless: /usr/local/lib/caddy-bastet/build current
- name: caddy config is valid
  when: dns is none
  run: runuser -u caddy -- env XDG_DATA_HOME=/var/lib XDG_CONFIG_HOME=/etc caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile
  unless: runuser -u caddy -- env XDG_DATA_HOME=/var/lib XDG_CONFIG_HOME=/etc caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile
- name: caddy config is valid (with the dns plugin)
  when: dns is not none
  run: runuser -u caddy -- env XDG_DATA_HOME=/var/lib XDG_CONFIG_HOME=/etc /usr/local/bin/caddy-bastet validate --adapter caddyfile --config /etc/caddy/Caddyfile
  unless: runuser -u caddy -- env XDG_DATA_HOME=/var/lib XDG_CONFIG_HOME=/etc /usr/local/bin/caddy-bastet validate --adapter caddyfile --config /etc/caddy/Caddyfile
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
| `site_defaults` | nothing of its own: values every site of this Caddy inherits (see "Defaults for sites") |
| `email` | `email <value>` in the global block |
| `admin` | `admin <value>` in place of the package's socket (`off` or an address) |
| `log_level` | `log { level <value> }` in the global block |
| `trusted_proxies` | `servers { trusted_proxies static <list> }` (an empty list writes nothing) |
| `snippets` | a `(name) { ... }` block per entry, between the global block and the import, for hand-written files to `import` |
| `extra` | raw text at the end of the global block |
| `dns` | builds Caddy with a DNS-challenge plugin, see "Certificates with the DNS challenge" |
| `dns_secrets` | the plugin's secret fields, written to `/etc/caddy/dns.env` (mode 0600) |

A line break in `email`, `admin`, `log_level`, a `trusted_proxies` entry or a site's `name`, `allow` or `headers` value
is refused; `extra` and `snippets` are raw text and may have many lines.

## Sites

Each site (manual or collected) becomes `/etc/caddy/conf.d/<hostname>.caddy`, a complete site block that needs nothing
from the main Caddyfile (no `import`). The fields are:

| Field | Written as |
| --- | --- |
| `name` | the site address (the hostname) and the file name |
| `upstream` | `reverse_proxy <upstream>` (one `host:port`, or a list) |
| `tls_skip_verify` | `transport http { tls_insecure_skip_verify }` inside `reverse_proxy` |
| `allow` | `@denied not client_ip <list>` and `respond @denied 403` (`[]` writes nothing) |
| `headers` | a `header_up` line per entry inside `reverse_proxy` |
| `encode` | `encode zstd gzip` when `true` |
| `extra` | raw text inside the site block |

A collected site also carries `host` (the exposing host) and `source` (the note that exposed it); both are only
information. One Caddy never gets the same hostname twice: two sources for one name (collected or manual) are an error
that names both. A site removed from the list leaves its file behind, because Bastet does not delete files yet; the role
says so (info). The same hostname on two different Caddies is fine (split horizon).

`allow` matches on `client_ip`: the address of whoever connects to Caddy, or, when this Caddy sits behind another proxy
that is listed in `trusted_proxies`, the real visitor that proxy forwards. Without `trusted_proxies` it is the same as the
connecting address, so a Caddy that is the first stop needs nothing extra; a Caddy behind another proxy should set
`trusted_proxies` to that proxy's network, or the allow list would only ever see the proxy. The apps behind Caddy see the
real address only if they trust the forwarded header (an app setting, not Caddy's).

## Defaults for sites

`site_defaults` has the same knobs as a site (`tls_skip_verify`, `allow`, `headers`, `encode`, `extra`) and is an
ordinary option, so a group or host note can give one proxy different defaults from another (for example the home-lab
Caddy defaults `allow` to the LAN and the tunnel). There are no lab-wide defaults. For each knob a site gets:

1. its own value, whether it was written by hand or exposed by another host's role (the app knows what only the app
   knows);
2. else the Caddy's `site_defaults` value;
3. else nothing is written, and Caddy's own behaviour applies.

`false`, `0`, `""` and `[]` are values, so a site can switch a default off: `encode: false`, `tls_skip_verify: false`,
`allow: []` (no restriction). A site's own list or flag replaces the default. `headers` merge by header name, and the
site's value wins for a name both set. `extra` is the exception: the default's text is written first and the site's
text after it, so a site cannot remove a default's `extra`.

## Certificates with the DNS challenge (`dns`)

Stock Caddy gets certificates with HTTP-01, which needs the name to reach this host from the internet. For names that
do not (an internal copy of a public name, a wildcard) Caddy needs a DNS-challenge plugin, which is not in the Arch
package. Set `dns` and the role builds Caddy with the plugin on this host and keeps it current. Unset = none of this
exists.

What it adds (all of it only when `dns` is set):

- `go` from the repository (it stays installed: every Caddy update rebuilds).
- `/usr/local/lib/caddy-bastet/build`, a small script holding the provider and version, and
  `caddy-bastet-build.service`, a one-shot unit that runs it as a throwaway user in a sandbox with no access to the
  credentials. It installs `xcaddy` with `go install ...@latest`, builds the packaged Caddy version with the plugin,
  checks the new binary against the current config, moves it to `/usr/local/bin/caddy-bastet` and restarts Caddy.
  Caches live on disk in `/var/cache/caddy-bastet`; only the executables are in `/run` (nothing under a
  `DynamicUser` cache or state directory can be executed).
- A systemd drop-in that points `caddy.service` at `caddy-bastet`: it clears and replaces `ExecStartPre`,
  `ExecStart` and `ExecReload` (the packaged `ExecStartPre` validates with the stock binary, which does not know the
  plugin) and loads `/etc/caddy/dns.env`.
- `/etc/caddy/dns.caddy`, the `acme_dns <provider> { ... }` block, imported from the global block of the Caddyfile.
- `/etc/caddy/dns.env` (owner root, mode 0600): your `dns_secrets` as `DNS_<FIELD>` variables. Only the service reads
  it (systemd loads it as root); the build unit never does.
- A pacman hook that starts the build after `caddy` or `go` change, without making pacman wait for it.
- In each site file a `tls { ... }` block when you set `propagation_delay`, `propagation_timeout`, `ttl` (written as
  `dns_ttl`) or `resolvers`; the global `acme_dns` block does not accept them. `resolvers` matters when this host's own
  resolver answers differently for the name (split-horizon DNS), because the check for the challenge record would
  otherwise ask it.

**When it rebuilds.** The hook rebuilds after every `caddy` or `go` update (also a reinstall), because Go fixes reach
a TLS server only through a rebuild. Every run also asks the script whether the built binary has the packaged Caddy
version and the wanted plugin version (`version: latest` asks Go's module proxy what `@latest` is); if not, it builds
before Caddy is started. A build that fails leaves the old binary running and fails the run with the build's own
output; a failure inside the hook is only seen on the next run (Bastet has no notification channel yet), and until then
the older Caddy keeps serving. The build is slow the first time (about two minutes and 1 GB of memory on the machine
this was tested on) and a warm rebuild takes seconds. Each build prints the versions it used (journal and
`/usr/local/share/caddy-bastet.build`).

**Credentials.** Put each secret field in `dns_secrets` as a secret reference, for example
`api_token: secret:linode_token`; the role turns the field name into `DNS_API_TOKEN`. A residual risk to know about:
the plugin's code runs inside Caddy and can read the token, which is why a plugin release can be pinned (`version`)
and why the token should be limited to DNS.

**Providers.** Any module under github.com/caddy-dns works; these three are documented (from each plugin's own
README; what the README does not say is marked unverified, and the providers themselves were not exercised):

| | linode | cloudflare | namecheap |
| --- | --- | --- | --- |
| Secret fields (`dns_secrets`) | `api_token` (a Personal Access Token) | `api_token` | `api_key` |
| Plain fields (`dns.settings`) | optional `api_url`, `api_version`, `debug_logs_enabled` | none | `user` (required); optional `api_endpoint`, `client_ip` (found automatically when unset) |
| What the token needs | not stated by the plugin; expected: domains read and write only (unverified) | Zone.Zone:Read and Zone.DNS:Edit on the zones Caddy manages (a separate `zone_token` exists but is deprecated) | not stated by the plugin; Namecheap's API probably needs API access enabled and the host's IP whitelisted (unverified) |
| Watch out for | set a low `ttl` such as 30s: a TTL of 0 means Linode's default, which resolvers may cache for hours | "Invalid request headers" means the token variable does not reach Caddy; "expected 1 zone, got 0" means the resolver cannot see public DNS, so set `resolvers` | try the sandbox `api_endpoint` first |

**Turning `dns` off** is not undone by the role: Go stays installed (Bastet does not remove packages yet), the build
unit, script, hook and `caddy-bastet` stay on the host, and the drop-in is no longer written but stays in place, so
`caddy.service` keeps running `caddy-bastet`. Remove those by hand, or leave them; nothing rebuilds without the hook
and the guard.

## Validation and reloads

Bastet never reloads Caddy without validating first.

- **Each site file is validated alone** (`caddy validate --adapter caddyfile --config <file>`) before it is written, so
  a bad file never lands on disk.
- With `dns` set the same checks use `caddy-bastet`, which knows the plugin. A site file is checked alone only once
  `caddy-bastet` exists (the first run writes the files before it is built), and the gated reload, which runs after the
  build, checks everything.
- **A changed Caddyfile or site file runs one gated reload**, once per host, after everything else: if `caddy.service`
  is not running nothing happens; otherwise the whole config is validated as the `caddy` user and only then
  `systemctl reload caddy.service` runs. When validation fails the reload is never attempted and the run fails with
  Caddy's own error. The role uses no plain `reload:`/`restart:` trigger.
- **A standing check** (`caddy config is valid`) validates the whole config on disk on every run and is silent while it
  is valid, so a config that was left invalid (a run that failed earlier, or a hand edit) is reported each time. On the
  very first run of a host it shows once as a change, because Caddy is not installed yet when the check is planned.

## Changes

- 0.1.0: first version: the Caddyfile, `conf.d` site files, collected sites, `site_defaults`, `client_ip` for `allow`,
  the DNS challenge (`dns`, `dns_secrets`) with a Caddy built on the host, validation before every write, reload and
  restart.
