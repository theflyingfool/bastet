"""Roles built on the building blocks: base, pacman and proxmox."""

from __future__ import annotations

import fnmatch
import re

from bastet.core.errors import BastetError
from bastet.core.osinfo import ARCH_LIKE
from bastet.engine.command import Command
from bastet.engine.files import File, Line, Symlink
from bastet.engine.packages import Package, Repository, StraySources
from bastet.engine.run import Batch
from bastet.engine.model import Trigger
from bastet.engine.security import AppArmorStatus, ListeningPorts, LynisReport, ServiceExposure, VulnerablePackages
from bastet.engine.systemd import Unit, drop_in, reload, restart
from bastet.engine.users import sudoer

MICROCODE = {("arch", "intel"): "intel-ucode", ("arch", "amd"): "amd-ucode",
             ("debian", "intel"): "intel-microcode", ("debian", "amd"): "amd64-microcode"}


def _family(host) -> str | None:
    if host.os_id in ARCH_LIKE:
        return "arch"
    if host.debian_like:
        return "debian"
    return None


def _vendor(cpu: object) -> str | None:
    text = str(cpu or "").lower()
    return "intel" if "intel" in text else "amd" if "amd" in text else None


def base(v: dict, host) -> list[Batch]:
    names = list(dict.fromkeys([*(v.get("tools") or []), *(v.get("extra_tools") or [])]))
    res = [Package(name=n) for n in names]
    if v.get("microcode") == "auto" and host.physical:
        if not host.data.get("cpu"):
            raise BastetError("base.microcode: auto needs the CPU vendor; run bastet run -g on this host first")
        package = MICROCODE.get((_family(host), _vendor(host.data.get("cpu"))))
        if package is None:
            raise BastetError(f"base.microcode: no microcode package known for {host.data.get('os')} "
                              f"on {host.data.get('cpu')}; set microcode: never")
        res.append(Package(name=package))
    return [Batch("base", res)]


PACMAN_CONF = "/etc/pacman.conf"
OPTIONS = r"^\[options\]\s*$"
# role option -> (pacman.conf directive, kind): flag = bare word, value = "Name = v", list = "Name = a b c"
PACMAN_SETTINGS = {
    "root_dir": ("RootDir", "value"), "db_path": ("DBPath", "value"), "cache_dir": ("CacheDir", "list"),
    "hook_dir": ("HookDir", "list"), "gpg_dir": ("GPGDir", "value"), "log_file": ("LogFile", "value"),
    "hold_pkg": ("HoldPkg", "list"), "ignore_pkg": ("IgnorePkg", "list"), "ignore_group": ("IgnoreGroup", "list"),
    "no_upgrade": ("NoUpgrade", "list"), "no_extract": ("NoExtract", "list"), "architecture": ("Architecture", "value"),
    "xfer_command": ("XferCommand", "value"), "parallel_downloads": ("ParallelDownloads", "value"),
    "disable_download_timeout": ("DisableDownloadTimeout", "flag"), "download_user": ("DownloadUser", "value"),
    "disable_sandbox": ("DisableSandbox", "flag"), "clean_method": ("CleanMethod", "list"),
    "sig_level": ("SigLevel", "value"), "local_file_sig_level": ("LocalFileSigLevel", "value"),
    "remote_file_sig_level": ("RemoteFileSigLevel", "value"), "color": ("Color", "flag"),
    "candy": ("ILoveCandy", "flag"), "no_progress_bar": ("NoProgressBar", "flag"),
    "verbose_pkg_lists": ("VerbosePkgLists", "flag"), "check_space": ("CheckSpace", "flag"),
    "use_syslog": ("UseSyslog", "flag"),
}


def _directive(name: str, kind: str, value) -> Line:
    """One [options] line: written in place of the directive (commented or not), else right under [options]."""
    match = rf"^#?\s*{name}\s*(=.*)?$"
    if kind == "flag":
        line = name if value else f"#{name}"
    elif kind == "list":
        line = f"{name} = {' '.join(str(x) for x in value)}" if value else f"#{name} ="
    else:
        line = f"{name} = {value}"
    return Line(path=PACMAN_CONF, line=line, match=match, after=OPTIONS, unique=True)  # the setting means exactly this


