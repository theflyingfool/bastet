# Roles

Every role Bastet ships. Put values in a role file's properties (`_roles/lab/<role>.md`, `_roles/groups/<group>/<role>.md` or `_roles/hosts/<host>/<role>.md`), or run `bastet add role`.

| Role | What it does |
|---|---|
| [base](#base) | The basics every host gets: admin tools, and CPU microcode on physical machines |
| [files](#files) | Files, directories, links, and blocks or lines inside other files |
| [harden](#harden) | Security knobs and reports |
| [packages](#packages) | Packages and package repositories for apt, pacman, dnf, zypper and apk |
| [pacman](#pacman) | pacman's own settings: every [options] setting in /etc/pacman.conf (Arch-based hosts; aim it at `arch`) |
| [proxmox](#proxmox) | A Proxmox VE node's own setup: the PVE and Debian repositories, the subscription notice, Proxmox tools |
| [ssh](#ssh) | OpenSSH server settings: every sshd_config keyword, plus Match blocks |
| [systemd](#systemd) | Settings systemd owns: time and time sync, hostname, locale, and services with their drop-ins |
| [users](#users) | Users, groups, SSH keys and sudoers rules |

## base

The basics every host gets: admin tools, and CPU microcode on physical machines.

### Examples

**Everywhere (put in _roles/lab/base.md)**

```yaml
extra_tools:
  - jq
```

**A machine that shouldn't get microcode**

```yaml
microcode: never
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| tools | list of string | ['vim', 'zsh', 'git', 'htop', 'tree', 'gdu', 'wget', 'less'] | Admin tools to install; setting this replaces the default list (use extra_tools to add) |
| extra_tools | list of string | [] | More tools on top of `tools` |
| microcode | string | auto | auto: install CPU microcode on physical hosts (by host type; Intel or AMD from the gathered CPU), never on VMs or containers. Debian needs the non-free-firmware component. (one of auto, never) |

## files

Files, directories, links, and blocks or lines inside other files.

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

## harden

Security knobs and reports. Reports only read (vulnerable packages, service exposure, listening ports, AppArmor; lynis when on) and land in each host's security note. Changes are mostly off by default: fail2ban, lynis, kernel modules, core dumps, sudo defaults. A small safe sysctl set is on (not in containers).

### Examples

**Everywhere, reports plus fail2ban (put in _roles/lab/harden.md)**

```yaml
fail2ban: true
fail2ban_ignoreip: ["127.0.0.1/8", "::1", "10.10.0.0/24"]
```

**Audit with lynis on one host**

```yaml
lynis: true
```

**Stricter (try on one machine first)**

```yaml
core_dumps: "off"
block_modules: [usb-storage, dccp, sctp, rds, tipc]
sudo_defaults: [use_pty, "logfile=/var/log/sudo.log"]
sysctl:
  kernel.yama.ptrace_scope: "1"
  kernel.unprivileged_bpf_disabled: "1"
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| fail2ban | bool | false | Install fail2ban with an sshd jail (ports follow the ssh role) |
| fail2ban_bantime | string | 1h | How long a ban lasts |
| fail2ban_findtime | string | 10m | Window for counting failures |
| fail2ban_maxretry | int | 5 | Failures before a ban |
| fail2ban_ignoreip | list of string | ['127.0.0.1/8', '::1'] | Never ban these addresses/networks (add your LAN to avoid locking yourself out) |
| fail2ban_backend | string | systemd | Where fail2ban reads logs (systemd journal; Arch and Debian 12+ have no auth.log) |
| fail2ban_jails | map of map | {} | More jails: name → settings, written as-is |
| fail2ban_sandbox | bool | true | Run fail2ban sandboxed (systemd drop-in); turn off if a jail needs more access |
| lynis | bool | false | Install lynis; apply runs an audit (1–3 minutes) and the host's security note shows the result |
| lynis_timer | bool | false | Leave the lynis package's own timer alone (Debian enables a daily one); off = Bastet turns it off |
| vulnerable_packages | bool | true | Report installed packages with known vulnerabilities (arch-audit on Arch, debsecan on Debian/Proxmox) |
| service_exposure | bool | true | Report systemd-analyze security for every service |
| exposure_target | number | 5.0 | Services Bastet's roles run should score at or under this (0 locked down, 10 exposed) |
| listening_ports | bool | true | Report what listens on the network (ss) and what no role accounts for |
| allowed_ports | list of string | [] | Listeners that are fine: proto/port (tcp/8006) or a process name |
| apparmor_status | bool | true | Report whether AppArmor is on, and its profiles |
| sysctl_defaults | bool | true | A safe kernel set: kptr/dmesg restrict, protected links/fifos/regular, SYN cookies, ignore ICMP redirects (not in containers) |
| sysctl | map of string | {} | More kernel settings (key → value); these win over the defaults |
| block_modules | list of string | [] | Kernel modules that may never load (e.g. usb-storage, dccp, sctp, rds, tipc) |
| core_dumps | string | keep | off: no core dumps (they can hold secrets from memory) (one of keep, off) |
| sudo_defaults | list of string | [] | sudo Defaults lines (e.g. use_pty, logfile=/var/log/sudo.log, timestamp_timeout=5) |

## packages

Packages and package repositories for apt, pacman, dnf, zypper and apk.

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

**An AUR package (Arch; sets up yay on this host only)**

```yaml
install:
  - name: visual-studio-code-bin
    aur: true
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

**Remove a package, add a repository**

```yaml
remove:
  - nano
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
| refresh | bool | true | Refresh the package index before installing (no effect on pacman) |
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
| install[].aur | bool |  | Arch only: build this package from the AUR (with yay, as the aur_user) |
| remove | list of object |  | Packages to remove |
| remove[].name | string |  |  |
| remove[].purge | bool |  | Also remove config (apt purge, pacman -Rns, apk --purge) |
| remove[].manager | string |  | Fail unless the host uses this manager (one of apt-get, pacman, dnf, zypper, apk) |
| remove[].dpkg_options | list of string |  |  |
| remove[].allow_change_held | bool |  |  |
| remove[].extra_args | list of string |  |  |
| repositories | list of object |  | Package repositories, written in the host's own format |
| repositories[].name | string |  |  |
| repositories[].uris | list of string |  |  |
| repositories[].suites | list of string |  | apt only |
| repositories[].components | list of string |  | apt only |
| repositories[].types | list of string |  | apt only (deb, deb-src) |
| repositories[].architectures | list of string |  | apt only |
| repositories[].key | string |  | Public key text (armored/PEM) |
| repositories[].key_name | string |  | apk only: key file name in /etc/apk/keys |
| repositories[].signed_by | string |  | Path or URL of an existing key |
| repositories[].enabled | bool |  |  |
| repositories[].trusted | bool |  |  |
| repositories[].options | map of string |  | Extra fields in the repository's own format |
| updates | string | manual | manual: check reports pending updates, apply installs them only with --updates. auto: apply installs them. security: apply installs security updates (apt, dnf, zypper) (one of manual, auto, security) |
| aur_user | string | bastet-aur | Arch only: the user AUR packages are built as (created when needed). It may run pacman through sudo, so treat it as root-equivalent |
| aur_helper | string | yay-bin | Arch only: the AUR package that provides yay, installed only on hosts that list AUR packages |
| reboot | string | ask | After apply, when the host needs a reboot (new kernel, /run/reboot-required): never = only report it; ask = ask (never under -y); auto = reboot and wait for the host. Bastet never reboots the machine it runs on. (one of never, ask, auto) |
| reboot_timeout | int | 600 | Seconds to wait for the host to come back after a reboot |
| updates_exclude | list of string |  | Never upgrade these (pacman --ignore, dnf --exclude, …) |
| allowed | list of string |  | Packages that are fine without a role (not reported as unaccounted) |
| report_unaccounted | bool | true | Report packages installed outside Bastet (explicitly installed, not in the system set, no role, not allowed) |

## pacman

pacman's own settings: every [options] setting in /etc/pacman.conf (Arch-based hosts; aim it at `arch`). Unset = leave pacman's setting as it is. Repositories belong to the packages role.

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

## proxmox

A Proxmox VE node's own setup: the PVE and Debian repositories, the subscription notice, Proxmox tools. Every proxmox-node gets it from its type.

### Examples

**Use your local Debian mirror and clean up old source files (on one node)**

```yaml
debian_mirror: http://ftp.us.debian.org/debian
stray_sources: remove
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| repository | string | no-subscription | Which PVE repository: no-subscription (pve-no-subscription), enterprise (needs a subscription), test (pvetest) (one of no-subscription, enterprise, test) |
| suite | string |  | Debian codename (trixie for PVE 9); default: from the gathered OS |
| debian_mirror | string | http://deb.debian.org/debian | Debian mirror for the main and -updates suites |
| debian_components | list of string | ['main', 'contrib', 'non-free-firmware'] | Debian components; non-free-firmware carries CPU microcode |
| ceph | string | none | Ceph repository (ceph.sources): none writes it disabled so an enterprise entry can't break apt (one of none, no-subscription, enterprise) |
| ceph_release | string | squid | Ceph release name in the repository path (squid for PVE 9) |
| subscription_notice | string | remove | remove: patch out the 'No valid subscription' notice (re-applied when a Proxmox update restores it) (one of remove, keep) |
| tools | list of string | ['libguestfs-tools'] | Proxmox-side tools to install |
| stray_sources | string | report | Other Debian/Proxmox source files in /etc/apt/sources.list.d (old duplicates): report them, or remove them (one of report, remove) |

## ssh

OpenSSH server settings: every sshd_config keyword, plus Match blocks. Written to /etc/ssh/sshd_config.d/10-bastet.conf, checked with sshd -t, then sshd is reloaded. Unset = leave sshd's own setting alone; nothing is set by default. Settings that would lock Bastet out are refused.

### Examples

**Super hardened (not applied anywhere by default — copy into _roles/lab/ssh.md when ready)**

```yaml
password_authentication: false
kbd_interactive_authentication: false
permit_root_login: "no"
permit_empty_passwords: false
x11_forwarding: false
allow_agent_forwarding: false
allow_tcp_forwarding: "no"
max_auth_tries: 3
login_grace_time: "20"
client_alive_interval: 300
client_alive_count_max: 2
kex_algorithms: [sntrup761x25519-sha512@openssh.com, curve25519-sha256, curve25519-sha256@libssh.org]
ciphers: [chacha20-poly1305@openssh.com, aes256-gcm@openssh.com, aes128-gcm@openssh.com]
macs: [hmac-sha2-512-etm@openssh.com, hmac-sha2-256-etm@openssh.com]
host_key_algorithms: [ssh-ed25519, sk-ssh-ed25519@openssh.com, rsa-sha2-512]
log_level: VERBOSE
```

**Move to port 2222 safely (apply this, then change it to [2222] once 2222 works)**

```yaml
port: [22, 2222]
```

**Allow a forwarding user only from the LAN**

```yaml
match:
  - criteria: "User admin Address 10.10.0.0/24"
    settings:
      allow_tcp_forwarding: "yes"
```

### Options

| Option | Type | Default | Description |
|---|---|---|---|
| authorized_keys_file | list of string |  | AuthorizedKeysFile |
| authorized_principals_file | string |  | AuthorizedPrincipalsFile: principals allowed per user (with certificates) |
| chroot_directory | string |  | ChrootDirectory |
| host_certificate | list of string |  | HostCertificate: host certificates signed by your CA |
| host_key | list of string |  | HostKey |
| host_key_agent | string |  | HostKeyAgent |
| moduli_file | string |  | ModuliFile |
| pid_file | string |  | PidFile |
| revoked_keys | string |  | RevokedKeys |
| trusted_user_ca_keys | string |  | TrustedUserCAKeys: CA keys trusted to sign user certificates |
| security_key_provider | string |  | SecurityKeyProvider |
| x_auth_location | string |  | XAuthLocation |
| sshd_session_path | string |  | SshdSessionPath |
| sshd_auth_path | string |  | SshdAuthPath |
| port | list of int |  | Port: ports to listen on; Bastet tries them in order, then 22 |
| listen_address | list of string |  | ListenAddress |
| address_family | string |  | AddressFamily |
| rdomain | string |  | RDomain |
| ipqos | string |  | IPQoS |
| tcp_keep_alive | bool |  | TCPKeepAlive |
| use_dns | bool |  | UseDNS |
| client_alive_interval | int |  | ClientAliveInterval |
| client_alive_count_max | int |  | ClientAliveCountMax |
| channel_timeout | list of string |  | ChannelTimeout |
| unused_connection_timeout | string |  | UnusedConnectionTimeout |
| allow_users | list of string |  | AllowUsers: only these users may log in (must include bastet) |
| allow_groups | list of string |  | AllowGroups: only these groups may log in (must include bastet, or list bastet in allow_users) |
| deny_users | list of string |  | DenyUsers |
| deny_groups | list of string |  | DenyGroups |
| permit_root_login | string |  | PermitRootLogin: yes, prohibit-password, forced-commands-only or no |
| permit_empty_passwords | bool |  | PermitEmptyPasswords |
| permit_tty | bool |  | PermitTTY |
| permit_user_environment | string |  | PermitUserEnvironment |
| permit_user_rc | bool |  | PermitUserRC |
| strict_modes | bool |  | StrictModes |
| max_auth_tries | int |  | MaxAuthTries |
| max_sessions | int |  | MaxSessions |
| max_startups | string |  | MaxStartups |
| login_grace_time | string |  | LoginGraceTime |
| per_source_max_startups | string |  | PerSourceMaxStartups |
| per_source_net_block_size | string |  | PerSourceNetBlockSize |
| per_source_penalties | list of string |  | PerSourcePenalties |
| per_source_penalty_exempt_list | list of string |  | PerSourcePenaltyExemptList |
| refuse_connection | bool |  | RefuseConnection |
| force_command | string |  | ForceCommand |
| banner | string |  | Banner |
| print_motd | bool |  | PrintMotd |
| print_last_log | bool |  | PrintLastLog |
| version_addendum | string |  | VersionAddendum |
| pubkey_authentication | bool |  | PubkeyAuthentication: key logins (Bastet needs these) |
| password_authentication | bool |  | PasswordAuthentication: password logins |
| kbd_interactive_authentication | bool |  | KbdInteractiveAuthentication: keyboard-interactive (PAM) logins |
| authentication_methods | string |  | AuthenticationMethods |
| use_pam | bool |  | UsePAM |
| hostbased_authentication | bool |  | HostbasedAuthentication |
| hostbased_uses_name_from_packet_only | bool |  | HostbasedUsesNameFromPacketOnly |
| ignore_rhosts | string |  | IgnoreRhosts |
| ignore_user_known_hosts | bool |  | IgnoreUserKnownHosts |
| gssapi_authentication | bool |  | GSSAPIAuthentication |
| gssapi_cleanup_credentials | bool |  | GSSAPICleanupCredentials |
| gssapi_strict_acceptor_check | bool |  | GSSAPIStrictAcceptorCheck |
| kerberos_authentication | bool |  | KerberosAuthentication |
| kerberos_get_afs_token | bool |  | KerberosGetAFSToken |
| kerberos_or_local_passwd | bool |  | KerberosOrLocalPasswd |
| kerberos_ticket_cleanup | bool |  | KerberosTicketCleanup |
| authorized_keys_command | string |  | AuthorizedKeysCommand |
| authorized_keys_command_user | string |  | AuthorizedKeysCommandUser |
| authorized_principals_command | string |  | AuthorizedPrincipalsCommand |
| authorized_principals_command_user | string |  | AuthorizedPrincipalsCommandUser |
| expose_auth_info | bool |  | ExposeAuthInfo |
| pubkey_auth_options | list of string |  | PubkeyAuthOptions |
| required_rsa_size | int |  | RequiredRSASize |
| ciphers | list of string |  | Ciphers |
| macs | list of string |  | MACs |
| kex_algorithms | list of string |  | KexAlgorithms |
| host_key_algorithms | list of string |  | HostKeyAlgorithms |
| pubkey_accepted_algorithms | list of string |  | PubkeyAcceptedAlgorithms |
| hostbased_accepted_algorithms | list of string |  | HostbasedAcceptedAlgorithms |
| ca_signature_algorithms | list of string |  | CASignatureAlgorithms |
| fingerprint_hash | string |  | FingerprintHash |
| rekey_limit | string |  | RekeyLimit |
| allow_agent_forwarding | bool |  | AllowAgentForwarding |
| allow_tcp_forwarding | string |  | AllowTcpForwarding |
| allow_stream_local_forwarding | string |  | AllowStreamLocalForwarding |
| disable_forwarding | bool |  | DisableForwarding |
| gateway_ports | string |  | GatewayPorts |
| permit_listen | list of string |  | PermitListen |
| permit_open | list of string |  | PermitOpen |
| permit_tunnel | string |  | PermitTunnel |
| stream_local_bind_mask | string |  | StreamLocalBindMask |
| stream_local_bind_unlink | bool |  | StreamLocalBindUnlink |
| x11_forwarding | bool |  | X11Forwarding |
| x11_display_offset | int |  | X11DisplayOffset |
| x11_use_localhost | bool |  | X11UseLocalhost |
| accept_env | list of string |  | AcceptEnv |
| set_env | list of string |  | SetEnv |
| subsystem | list of string |  | Subsystem |
| compression | string |  | Compression |
| log_level | string |  | LogLevel |
| log_verbose | list of string |  | LogVerbose |
| syslog_facility | string |  | SyslogFacility |
| include | list of string |  | Include |
| match | list of object |  | Match blocks: settings for some users or addresses only (written last, then Match all) |
| match[].criteria | string |  | e.g. User admin Address 10.10.0.0/24 |
| match[].settings | map of any |  | ssh role option names and values |

## systemd

Settings systemd owns: time and time sync, hostname, locale, and services with their drop-ins.

### Examples

**Lab-wide time, synced with timesyncd**

```yaml
timezone: America/Chicago
ntp: true
ntp_service: timesyncd
ntp_servers:
  - 10.0.10.1
```

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
| timezone | string |  | IANA timezone, e.g. America/Chicago |
| ntp | bool |  | Keep the clock synced (on LXC the node does this, so it's left alone) |
| ntp_service | string | keep | keep: leave the service alone and let timedatectl turn sync on or off. timesyncd/chrony: install, enable and configure that one, and stop the other (one of keep, timesyncd, chrony) |
| ntp_servers | list of string |  | NTP servers (timesyncd NTP=, chrony server lines); needs timesyncd or chrony |
| fallback_ntp_servers | list of string |  | timesyncd FallbackNTP= (timesyncd only) |
| rtc_local | bool | false | Hardware clock in local time; only for Windows dual-boot |
| manage_hostname | bool | true | Set the hostname from the host file's hostname: (or the note name) |
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

## users

Users, groups, SSH keys and sudoers rules.

### Examples

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
| users | map of object |  | Users by name |
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
