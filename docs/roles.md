# Roles

Every role Bastet ships. Put values in a role file's properties (`_roles/lab/<role>.md`, `_roles/groups/<group>/<role>.md` or `_roles/hosts/<host>/<role>.md`), or run `bastet add role`.

| Role | What it does |
|---|---|
| [apt](#apt) | apt's own settings, written to /etc/apt/apt.conf.d/90-bastet (Debian-based hosts; aim it at `debian`) |
| [base](#base) | The basics every host gets: admin tools, and CPU microcode on physical machines |
| [files](#files) | Files, directories, links, and blocks or lines inside other files |
| [harden](#harden) | Security knobs and reports |
| [packages](#packages) | Packages for apt, pacman, dnf, zypper and apk |
| [pacman](#pacman) | pacman's own settings: every [options] setting in /etc/pacman.conf (Arch-based hosts; aim it at `arch`) |
| [ssh](#ssh) | OpenSSH server settings: every sshd_config keyword, plus Match blocks |
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
| tools | list of string | ["vim", "zsh", "git", "htop", "tree", "gdu", "wget", "less"] | Admin tools to install; setting this replaces the default list (use extra_tools to add) |
| extra_tools | list of string | [] | More tools on top of `tools` |
| microcode | string | auto | auto: install CPU microcode on physical hosts (by host type; Intel or AMD from the gathered CPU), never on VMs or containers. Debian needs the non-free-firmware component. (one of auto, never) |

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
| fail2ban_ignoreip | list of string | ["127.0.0.1/8", "::1"] | Never ban these addresses/networks (add your LAN to avoid locking yourself out) |
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

Packages for apt, pacman, dnf, zypper and apk.

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

**Remove a package**

```yaml
remove:
  - nano
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
| updates | string | manual | manual: check reports pending updates, apply installs them only with --updates. auto: apply installs them. security: apply installs security updates (apt, dnf, zypper) (one of manual, auto, security) |
| aur_user | string | bastet-aur | Arch only: the user AUR packages are built as (created when needed). It may run pacman through sudo, so treat it as root-equivalent |
| aur_helper | string | yay-bin | Arch only: the AUR package that provides yay, installed only on hosts that list AUR packages |
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
| repositories | list of object |  | Extra pacman repositories, one marked block each at the end of /etc/pacman.conf, written before packages are installed |
| repositories[].name | string |  | Repository name, letters, digits and . _ + - |
| repositories[].servers | list of string |  |  |
| repositories[].include | string |  | A mirror list file, e.g. /etc/pacman.d/mirrorlist |
| repositories[].sig_level | string |  | e.g. Required, Optional or Never |
| repositories[].usage | string |  |  |
| repositories[].enabled | bool |  | false comments the whole block out |

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

The time zone (every system) and, on Arch, time sync with systemd-timesyncd: servers and poll settings go in a drop-in at /etc/systemd/timesyncd.conf.d/bastet.conf. Unset = leave things as they are.

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