def pacman(v: dict, host) -> list[Batch]:
    if host.os_id not in ARCH_LIKE:
        raise BastetError(f"pacman role: {host.name} isn't Arch-based ({host.data.get('os') or 'OS unknown'}); "
                          "aim it at [[arch]]")
    parallel = v.get("parallel_downloads")
    if parallel is not None and parallel < 1:
        raise BastetError("pacman.parallel_downloads must be 1 or more")
    for knob, (_, kind) in PACMAN_SETTINGS.items():
        if kind == "value" and isinstance(v.get(knob), str) and ("\n" in v[knob] or not v[knob].strip()):
            raise BastetError(f"pacman.{knob}: needs a single non-empty line")
    lines = [_directive(name, kind, v[knob]) for knob, (name, kind) in PACMAN_SETTINGS.items() if v.get(knob) is not None]
    return [Batch("pacman", lines)]

DEBIAN_KEY = "/usr/share/keyrings/debian-archive-keyring.gpg"
PVE_KEY = "/usr/share/keyrings/proxmox-archive-keyring.gpg"
PVE_JS = "/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js"
NAG = "res.data.status.toLowerCase() !== 'active'"
NAG_SED = NAG.replace(".", "\\.")  # sed basic regex: ( ) are literal; only the dots need escaping


def _suite(v: dict, host) -> str:
    if v.get("suite"):
        return str(v["suite"])
    m = re.search(r"\(([a-z]+)\)", str(host.data.get("os") or ""))
    if not m:
        raise BastetError(f"proxmox.suite: can't tell the Debian codename from '{host.data.get('os')}'; "
                          "set suite (e.g. trixie) or run bastet run -g")
    return m.group(1)


def proxmox(v: dict, host) -> list[Batch]:
    s = _suite(v, host)
    comps = tuple(v.get("debian_components") or ())
    which = v.get("repository") or "no-subscription"
    res: list = [
        Repository(name="debian", uris=(v["debian_mirror"],), suites=(s, f"{s}-updates"), components=comps,
                   signed_by=DEBIAN_KEY),
        Repository(name="debian-security", uris=("http://security.debian.org/debian-security",),
                   suites=(f"{s}-security",), components=comps, signed_by=DEBIAN_KEY),
        Repository(name="proxmox", uris=("http://download.proxmox.com/debian/pve",), suites=(s,),
                   components=("pvetest" if which == "test" else "pve-no-subscription",), signed_by=PVE_KEY,
                   enabled=which != "enterprise"),
        Repository(name="pve-enterprise", uris=("https://enterprise.proxmox.com/debian/pve",), suites=(s,),
                   components=("pve-enterprise",), signed_by=PVE_KEY, enabled=which == "enterprise"),
        _ceph(v, s),
        StraySources(keep=("debian", "debian-security", "proxmox", "pve-enterprise", "ceph"),
                     remove=v.get("stray_sources") == "remove"),
    ]
    res += [Package(name=t) for t in v.get("tools") or []]
    if v.get("subscription_notice") == "remove":  # last: a failure here mustn't stop the tools
        res.append(Command(
            name="proxmox subscription notice",
            unless=f"grep -q BASTET-NOTICE-OFF {PVE_JS}",
            run=(f"grep -qF \"{NAG}\" {PVE_JS} || {{ echo 'pattern not found; Proxmox changed proxmoxlib.js, or another "
                 f"tool already patched it (apt reinstall proxmox-widget-toolkit, then apply again)' >&2; exit 1; }}; "
                 f"sed -i.bastet-bak \"s/{NAG_SED}/false \\/* BASTET-NOTICE-OFF *\\//g\" {PVE_JS} && "
                 "systemctl restart pveproxy.service"),
        ))
    return [Batch("proxmox", res)]


