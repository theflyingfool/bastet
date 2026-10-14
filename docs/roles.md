# Roles

Every role Bastet ships. Put values in a role file's properties (`_roles/lab/<role>.md`, `_roles/groups/<group>/<role>.md` or `_roles/hosts/<host>/<role>.md`), or run `bastet add role`.

| Role | What it does |
|---|---|
| [apt](#apt) | apt's own settings, written to /etc/apt/apt.conf.d/90-bastet (Debian-based hosts; aim it at `debian`) |
| [base](#base) | The basics every host gets: a set of admin tools, and CPU microcode on physical machines |
| [caddy](#caddy) | The Caddy web server and reverse proxy (Arch): the main Caddyfile, one self-contained file per site in /etc/caddy/conf.d, and sites collected from the proxy option of other hosts' roles |
| [files](#files) | Files, directories, links, and blocks or lines inside other files |
| [packages](#packages) | Packages for apt, pacman, dnf, zypper and apk |
| [pacman](#pacman) | pacman's own settings: every [options] setting in /etc/pacman.conf (Arch-based hosts; aim it at `arch`) |
| [systemd](#systemd) | Settings systemd owns: hostname, locale, and services with their drop-ins (time and time sync are the time role) |
| [time](#time) | The time zone (every system) and, on Arch, time sync with systemd-timesyncd: servers and poll settings go in a drop-in at /etc/systemd/timesyncd.conf.d/bastet.conf |
| [users](#users) | Users, groups, SSH keys and sudoers rules |

## apt

apt's own settings, written to /etc/apt/apt.conf.d/90-bastet (Debian-based hosts; aim it at `debian`). Unset = leave apt's setting as it is. A curated, incomplete list of options. Repositories are written in apt's own format (deb822 files in /etc/apt/sources.list.d).

### Examples

**Go through a proxy (all Debian hosts)**

```yaml
acquire_http_proxy: http://proxy.example.net:3128
acquire_https_proxy: http://proxy.example.net:3128
acquire_retries: 3
```

**No recommended packages**

```yaml
install_recommends: false
```

**Debian backports**

```yaml
repositories:
  - name: backports
    uris:
      - http://deb.debian.org/debian
    suites:
      - trixie-backports
    components:
      - main
    signed_by: /usr/share/keyrings/debian-archive-keyring.gpg
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| install_recommends | bool |  | APT::Install-Recommends: install recommended packages too |
| install_suggests | bool |  | APT::Install-Suggests: install suggested packages too |
| default_release | string |  | APT::Default-Release: the release to install from by default, e.g. trixie-backports |
| keep_downloaded_packages | bool |  | APT::Keep-Downloaded-Packages: keep .deb files after installing |
| autoremove_suggests_important | bool |  | APT::AutoRemove::SuggestsImportant: treat suggested packages as important for autoremove |
| acquire_retries | int |  | Acquire::Retries: download retries |
| acquire_http_timeout | int |  | Acquire::http::Timeout: seconds |
| acquire_https_timeout | int |  | Acquire::https::Timeout: seconds |
| acquire_http_proxy | string |  | Acquire::http::Proxy: e.g. http://proxy.example.net:3128 |
| acquire_https_proxy | string |  | Acquire::https::Proxy |
| acquire_languages | list of string |  | Acquire::Languages: translations to download (en, none, …) |
| dpkg_options | list of string |  | Dpkg::Options: options passed to dpkg |
| repositories | list of object |  | Extra apt repositories, one /etc/apt/sources.list.d/<name>.sources file each, written before packages are installed |
| repositories[].name | string |  | File name, letters, digits and . _ + - |
| repositories[].types | list of string | ["deb"] | deb, deb-src |
| repositories[].uris | list of string |  |  |
| repositories[].suites | list of string |  |  |
| repositories[].components | list of string |  |  |
| repositories[].architectures | list of string |  |  |
| repositories[].enabled | bool |  |  |
| repositories[].trusted | bool |  |  |
| repositories[].signed_by | string |  | A key file path, or the armored key text |
| modernize_sources | bool | false | Run `apt modernize-sources` to convert leftover legacy .list files to .sources; does nothing when there is nothing to convert. Where apt cannot work out Signed-By it prints a warning and the new file has none |

## base

The basics every host gets: a set of admin tools, and CPU microcode on physical machines. With no options it installs vim, zsh, git, htop, tree, gdu, wget and less, plus the microcode package for the host's CPU if the host is a physical machine (Arch: intel-ucode or amd-ucode; Debian: intel-microcode or amd64-microcode).

### Examples

**Everywhere (put in the lab note)**

```yaml
extra_tools:
  - jq
```

**Only these tools**

```yaml
tools:
  - vim
  - git
```

**A machine that should not get microcode**

```yaml
microcode: never
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| tools | list of string | ["vim", "zsh", "git", "htop", "tree", "gdu", "wget", "less"] | Admin tools to install; setting this replaces the default list (use extra_tools to add to it) |
| extra_tools | list of string |  | More tools on top of `tools`, at every level (lab, group, host) |
| microcode | string | auto | auto: install the CPU microcode package on physical hosts (never on VMs or containers); never: install none (one of auto, never) |
| baseline | string |  | Reserved for a later round; has no effect |

## caddy

The Caddy web server and reverse proxy (Arch): the main Caddyfile, one self-contained file per site in /etc/caddy/conf.d, and sites collected from the proxy option of other hosts' roles. Every file is validated before it is written, and Caddy is reloaded only after the whole config validates. Unset = leave things as they are, except for the documented defaults in "What it does with no options".

### Examples

**A reverse proxy with one site written by hand**

```yaml
email: admin@example.com
sites:
  - name: router.example.com
    upstream: 10.1.0.1:443
    tls_skip_verify: true
    allow:
      - 10.1.0.0/16
```

**The Caddy that answers for the public scope (other hosts' roles expose their apps to it with their proxy option)**

```yaml
serves:
  - public
email: admin@example.com
```

**Certificates with the DNS challenge, Linode (Caddy is rebuilt on this host with the plugin)**

```yaml
serves:
  - internal
dns:
  provider: linode
  resolvers:
    - 1.1.1.1
  ttl: 30s
dns_secrets:
  api_token: secret:linode_token
```

**The same with Cloudflare, pinned to a plugin release**

```yaml
dns:
  provider: cloudflare
  version: v0.2.1
dns_secrets:
  api_token: secret:cloudflare_token
```

**The same with Namecheap (a user name and an API key; try the sandbox endpoint first)**

```yaml
dns:
  provider: namecheap
  settings:
    user: example-user
    api_endpoint: https://api.sandbox.namecheap.com/xml.response
dns_secrets:
  api_key: secret:namecheap_key
```

**Behind another proxy, with a snippet for hand-written config**

```yaml
trusted_proxies:
  - 10.1.0.0/16
snippets:
  security: |
    header X-Frame-Options DENY
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| serves | list of string |  | The lab scopes (keys of the lab note's domains) this Caddy answers for: exposures of other roles' proxy option for these scopes become sites here |
| sites | list of object |  | Sites written by hand (the sites collected from other hosts are added to this list); each becomes /etc/caddy/conf.d/<name>.caddy |
| sites[].name | string |  | The hostname the site answers for, e.g. router.example.com (letters, digits, dots, dashes and a leading * only) |
| sites[].upstream | any |  | Where to proxy to: one host:port, or a list of them. A site with none writes no reverse_proxy (use extra for the rest) |
| sites[].tls_skip_verify | bool |  | Do not verify the backend's certificate (a backend with a self-signed certificate) |
| sites[].allow | list of string |  | Addresses or networks that may use the site; everyone else gets 403. [] writes no restriction |
| sites[].headers | map of string |  | Headers added to the request sent to the backend (name: value) |
| sites[].encode | bool |  | true compresses responses (encode zstd gzip) |
| sites[].extra | string |  | Raw Caddyfile text added inside the site block |
| site_defaults | object |  | Values every site of this Caddy inherits when it does not set its own: a site's own value wins, then this one, then nothing is written. Set it in a group or host note to give one proxy different defaults from another |
| site_defaults.tls_skip_verify | bool |  | Default for a site's tls_skip_verify |
| site_defaults.allow | list of string |  | Default for a site's allow (a site's own list replaces it; [] on a site drops it) |
| site_defaults.headers | map of string |  | Headers every site sends to its backend; a site's header of the same name wins |
| site_defaults.encode | bool |  | Default for a site's encode |
| site_defaults.extra | string |  | Raw Caddyfile text added inside every site block, before the site's own extra |
| email | string |  | ACME account email, written as the email line of the global block |
| admin | string |  | The admin endpoint: off, or an address. Unset keeps the package's unix socket |
| log_level | string |  | Global log level, written as a log block in the global block (one of DEBUG, INFO, WARN, ERROR, PANIC, FATAL) |
| trusted_proxies | list of string |  | Networks of proxies in front of Caddy whose forwarded headers are trusted (servers / trusted_proxies static) |
| snippets | map of string |  | Name to raw text, each written as a (name) { ... } block in the Caddyfile, for hand-written config to import |
| extra | string |  | Raw Caddyfile text added at the end of the global block |
| dns | object |  | Build Caddy with a DNS-challenge plugin on this host so certificates can be issued with DNS-01 (names that are not reachable from the internet, wildcards). Unset = stock Caddy, nothing below exists on the host. The credentials go in dns_secrets |
| dns.provider | string |  | The caddy-dns module name: github.com/caddy-dns/<provider> (linode, cloudflare and namecheap are documented below; any other caddy-dns module works with its fields passed through as given) |
| dns.version | string |  | The plugin release to build: latest (the default, rebuilt when a newer one appears) or a tag such as v0.8.0 |
| dns.settings | map of string |  | The provider's plain fields, written as they are in the acme_dns block (for example user, or api_endpoint for Namecheap) |
| dns.propagation_delay | string |  | How long to wait before checking that the challenge record is visible, e.g. 2m (written in each site's tls block) |
| dns.propagation_timeout | string |  | How long to wait for the record to propagate, e.g. 5m, or -1 for no check |
| dns.ttl | string |  | TTL of the challenge record, e.g. 30s (written as dns_ttl) |
| dns.resolvers | list of string |  | DNS servers used to check the challenge record, e.g. 1.1.1.1; needed when this host's own resolver answers differently for the name (split-horizon) |
| dns_secrets | map of string |  | The provider's secret fields, by their name in the acme_dns block, each a secret: reference (for example api_token: secret:linode_token). They are written to /etc/caddy/dns.env (root only, mode 0600) as DNS_<FIELD>, and the Caddyfile refers to them as {env.DNS_<FIELD>}. A separate option from dns so that only the files that hold or name a secret are hidden in diffs |

### Collects

- Collects `proxy` exposures from other hosts' roles into `sites`.

## files

Files, directories, links, and blocks or lines inside other files. Planned settings edits, added when a role needs them: env (KEY=value files), sshd, sysctl (key = value).

### Examples

**A file, a directory and a link**

```yaml
files:
  /etc/motd:
    content: "Managed by Bastet\n"
    mode: "0644"
directories:
  /srv/app:
    mode: "0750"
links:
  /srv/current: /srv/app
```

**One line in someone else's file**

```yaml
lines:
  - path: /etc/ssh/sshd_config
    line: PermitRootLogin no
    match: "^#?PermitRootLogin"
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| files | map of object |  | Whole files by absolute path |
| files.<name>.content | string |  |  |
| files.<name>.template | string |  | A Jinja2 template in the inventory (path from its root); gets host, name, lab |
| files.<name>.owner | string |  |  |
| files.<name>.group | string |  |  |
| files.<name>.mode | string |  | Quoted, e.g. "0644" |
| files.<name>.validate | string |  | Command checking the new file first; %s is its path |
| files.<name>.secret | bool |  | Never show the contents |
| files.<name>.restart | list of string |  | Units to restart when this changes |
| files.<name>.reload | list of string |  | Units to reload (or restart) when this changes |
| directories | map of object |  | Directories by absolute path |
| directories.<name>.owner | string |  |  |
| directories.<name>.group | string |  |  |
| directories.<name>.mode | string |  |  |
| links | map of string |  | Symlinks: path -> target |
| blocks | list of object |  | A marked block inside a file |
| blocks[].path | string |  |  |
| blocks[].marker | string |  |  |
| blocks[].block | string |  |  |
| blocks[].comment | string |  | Comment character for the markers (default #) |
| blocks[].validate | string |  |  |
| blocks[].secret | bool |  | Never show the contents |
| blocks[].restart | list of string |  | Units to restart when this changes |
| blocks[].reload | list of string |  | Units to reload (or restart) when this changes |
| lines | list of object |  | One line inside a file |
| lines[].path | string |  |  |
| lines[].line | string |  |  |
| lines[].match | string |  | Regex for the line to replace |
| lines[].unique | bool |  | With match: also remove the other uncommented lines it matches (for settings that may appear more than once) |
| lines[].after | string |  | Regex: when the line isn't there yet, insert it after the last line matching this (instead of at the end) |
| lines[].validate | string |  |  |
| lines[].secret | bool |  | Never show the contents |
| lines[].restart | list of string |  | Units to restart when this changes |
| lines[].reload | list of string |  | Units to reload (or restart) when this changes |
| commands | list of object |  | Escape hatch: run a command unless a check command succeeds (use a real option when one exists) |
| commands[].name | string |  |  |
| commands[].run | string |  | The command |
| commands[].unless | string |  | Skip when this command exits 0 |
| commands[].root | bool |  | Run as root (default true) |

## packages

Packages for apt, pacman, dnf, zypper and apk. A new lab starts with a note for this role at the lab level, so it applies to every host (installs nothing on its own, but reports pending updates, reboot need and packages no role accounts for).

### Examples

**Lab-wide (put in _roles/lab/packages.md) — apply updates, ask before rebooting**

```yaml
updates: auto
reboot: ask
```

**Keep the system updated automatically, holding one package back**

```yaml
updates: auto
updates_exclude:
  - linux-lts
allowed:
  - steam
```

**Install a few packages**

```yaml
install:
  - tree
  - htop
```

**Pin one version, skip recommended packages**

```yaml
install_recommends: false
install:
  - name: jq
    version: "1.7.1-3"
```

**Remove a package**

```yaml
remove:
  - nano
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| refresh | bool | true | Refresh the package index before installing. Arch: refreshes and upgrades the whole system together (-Syu); false installs with plain -S, which fails or half-upgrades when the sync database is stale |
| install_recommends | bool |  | apt recommends / dnf weak deps / zypper recommends; unset = distro default |
| full_upgrade | bool | false | Upgrade the whole system as part of installing (pacman -Syu, apt full-upgrade, …) |
| default_release | string |  | apt only: install from this release (-t), e.g. trixie-backports |
| allow_change_held | bool | false | apt only: allow changing held packages |
| dpkg_options | list of string |  | apt only: dpkg options; default keeps changed config files (--force-confdef --force-confold) |
| extra_args | list of string |  | Extra arguments for the package manager (e.g. --enablerepo=crb) |
| install | list of object |  | Packages to install; a name, or a map with per-package knobs |
| install[].name | string |  |  |
| install[].version | string |  | Exact version (not on pacman); rpm accepts a version without release |
| install[].install_recommends | bool |  |  |
| install[].default_release | string |  |  |
| install[].allow_change_held | bool |  |  |
| install[].dpkg_options | list of string |  |  |
| install[].extra_args | list of string |  |  |
| install[].refresh | bool |  |  |
| install[].full_upgrade | bool |  |  |
| install[].manager | string |  | Fail unless the host uses this manager (one of apt-get, pacman, dnf, zypper, apk) |
| remove | list of object |  | Packages to remove |
| remove[].name | string |  |  |
| remove[].purge | bool |  | Also remove config (apt purge, pacman -Rns, apk --purge) |
| remove[].manager | string |  | Fail unless the host uses this manager (one of apt-get, pacman, dnf, zypper, apk) |
| remove[].dpkg_options | list of string |  |  |
| remove[].allow_change_held | bool |  |  |
| remove[].extra_args | list of string |  |  |
| updates | string | manual | manual: check reports pending updates, apply installs them only with --updates. auto: apply installs them. security: apply installs security updates (apt, dnf, zypper) (one of manual, auto, security) |
| reboot | string | ask | After apply, when the host needs a reboot (new kernel, /run/reboot-required): never = only report it; ask = ask (never under -y); auto = reboot and wait for the host. Bastet never reboots the machine it runs on. (one of never, ask, auto) |
| reboot_timeout | int | 600 | Seconds to wait for the host to come back after a reboot |
| updates_exclude | list of string |  | Never upgrade these (pacman --ignore, dnf --exclude, …) |
| allowed | list of string |  | Packages that are fine without a role (not reported as unaccounted); a host with a provider (Linode on Arch) also gets that provider's stock-image packages allowed automatically |
| report_unaccounted | bool | true | Report packages installed outside Bastet (explicitly installed, not in the system set, no role, not allowed or in the provider's stock image) |

## pacman

pacman's own settings: every [options] setting in /etc/pacman.conf (Arch-based hosts; aim it at `arch`). Unset = leave pacman's setting as it is. Settings you give are written in a Bastet block right after [options], and the original lines are commented out with `#bastet: `. Repositories are written in pacman's own format (a block in /etc/pacman.conf, marked `bastet repo <name>`).

### Examples

**All Arch hosts (put in _roles/groups/pacman.md with applies_to "`arch`")**

```yaml
parallel_downloads: 10
verbose_pkg_lists: true
```

**Hold the kernel back, skip docs, keep the current cache only**

```yaml
ignore_pkg:
  - linux
  - linux-headers
no_extract:
  - usr/share/doc/*
clean_method:
  - KeepCurrent
```

**A custom repository**

```yaml
repositories:
  - name: custom
    servers:
      - https://repo.example.net/$repo/os/$arch
    sig_level: Optional
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| root_dir | string |  | RootDir: installation root |
| db_path | string |  | DBPath: package database location |
| cache_dir | list of string |  | CacheDir: package cache directories |
| hook_dir | list of string |  | HookDir: extra hook directories |
| gpg_dir | string |  | GPGDir: keyring directory |
| log_file | string |  | LogFile |
| hold_pkg | list of string |  | HoldPkg: ask before removing these (pacman, glibc by default); [] comments it out |
| ignore_pkg | list of string |  | IgnorePkg: never upgrade these |
| ignore_group | list of string |  | IgnoreGroup: never upgrade packages in these groups |
| no_upgrade | list of string |  | NoUpgrade: files never overwritten on upgrade (saved as .pacnew) |
| no_extract | list of string |  | NoExtract: files never installed (e.g. usr/share/doc/*) |
| architecture | string |  | Architecture (auto, x86_64, …) |
| xfer_command | string |  | XferCommand: external download command (%u URL, %o output) |
| parallel_downloads | int |  | ParallelDownloads: packages downloaded at once |
| disable_download_timeout | bool |  | DisableDownloadTimeout |
| download_user | string |  | DownloadUser: unprivileged user downloads run as |
| disable_sandbox | bool |  | DisableSandbox: turn off the download sandbox |
| clean_method | list of string |  | CleanMethod: what pacman -Sc keeps |
| sig_level | string |  | SigLevel, e.g. Required DatabaseOptional |
| local_file_sig_level | string |  | LocalFileSigLevel |
| remote_file_sig_level | string |  | RemoteFileSigLevel |
| color | bool | true | Color: colour output |
| candy | bool | true | ILoveCandy: Pac-Man progress bar |
| no_progress_bar | bool |  | NoProgressBar |
| verbose_pkg_lists | bool |  | VerbosePkgLists: old and new versions in a table |
| check_space | bool |  | CheckSpace: check disk space before installing |
| use_syslog | bool |  | UseSyslog: log to syslog too |
| reflector | bool | true | Mirror list upkeep (a stopgap): installs reflector and starts reflector.timer, which refreshes the mirror list on its own schedule. While it is on, etc/pacman.d/mirrorlist is in NoExtract so a pacman-mirrorlist upgrade does not overwrite it. false does neither |
| repositories | list of object |  | Extra pacman repositories, one marked block each at the end of /etc/pacman.conf, written before packages are installed |
| repositories[].name | string |  | Repository name, letters, digits and . _ + - |
| repositories[].servers | list of string |  |  |
| repositories[].include | string |  | A mirror list file, e.g. /etc/pacman.d/mirrorlist |
| repositories[].sig_level | string |  | e.g. Required, Optional or Never |
| repositories[].usage | string |  |  |
| repositories[].enabled | bool |  | false comments the whole block out |

## systemd

Settings systemd owns: hostname, locale, and services with their drop-ins (time and time sync are the time role). Arch comes with this role by default only for its accounts, the systemd-* system users every Arch install has; with no options it changes nothing.

### Examples

**Keep a service running, with a drop-in**

```yaml
services:
  ssh.service:
    enabled: true
    state: up
dropins:
  - unit: ssh.service
    name: bastet
    content: |
      [Service]
      Restart=always
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| manage_hostname | bool | false | Set the hostname from the host file's hostname: (or the note name); off unless you turn it on |
| locale | string |  | LANG, e.g. en_US.UTF-8; the locale must exist on the host |
| keymap | string |  | Console keymap (not supported on Debian yet) |
| services | map of object |  | Units and the state you want them in, e.g. ssh.service: {enabled: true, state: up} |
| services.<name>.enabled | bool |  | Start at boot |
| services.<name>.state | string |  | Running now or stopped (one of up, down) |
| dropins | list of object |  | Drop-in files for units: /etc/systemd/system/<unit>.d/<name>.conf |
| dropins[].unit | string |  | e.g. gitea.service |
| dropins[].name | string |  | File name without .conf |
| dropins[].content | string |  | The drop-in's contents |
| dropins[].restart | bool | true | Restart the unit when the drop-in changes |

## time

The time zone (every system) and, on Arch, time sync with systemd-timesyncd: servers and poll settings go in a drop-in at /etc/systemd/timesyncd.conf.d/bastet.conf. On other systems the sync settings are ignored with a note and only the time zone applies. Unset = leave things as they are.

### Examples

**Time zone only (works on every system)**

```yaml
timezone: Europe/Berlin
```

**Arch host synced against a local server**

```yaml
timezone: Europe/Berlin
ntp: true
ntp_servers:
  - 10.1.1.1
```

**In the lab note (other systems ignore the sync settings and only get the time zone)**

```yaml
timezone: Europe/Berlin
ntp: true
ntp_servers:
  - 10.1.1.1
```

**A host on an SD card, writing the clock as little as possible**

```yaml
ntp: true
poll_interval_min_sec: 1d
save_interval_sec: infinity
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| timezone | string |  | IANA time zone, e.g. Europe/Berlin (checked against a list of known zones) <details><summary>598 allowed values</summary>Africa/Abidjan, Africa/Accra, Africa/Addis_Ababa, Africa/Algiers, Africa/Asmara, Africa/Asmera, Africa/Bamako, Africa/Bangui, Africa/Banjul, Africa/Bissau, Africa/Blantyre, Africa/Brazzaville, Africa/Bujumbura, Africa/Cairo, Africa/Casablanca, Africa/Ceuta, Africa/Conakry, Africa/Dakar, Africa/Dar_es_Salaam, Africa/Djibouti, Africa/Douala, Africa/El_Aaiun, Africa/Freetown, Africa/Gaborone, Africa/Harare, Africa/Johannesburg, Africa/Juba, Africa/Kampala, Africa/Khartoum, Africa/Kigali, Africa/Kinshasa, Africa/Lagos, Africa/Libreville, Africa/Lome, Africa/Luanda, Africa/Lubumbashi, Africa/Lusaka, Africa/Malabo, Africa/Maputo, Africa/Maseru, Africa/Mbabane, Africa/Mogadishu, Africa/Monrovia, Africa/Nairobi, Africa/Ndjamena, Africa/Niamey, Africa/Nouakchott, Africa/Ouagadougou, Africa/Porto-Novo, Africa/Sao_Tome, Africa/Timbuktu, Africa/Tripoli, Africa/Tunis, Africa/Windhoek, America/Adak, America/Anchorage, America/Anguilla, America/Antigua, America/Araguaina, America/Argentina/Buenos_Aires, America/Argentina/Catamarca, America/Argentina/ComodRivadavia, America/Argentina/Cordoba, America/Argentina/Jujuy, America/Argentina/La_Rioja, America/Argentina/Mendoza, America/Argentina/Rio_Gallegos, America/Argentina/Salta, America/Argentina/San_Juan, America/Argentina/San_Luis, America/Argentina/Tucuman, America/Argentina/Ushuaia, America/Aruba, America/Asuncion, America/Atikokan, America/Atka, America/Bahia, America/Bahia_Banderas, America/Barbados, America/Belem, America/Belize, America/Blanc-Sablon, America/Boa_Vista, America/Bogota, America/Boise, America/Buenos_Aires, America/Cambridge_Bay, America/Campo_Grande, America/Cancun, America/Caracas, America/Catamarca, America/Cayenne, America/Cayman, America/Chicago, America/Chihuahua, America/Ciudad_Juarez, America/Coral_Harbour, America/Cordoba, America/Costa_Rica, America/Coyhaique, America/Creston, America/Cuiaba, America/Curacao, America/Danmarkshavn, America/Dawson, America/Dawson_Creek, America/Denver, America/Detroit, America/Dominica, America/Edmonton, America/Eirunepe, America/El_Salvador, America/Ensenada, America/Fort_Nelson, America/Fort_Wayne, America/Fortaleza, America/Glace_Bay, America/Godthab, America/Goose_Bay, America/Grand_Turk, America/Grenada, America/Guadeloupe, America/Guatemala, America/Guayaquil, America/Guyana, America/Halifax, America/Havana, America/Hermosillo, America/Indiana/Indianapolis, America/Indiana/Knox, America/Indiana/Marengo, America/Indiana/Petersburg, America/Indiana/Tell_City, America/Indiana/Vevay, America/Indiana/Vincennes, America/Indiana/Winamac, America/Indianapolis, America/Inuvik, America/Iqaluit, America/Jamaica, America/Jujuy, America/Juneau, America/Kentucky/Louisville, America/Kentucky/Monticello, America/Knox_IN, America/Kralendijk, America/La_Paz, America/Lima, America/Los_Angeles, America/Louisville, America/Lower_Princes, America/Maceio, America/Managua, America/Manaus, America/Marigot, America/Martinique, America/Matamoros, America/Mazatlan, America/Mendoza, America/Menominee, America/Merida, America/Metlakatla, America/Mexico_City, America/Miquelon, America/Moncton, America/Monterrey, America/Montevideo, America/Montreal, America/Montserrat, America/Nassau, America/New_York, America/Nipigon, America/Nome, America/Noronha, America/North_Dakota/Beulah, America/North_Dakota/Center, America/North_Dakota/New_Salem, America/Nuuk, America/Ojinaga, America/Panama, America/Pangnirtung, America/Paramaribo, America/Phoenix, America/Port-au-Prince, America/Port_of_Spain, America/Porto_Acre, America/Porto_Velho, America/Puerto_Rico, America/Punta_Arenas, America/Rainy_River, America/Rankin_Inlet, America/Recife, America/Regina, America/Resolute, America/Rio_Branco, America/Rosario, America/Santa_Isabel, America/Santarem, America/Santiago, America/Santo_Domingo, America/Sao_Paulo, America/Scoresbysund, America/Shiprock, America/Sitka, America/St_Barthelemy, America/St_Johns, America/St_Kitts, America/St_Lucia, America/St_Thomas, America/St_Vincent, America/Swift_Current, America/Tegucigalpa, America/Thule, America/Thunder_Bay, America/Tijuana, America/Toronto, America/Tortola, America/Vancouver, America/Virgin, America/Whitehorse, America/Winnipeg, America/Yakutat, America/Yellowknife, Antarctica/Casey, Antarctica/Davis, Antarctica/DumontDUrville, Antarctica/Macquarie, Antarctica/Mawson, Antarctica/McMurdo, Antarctica/Palmer, Antarctica/Rothera, Antarctica/South_Pole, Antarctica/Syowa, Antarctica/Troll, Antarctica/Vostok, Arctic/Longyearbyen, Asia/Aden, Asia/Almaty, Asia/Amman, Asia/Anadyr, Asia/Aqtau, Asia/Aqtobe, Asia/Ashgabat, Asia/Ashkhabad, Asia/Atyrau, Asia/Baghdad, Asia/Bahrain, Asia/Baku, Asia/Bangkok, Asia/Barnaul, Asia/Beirut, Asia/Bishkek, Asia/Brunei, Asia/Calcutta, Asia/Chita, Asia/Choibalsan, Asia/Chongqing, Asia/Chungking, Asia/Colombo, Asia/Dacca, Asia/Damascus, Asia/Dhaka, Asia/Dili, Asia/Dubai, Asia/Dushanbe, Asia/Famagusta, Asia/Gaza, Asia/Harbin, Asia/Hebron, Asia/Ho_Chi_Minh, Asia/Hong_Kong, Asia/Hovd, Asia/Irkutsk, Asia/Istanbul, Asia/Jakarta, Asia/Jayapura, Asia/Jerusalem, Asia/Kabul, Asia/Kamchatka, Asia/Karachi, Asia/Kashgar, Asia/Kathmandu, Asia/Katmandu, Asia/Khandyga, Asia/Kolkata, Asia/Krasnoyarsk, Asia/Kuala_Lumpur, Asia/Kuching, Asia/Kuwait, Asia/Macao, Asia/Macau, Asia/Magadan, Asia/Makassar, Asia/Manila, Asia/Muscat, Asia/Nicosia, Asia/Novokuznetsk, Asia/Novosibirsk, Asia/Omsk, Asia/Oral, Asia/Phnom_Penh, Asia/Pontianak, Asia/Pyongyang, Asia/Qatar, Asia/Qostanay, Asia/Qyzylorda, Asia/Rangoon, Asia/Riyadh, Asia/Saigon, Asia/Sakhalin, Asia/Samarkand, Asia/Seoul, Asia/Shanghai, Asia/Singapore, Asia/Srednekolymsk, Asia/Taipei, Asia/Tashkent, Asia/Tbilisi, Asia/Tehran, Asia/Tel_Aviv, Asia/Thimbu, Asia/Thimphu, Asia/Tokyo, Asia/Tomsk, Asia/Ujung_Pandang, Asia/Ulaanbaatar, Asia/Ulan_Bator, Asia/Urumqi, Asia/Ust-Nera, Asia/Vientiane, Asia/Vladivostok, Asia/Yakutsk, Asia/Yangon, Asia/Yekaterinburg, Asia/Yerevan, Atlantic/Azores, Atlantic/Bermuda, Atlantic/Canary, Atlantic/Cape_Verde, Atlantic/Faeroe, Atlantic/Faroe, Atlantic/Jan_Mayen, Atlantic/Madeira, Atlantic/Reykjavik, Atlantic/South_Georgia, Atlantic/St_Helena, Atlantic/Stanley, Australia/ACT, Australia/Adelaide, Australia/Brisbane, Australia/Broken_Hill, Australia/Canberra, Australia/Currie, Australia/Darwin, Australia/Eucla, Australia/Hobart, Australia/LHI, Australia/Lindeman, Australia/Lord_Howe, Australia/Melbourne, Australia/NSW, Australia/North, Australia/Perth, Australia/Queensland, Australia/South, Australia/Sydney, Australia/Tasmania, Australia/Victoria, Australia/West, Australia/Yancowinna, Brazil/Acre, Brazil/DeNoronha, Brazil/East, Brazil/West, CET, CST6CDT, Canada/Atlantic, Canada/Central, Canada/Eastern, Canada/Mountain, Canada/Newfoundland, Canada/Pacific, Canada/Saskatchewan, Canada/Yukon, Chile/Continental, Chile/EasterIsland, Cuba, EET, EST, EST5EDT, Egypt, Eire, Etc/GMT, Etc/GMT+0, Etc/GMT+1, Etc/GMT+10, Etc/GMT+11, Etc/GMT+12, Etc/GMT+2, Etc/GMT+3, Etc/GMT+4, Etc/GMT+5, Etc/GMT+6, Etc/GMT+7, Etc/GMT+8, Etc/GMT+9, Etc/GMT-0, Etc/GMT-1, Etc/GMT-10, Etc/GMT-11, Etc/GMT-12, Etc/GMT-13, Etc/GMT-14, Etc/GMT-2, Etc/GMT-3, Etc/GMT-4, Etc/GMT-5, Etc/GMT-6, Etc/GMT-7, Etc/GMT-8, Etc/GMT-9, Etc/GMT0, Etc/Greenwich, Etc/UCT, Etc/UTC, Etc/Universal, Etc/Zulu, Europe/Amsterdam, Europe/Andorra, Europe/Astrakhan, Europe/Athens, Europe/Belfast, Europe/Belgrade, Europe/Berlin, Europe/Bratislava, Europe/Brussels, Europe/Bucharest, Europe/Budapest, Europe/Busingen, Europe/Chisinau, Europe/Copenhagen, Europe/Dublin, Europe/Gibraltar, Europe/Guernsey, Europe/Helsinki, Europe/Isle_of_Man, Europe/Istanbul, Europe/Jersey, Europe/Kaliningrad, Europe/Kiev, Europe/Kirov, Europe/Kyiv, Europe/Lisbon, Europe/Ljubljana, Europe/London, Europe/Luxembourg, Europe/Madrid, Europe/Malta, Europe/Mariehamn, Europe/Minsk, Europe/Monaco, Europe/Moscow, Europe/Nicosia, Europe/Oslo, Europe/Paris, Europe/Podgorica, Europe/Prague, Europe/Riga, Europe/Rome, Europe/Samara, Europe/San_Marino, Europe/Sarajevo, Europe/Saratov, Europe/Simferopol, Europe/Skopje, Europe/Sofia, Europe/Stockholm, Europe/Tallinn, Europe/Tirane, Europe/Tiraspol, Europe/Ulyanovsk, Europe/Uzhgorod, Europe/Vaduz, Europe/Vatican, Europe/Vienna, Europe/Vilnius, Europe/Volgograd, Europe/Warsaw, Europe/Zagreb, Europe/Zaporozhye, Europe/Zurich, Factory, GB, GB-Eire, GMT, GMT+0, GMT-0, GMT0, Greenwich, HST, Hongkong, Iceland, Indian/Antananarivo, Indian/Chagos, Indian/Christmas, Indian/Cocos, Indian/Comoro, Indian/Kerguelen, Indian/Mahe, Indian/Maldives, Indian/Mauritius, Indian/Mayotte, Indian/Reunion, Iran, Israel, Jamaica, Japan, Kwajalein, Libya, MET, MST, MST7MDT, Mexico/BajaNorte, Mexico/BajaSur, Mexico/General, NZ, NZ-CHAT, Navajo, PRC, PST8PDT, Pacific/Apia, Pacific/Auckland, Pacific/Bougainville, Pacific/Chatham, Pacific/Chuuk, Pacific/Easter, Pacific/Efate, Pacific/Enderbury, Pacific/Fakaofo, Pacific/Fiji, Pacific/Funafuti, Pacific/Galapagos, Pacific/Gambier, Pacific/Guadalcanal, Pacific/Guam, Pacific/Honolulu, Pacific/Johnston, Pacific/Kanton, Pacific/Kiritimati, Pacific/Kosrae, Pacific/Kwajalein, Pacific/Majuro, Pacific/Marquesas, Pacific/Midway, Pacific/Nauru, Pacific/Niue, Pacific/Norfolk, Pacific/Noumea, Pacific/Pago_Pago, Pacific/Palau, Pacific/Pitcairn, Pacific/Pohnpei, Pacific/Ponape, Pacific/Port_Moresby, Pacific/Rarotonga, Pacific/Saipan, Pacific/Samoa, Pacific/Tahiti, Pacific/Tarawa, Pacific/Tongatapu, Pacific/Truk, Pacific/Wake, Pacific/Wallis, Pacific/Yap, Poland, Portugal, ROC, ROK, Singapore, Turkey, UCT, US/Alaska, US/Aleutian, US/Arizona, US/Central, US/East-Indiana, US/Eastern, US/Hawaii, US/Indiana-Starke, US/Michigan, US/Mountain, US/Pacific, US/Samoa, UTC, Universal, W-SU, WET, Zulu</details> |
| ntp | bool |  | Time sync: unset leaves it alone, true configures and starts systemd-timesyncd (Arch), false stops and disables it |
| ntp_servers | list of string |  | NTP: servers to ask (they come after per-interface servers; the stock servers stay as fallback) (needs ntp: true) |
| ntp_fallback_servers | list of string |  | FallbackNTP: servers used only when no other server is known (replaces timesyncd's built-in list) (needs ntp: true) |
| root_distance_max_sec | string |  | RootDistanceMaxSec: largest acceptable distance to the reference clock (default 5s) (needs ntp: true) |
| poll_interval_min_sec | string |  | PollIntervalMinSec: shortest time between polls (default 32s, at least 16s) (needs ntp: true) |
| poll_interval_max_sec | string |  | PollIntervalMaxSec: longest time between polls (default 34min 8s, larger than the minimum) (needs ntp: true) |
| connection_retry_sec | string |  | ConnectionRetrySec: wait before trying a new server (default 30s, at least 1s) (needs ntp: true) |
| save_interval_sec | string |  | SaveIntervalSec: how often the clock is saved to disk when nothing syncs (default 60s; infinity = never) (needs ntp: true) |

## users

Users, groups, SSH keys and sudoers rules.

### Examples

**Root's password from a secret (then run `bastet secret set <host> users root_password` and type the password; the secret holds plain text and Bastet hashes it for the host)**

```yaml
users:
  root:
    password: "secret:root_password"
```

**Report accounts nothing manages, except a few**

```yaml
allowed:
  - backup
  - www-data
report_system_accounts: false
```

**A user with an SSH key and passwordless sudo**

```yaml
users:
  alice:
    shell: /bin/bash
    groups:
      - wheel
    keys:
      - ssh-ed25519 AAAAC3Nza...example alice@laptop
    sudo:
      nopasswd: true
```

**A group with exactly these members**

```yaml
groups:
  media:
    gid: 2001
    members:
      - alice
      - jellyfin
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| users | map of object | {"root": {}, "bastet": {"system": true}} | Users by name. root and bastet are always there; entries you list merge over them. To drop a starter entry, delete the whole entry (or write `root: {}`), not just its password line. Setting root's password keeps an already locked root locked; add `locked: false` to unlock it |
| users.<name>.uid | int |  |  |
| users.<name>.group | string |  | Primary group |
| users.<name>.groups | list of string |  | Supplementary groups |
| users.<name>.append | bool |  | Only add groups (default); false = exactly these |
| users.<name>.comment | string |  |  |
| users.<name>.home | string |  |  |
| users.<name>.create_home | bool |  |  |
| users.<name>.move_home | bool |  |  |
| users.<name>.shell | string |  |  |
| users.<name>.system | bool |  |  |
| users.<name>.password_hash | string |  | crypt hash, e.g. from mkpasswd -m sha-512 |
| users.<name>.password | string |  | Plain-text password; Bastet hashes it in the host's own scheme (yescrypt where the host defaults to it, otherwise SHA-512) on the machine running Bastet. Set it with a secret: reference, never write it in the note |
| users.<name>.update_password | string |  |  (one of always, on_create) |
| users.<name>.locked | bool |  |  |
| users.<name>.expires | string |  | YYYY-MM-DD or never |
| users.<name>.max_days | int |  |  |
| users.<name>.min_days | int |  |  |
| users.<name>.warn_days | int |  |  |
| users.<name>.inactive_days | int |  |  |
| users.<name>.non_unique | bool |  |  |
| users.<name>.skeleton | string |  |  |
| users.<name>.keys | list of object |  | Authorized SSH keys; a key line, or a map with options |
| users.<name>.keys[].key | string |  |  |
| users.<name>.keys[].options | string |  | e.g. from="10.0.10.0/24",no-agent-forwarding |
| users.<name>.keys[].path | string |  | Custom authorized_keys path |
| users.<name>.keys[].state | string |  | absent revokes the key (one of present, absent) |
| users.<name>.sudo | object |  | A sudoers rule for this user (/etc/sudoers.d/<user>) |
| users.<name>.sudo.commands | list of string |  |  |
| users.<name>.sudo.runas | string |  |  |
| users.<name>.sudo.hosts | string |  |  |
| users.<name>.sudo.nopasswd | bool |  |  |
| users.<name>.sudo.setenv | bool |  |  |
| users.<name>.sudo.defaults | list of string |  |  |
| groups | map of object |  | Groups by name |
| groups.<name>.gid | int |  |  |
| groups.<name>.system | bool |  |  |
| groups.<name>.members | list of string |  |  |
| groups.<name>.append_members | bool |  | Only add members; default sets exactly these |
| sudoers | map of object |  | Sudoers files by name (/etc/sudoers.d/<name>) |
| sudoers.<name>.rules | list of string |  | Raw sudoers lines |
| sudoers.<name>.user | string |  |  |
| sudoers.<name>.group | string |  |  |
| sudoers.<name>.commands | list of string |  |  |
| sudoers.<name>.runas | string |  |  |
| sudoers.<name>.hosts | string |  |  |
| sudoers.<name>.nopasswd | bool |  |  |
| sudoers.<name>.setenv | bool |  |  |
| sudoers.<name>.defaults | list of string |  |  |
| allowed | list of string |  | Account names that are fine without a role; they are left out of the report of accounts no role manages |
| report_unaccounted | bool | true | Report accounts on the host that no role manages or allows (never changes or removes them) |
| report_system_accounts | bool | true | Include system accounts such as nobody and systemd-* in that report on purpose (root and bastet are managed by default, so they are never listed); false lists only accounts in the login.defs UID_MIN to UID_MAX range (the first real run shows how noisy this is and decides whether the default changes) |