def _ceph(v: dict, suite: str) -> Repository:
    """ceph.sources: disabled unless asked for, so an enterprise Ceph entry can't break apt on a no-subscription node."""
    which, release = v.get("ceph") or "none", v.get("ceph_release") or "squid"
    if which == "no-subscription":
        return Repository(name="ceph", uris=(f"http://download.proxmox.com/debian/ceph-{release}",), suites=(suite,),
                          components=("no-subscription",), signed_by=PVE_KEY)
    return Repository(name="ceph", uris=(f"https://enterprise.proxmox.com/debian/ceph-{release}",), suites=(suite,),
                      components=("enterprise",), signed_by=PVE_KEY, enabled=which == "enterprise")


# --- ssh -------------------------------------------------------------------------------------------------------------

# Every sshd_config(5) keyword, by kind: yesno = bool → yes/no; value = as written; words = list joined by spaces;
# commas = list joined by commas; repeat = one line per item.
_SSHD = """
AuthorizedKeysFile:words AuthorizedPrincipalsFile:value ChrootDirectory:value HostCertificate:repeat HostKey:repeat
HostKeyAgent:value ModuliFile:value PidFile:value RevokedKeys:value TrustedUserCAKeys:value SecurityKeyProvider:value
XAuthLocation:value SshdSessionPath:value SshdAuthPath:value
Port:repeat ListenAddress:repeat AddressFamily:value RDomain:value IPQoS:value TCPKeepAlive:yesno UseDNS:yesno
ClientAliveInterval:value ClientAliveCountMax:value ChannelTimeout:words UnusedConnectionTimeout:value
AllowUsers:words AllowGroups:words DenyUsers:words DenyGroups:words PermitRootLogin:value PermitEmptyPasswords:yesno
PermitTTY:yesno PermitUserEnvironment:value PermitUserRC:yesno StrictModes:yesno MaxAuthTries:value MaxSessions:value
MaxStartups:value LoginGraceTime:value PerSourceMaxStartups:value PerSourceNetBlockSize:value PerSourcePenalties:words
PerSourcePenaltyExemptList:commas RefuseConnection:yesno ForceCommand:value Banner:value PrintMotd:yesno
PrintLastLog:yesno VersionAddendum:value
PubkeyAuthentication:yesno PasswordAuthentication:yesno KbdInteractiveAuthentication:yesno AuthenticationMethods:value
UsePAM:yesno HostbasedAuthentication:yesno HostbasedUsesNameFromPacketOnly:yesno IgnoreRhosts:value
IgnoreUserKnownHosts:yesno GSSAPIAuthentication:yesno GSSAPICleanupCredentials:yesno GSSAPIStrictAcceptorCheck:yesno
KerberosAuthentication:yesno KerberosGetAFSToken:yesno KerberosOrLocalPasswd:yesno KerberosTicketCleanup:yesno
AuthorizedKeysCommand:value AuthorizedKeysCommandUser:value AuthorizedPrincipalsCommand:value
AuthorizedPrincipalsCommandUser:value ExposeAuthInfo:yesno PubkeyAuthOptions:words RequiredRSASize:value
Ciphers:commas MACs:commas KexAlgorithms:commas HostKeyAlgorithms:commas PubkeyAcceptedAlgorithms:commas
HostbasedAcceptedAlgorithms:commas CASignatureAlgorithms:commas FingerprintHash:value RekeyLimit:value
AllowAgentForwarding:yesno AllowTcpForwarding:value AllowStreamLocalForwarding:value DisableForwarding:yesno
GatewayPorts:value PermitListen:words PermitOpen:words PermitTunnel:value StreamLocalBindMask:value
StreamLocalBindUnlink:yesno X11Forwarding:yesno X11DisplayOffset:value X11UseLocalhost:yesno
AcceptEnv:words SetEnv:words Subsystem:repeat Compression:value LogLevel:value LogVerbose:commas SyslogFacility:value
Include:repeat
"""
_SSHD_NAMES = {"MACs": "macs", "IPQoS": "ipqos", "RDomain": "rdomain"}
SSHD_INTS = {"client_alive_interval", "client_alive_count_max", "max_auth_tries", "max_sessions", "x11_display_offset",
             "required_rsa_size"}


def _snake(keyword: str) -> str:
    if keyword in _SSHD_NAMES:
        return _SSHD_NAMES[keyword]
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", keyword)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", s)
    return s.lower()


SSHD_KEYWORDS: dict[str, tuple[str, str]] = {
    _snake(kw): (kw, kind) for kw, kind in (item.split(":") for item in _SSHD.split())
}
SSHD = "/usr/sbin/sshd"
SSHD_DROP_IN = "/etc/ssh/sshd_config.d/10-bastet.conf"
SSHD_INCLUDE = "Include /etc/ssh/sshd_config.d/*.conf"
BASTET = "bastet"


def _sshd_line(keyword: str, kind: str, value) -> list[str]:
    if kind == "yesno":
        return [f"{keyword} {'yes' if value else 'no'}"]
    if kind == "repeat":
        return [f"{keyword} {v}" for v in value]
    if kind == "words":
        return [f"{keyword} {' '.join(str(v) for v in value)}"]
    if kind == "commas":
        return [f"{keyword} {','.join(str(v) for v in value)}"]
    return [f"{keyword} {value}"]


def _sshd_block(settings: dict, where: str) -> list[str]:
    lines = []
    for knob, value in settings.items():
        if knob not in SSHD_KEYWORDS:
            raise BastetError(f"{where}: unknown setting {knob!r} (use the ssh role's option names, e.g. x11_forwarding)")
        if value is None:
            continue
        keyword, kind = SSHD_KEYWORDS[knob]
        if kind in ("words", "commas", "repeat") and not isinstance(value, list):
            value = [value]
        lines += _sshd_line(keyword, kind, value)
    return lines


def _names(value) -> list[str]:
    return [str(v) for v in (value if isinstance(value, list) else [value])]


def _matches_bastet(pattern: str) -> bool:
    """An AllowUsers/DenyUsers-style entry (user or user@host, with * and ?) that can match the bastet user."""
    user = pattern.lstrip("!").split("@", 1)[0]
    return not pattern.startswith("!") and fnmatch.fnmatchcase(BASTET, user)


def _excludes_bastet(criteria: str) -> bool:
    """A Match whose User criterion lists users, none of them bastet (and no wildcard), can't touch Bastet's login."""
    words = criteria.split()
    for i, w in enumerate(words[:-1]):
        if w.lower() == "user":
            users = words[i + 1].split(",")
            return all(u.lstrip("!") != BASTET and "*" not in u and "?" not in u for u in users)
    return False


def _publickey_alternative(methods: str) -> bool:
    """AuthenticationMethods: space-separated alternatives, each a comma list that must ALL succeed."""
    if methods.strip() == "any":
        return True
    return any(all(part.split(":")[0] == "publickey" for part in alt.split(",")) for alt in methods.split())


def _keeps_ed25519(algorithms: list[str]) -> bool:
    text = ",".join(algorithms)
    if text.startswith(("+", "^")):
        return True  # adds to (or reorders) the default list, which has ssh-ed25519
    if text.startswith("-"):
        return not any(fnmatch.fnmatchcase("ssh-ed25519", a) for a in text[1:].split(","))
    return any(fnmatch.fnmatchcase("ssh-ed25519", a) for a in text.split(","))


def _guard_ssh(settings: dict, where: str, *, criteria: str | None = None, host=None, ports=(22,)) -> None:
    def stop(why: str):
        raise BastetError(f"{where}: {why} would lock Bastet out of this host")

    if criteria is not None and _excludes_bastet(criteria):
        return
    if settings.get("pubkey_authentication") is False:
        stop("pubkey_authentication: false")
    methods = settings.get("authentication_methods")
    if methods is not None and not _publickey_alternative(str(methods)):
        stop(f"authentication_methods {methods!r} (Bastet logs in with a key only; one alternative must be publickey alone)")
    allow_users = settings.get("allow_users")
    if allow_users is not None and not any(_matches_bastet(u) for u in _names(allow_users)):
        stop("allow_users without bastet")
    allow_groups = settings.get("allow_groups")
    if allow_groups is not None and not any(fnmatch.fnmatchcase(BASTET, g) for g in _names(allow_groups)):
        stop("allow_groups without the bastet group (sshd checks allow_users and allow_groups separately)")
    if settings.get("deny_users") is not None and any(_matches_bastet(u) for u in _names(settings["deny_users"])):
        stop("deny_users matching bastet")
    if settings.get("deny_groups") is not None and any(
            not g.startswith("!") and fnmatch.fnmatchcase(BASTET, g) for g in _names(settings["deny_groups"])):
        stop("deny_groups matching the bastet group")
    if settings.get("refuse_connection") is True:
        stop("refuse_connection: true")
    if settings.get("max_sessions") is not None and settings["max_sessions"] < 2:
        stop("max_sessions under 2 (Bastet reuses one connection for several sessions)")
    keys = settings.get("authorized_keys_file")
    if keys is not None and not any(str(k).endswith(".ssh/authorized_keys") for k in _names(keys)):
        stop("authorized_keys_file without .ssh/authorized_keys (where Bastet's key is)")
    algorithms = settings.get("pubkey_accepted_algorithms")
    if algorithms is not None and not _keeps_ed25519(_names(algorithms)):
        stop("pubkey_accepted_algorithms without ssh-ed25519 (Bastet's key type)")
    for knob in ("force_command", "chroot_directory"):
        if settings.get(knob) is not None and criteria is None:
            stop(f"{knob} for every user (use a match with User …)")
        if settings.get(knob) is not None:
            stop(f"{knob} in a Match that can reach bastet")
    listen = settings.get("listen_address")
    if listen is not None and criteria is None:
        if host is not None and host.data.get("connection") == "local":
            # a local host is reached at 127.0.0.1 (or its `address:`), never its LAN `ip:`
            reachable = {str(host.data.get("address")).split("/")[0] if host.data.get("address") else "127.0.0.1"}
        else:
            reachable = {str(host.data.get(k)).split("/")[0] for k in ("ip", "address") if host is not None and host.data.get(k)}
        ok = False
        for entry in _names(listen):
            m = re.match(r"^\[?([^\]]+?)\]?(?::(\d+))?(?:\s+rdomain\s+\S+)?$", entry.strip())
            addr, port = (m.group(1), m.group(2)) if m else (entry, None)
            if port is not None and int(port) not in ports:
                stop(f"listen_address {entry!r} on a port that isn't in port")
            if addr in ("0.0.0.0", "::", "*") or addr in reachable:
                ok = True
        if not ok:
            stop("listen_address without a wildcard (0.0.0.0, ::) or the host's own address")


def _typed_settings(settings: dict, where: str) -> dict:
    """Match settings get the same type checks as the global options (the role contract only sees `any`)."""
    from bastet.roles.contract import check_value, load_roles  # lazy: contract loads every role.yml

    options = load_roles()["ssh"].options
    out = {}
    for knob, value in settings.items():
        if knob not in SSHD_KEYWORDS:
            raise BastetError(f"{where}: unknown setting {knob!r} (use the ssh role's option names, e.g. x11_forwarding)")
        out[knob] = check_value(options[knob], value, f"{where}.{knob}")
    return out


def _one_line(value, where: str) -> None:
    for v in _names(value):
        if "\n" in v or "\r" in v:
            raise BastetError(f"{where}: values must be one line")


def ssh(v: dict, host) -> list[Batch]:
    glob = {k: val for k, val in v.items() if k != "match" and val is not None}
    if glob.get("port"):
        glob["port"] = list(dict.fromkeys(glob["port"]))
    for p in glob.get("port") or []:
        if not 1 <= p <= 65535:
            raise BastetError(f"ssh.port: {p} isn't a port (1–65535)")
    for knob, value in glob.items():
        _one_line(value, f"ssh.{knob}")
    ports = tuple(glob.get("port") or (22,))
    _guard_ssh(glob, "ssh", host=host, ports=ports)
    matches = []
    for i, m in enumerate(v.get("match") or []):
        where = f"ssh.match[{i}]"
        _one_line(m["criteria"], f"{where}.criteria")
        settings = _typed_settings(m.get("settings") or {}, where)
        for knob, value in settings.items():
            _one_line(value, f"{where}.{knob}")
        _guard_ssh(settings, where, criteria=str(m["criteria"]), host=host, ports=ports)
        matches.append({"criteria": m["criteria"], "settings": settings})
    if not glob and not matches:
        return []
    body = ["# Managed by Bastet (ssh role)", *_sshd_block(glob, "ssh")]
    for i, m in enumerate(matches):
        body.append(f"Match {m['criteria']}")
        body += [f"    {line}" for line in _sshd_block(m.get("settings") or {}, f"ssh.match[{i}]")]
    if matches:
        body.append("Match all")  # the drop-in is included at the top: end our Matches so sshd_config stays global
    unit = "ssh.service" if host.debian_like else "sshd.service"
    return [Batch("ssh", [
        Command(name="sshd_config includes drop-ins",
                unless="grep -qiE '^[[:space:]]*include[[:space:]]+(/etc/ssh/)?sshd_config\\.d/' /etc/ssh/sshd_config",
                run=(f"{{ echo '{SSHD_INCLUDE}'; cat /etc/ssh/sshd_config; }} > /etc/ssh/sshd_config.bastet && "
                     "cat /etc/ssh/sshd_config.bastet > /etc/ssh/sshd_config && rm -f /etc/ssh/sshd_config.bastet")),
        File(path=SSHD_DROP_IN, content="\n".join(body) + "\n", mode="0644", validate=f"{SSHD} -t -f %s",
             on_change=(Trigger(f"reload {unit}", f"{SSHD} -t && systemctl reload-or-restart {unit}"),)),
    ])]


# --- harden ----------------------------------------------------------------------------------------------------------

SAFE_SYSCTL = {
    "kernel.kptr_restrict": "1", "kernel.dmesg_restrict": "1", "fs.protected_hardlinks": "1",
    "fs.protected_symlinks": "1", "fs.protected_fifos": "1", "fs.protected_regular": "2",
    "net.ipv4.tcp_syncookies": "1", "net.ipv4.conf.all.accept_redirects": "0",
    "net.ipv4.conf.default.accept_redirects": "0", "net.ipv6.conf.all.accept_redirects": "0",
    "net.ipv6.conf.default.accept_redirects": "0",
}
SYSCTL_FILE = "/etc/sysctl.d/90-bastet.conf"
FAIL2BAN_JAIL = "/etc/fail2ban/jail.d/bastet.local"
FAIL2BAN_SANDBOX = """[Service]
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
RuntimeDirectory=fail2ban
RuntimeDirectoryPreserve=yes
ReadWritePaths=/var/lib/fail2ban /var/log
ProtectHome=read-only
ProtectKernelTunables=yes
ProtectControlGroups=yes
ProtectClock=yes
ProtectHostname=yes
RestrictNamespaces=yes
RestrictRealtime=yes
LockPersonality=yes
MemoryDenyWriteExecute=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_RAW CAP_DAC_READ_SEARCH CAP_AUDIT_READ
SystemCallArchitectures=native
"""
_KEY = re.compile(r"^[A-Za-z0-9_.*/-]+$")


def _ini_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value)


def _fail2ban(v: dict, host) -> list:
    ports = ",".join(str(p) for p in host.ssh_ports) if host.ssh_ports else "ssh"
    lines = ["# Managed by Bastet (harden role)", "[DEFAULT]",
             f"bantime = {v['fail2ban_bantime']}", f"findtime = {v['fail2ban_findtime']}",
             f"maxretry = {v['fail2ban_maxretry']}", f"ignoreip = {' '.join(v.get('fail2ban_ignoreip') or [])}",
             f"backend = {v['fail2ban_backend']}", "", "[sshd]", "enabled = true", f"port = {ports}"]
    jails = dict(v.get("fail2ban_jails") or {})
    lines += [f"{k} = {_ini_value(val)}" for k, val in (jails.pop("sshd", None) or {}).items()
              if k not in ("enabled", "port")]  # settings for the built-in sshd jail join its section
    for name, settings in jails.items():
        if not _KEY.match(name):
            raise BastetError(f"harden.fail2ban_jails: {name!r} isn't a jail name")
        lines += ["", f"[{name}]"] + [f"{k} = {_ini_value(val)}" for k, val in (settings or {}).items()]
    unit = "fail2ban.service"
    res: list = [Package(name="fail2ban"),
                 File(path=FAIL2BAN_JAIL, content="\n".join(lines) + "\n", mode="0644", on_change=(restart(unit),))]
    if v.get("fail2ban_sandbox", True):
        res.append(drop_in(unit, "bastet-sandbox", FAIL2BAN_SANDBOX))
    res.append(Unit(name=unit, enabled=True, state="up"))
    return res


def harden(v: dict, host) -> list[Batch]:
    res: list = []
    if v.get("fail2ban"):
        res += _fail2ban(v, host)
    if v.get("lynis"):
        if not v.get("lynis_timer"):
            # masked before lynis installs, so the package can't enable its own timer (Debian's does) in the same run
            res.append(Symlink(path="/etc/systemd/system/lynis.timer", target="/dev/null"))
        res.append(Package(name="lynis"))
        res.append(LynisReport())
    if v.get("vulnerable_packages", True):
        if host.os_id in ARCH_LIKE:
            res += [Package(name="arch-audit"), VulnerablePackages(tool="arch-audit")]
        elif host.os_id in ("debian", "raspbian"):  # Proxmox reports Debian; debsecan only knows Debian suites
            res += [Package(name="debsecan"), VulnerablePackages(tool="debsecan")]
        else:
            raise BastetError(f"harden.vulnerable_packages: no vulnerability scanner known for "
                              f"{host.data.get('os') or 'this OS'}; set vulnerable_packages: false")
    if v.get("service_exposure", True):
        res.append(ServiceExposure(target=float(v.get("exposure_target", 5.0))))
    if v.get("listening_ports", True):
        accounted = (*(v.get("allowed_ports") or []), *(f"tcp/{p}" for p in host.ssh_ports or (22,)), "sshd")
        res += [Package(name="iproute2"), ListeningPorts(accounted=tuple(dict.fromkeys(accounted)))]
    if v.get("apparmor_status", True):
        res.append(AppArmorStatus())
    sysctl = dict(SAFE_SYSCTL) if v.get("sysctl_defaults", True) and not host.container else {}
    if v.get("sysctl"):
        if host.container:
            raise BastetError("harden.sysctl: containers share the node's kernel; set it on the Proxmox node")
        sysctl.update({str(k): str(val) for k, val in v["sysctl"].items()})
    if v.get("core_dumps") == "off":
        res.append(File(path="/etc/systemd/coredump.conf.d/bastet.conf", content="[Coredump]\nStorage=none\nProcessSizeMax=0\n",
                        mode="0644"))
        if not host.container:
            sysctl["fs.suid_dumpable"] = "0"
    for key in sysctl:
        if not _KEY.match(key):
            raise BastetError(f"harden.sysctl: {key!r} isn't a kernel setting name")
    if sysctl:
        body = "# Managed by Bastet (harden role)\n" + "".join(f"{k} = {val}\n" for k, val in sysctl.items())
        res.append(File(path=SYSCTL_FILE, content=body, mode="0644",
                        on_change=(Trigger("apply sysctl", f"sysctl -q -e -p {SYSCTL_FILE}"),)))
    modules = v.get("block_modules") or []
    if modules:
        if host.container:
            raise BastetError("harden.block_modules: containers share the node's kernel; set it on the Proxmox node")
        if not all(_KEY.match(m) for m in modules):
            raise BastetError("harden.block_modules: module names are letters, digits, - and _")
        res.append(File(path="/etc/modprobe.d/bastet-blocklist.conf", mode="0644",
                        content="# Managed by Bastet (harden role)\n" + "".join(f"install {m} /bin/false\nblacklist {m}\n" for m in modules)))
    if v.get("sudo_defaults"):
        if any(re.match(r"^\s*requiretty\b", d) for d in v["sudo_defaults"]):
            raise BastetError("harden.sudo_defaults: requiretty would lock Bastet out of root on this host "
                              "(Bastet runs sudo -n without a terminal)")
        res.append(sudoer("bastet_defaults", defaults=tuple(v["sudo_defaults"])))
    return [Batch("harden", res)] if res else []
