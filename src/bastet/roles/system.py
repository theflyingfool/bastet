"""Roles built on the building blocks: base, pacman and proxmox."""

from __future__ import annotations

import re

from bastet.core.errors import BastetError
from bastet.core.osinfo import ARCH_LIKE
from bastet.engine.command import Command
from bastet.engine.files import File, Line
from bastet.engine.packages import Package, Repository, StraySources
from bastet.engine.run import Batch
from bastet.engine.systemd import reload

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
            raise BastetError("base.microcode: auto needs the CPU vendor; run bastet gather on this host first")
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
                          "set suite (e.g. trixie) or run bastet gather")
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


def _excludes_bastet(criteria: str) -> bool:
    """A Match whose User criterion lists users, none of them bastet (and no wildcard), can't touch Bastet's login."""
    words = criteria.split()
    for i, w in enumerate(words[:-1]):
        if w.lower() == "user":
            users = words[i + 1].split(",")
            return all(u.lstrip("!") != BASTET and "*" not in u and "?" not in u for u in users)
    return False


def _guard_ssh(settings: dict, where: str, *, criteria: str | None = None) -> None:
    def stop(why: str):
        raise BastetError(f"{where}: {why} would lock Bastet out of this host")

    if criteria is not None and _excludes_bastet(criteria):
        return
    if settings.get("pubkey_authentication") is False:
        stop("pubkey_authentication: false")
    methods = settings.get("authentication_methods")
    if methods is not None and str(methods) != "any" and "publickey" not in str(methods):
        stop("authentication_methods without publickey")
    allow_users = settings.get("allow_users")
    if allow_users is not None and not any(u == BASTET or u.startswith(f"{BASTET}@") or u == "*" for u in _names(allow_users)):
        stop("allow_users without bastet")
    allow_groups = settings.get("allow_groups")
    if allow_groups is not None and BASTET not in _names(allow_groups) and BASTET not in _names(allow_users or []):
        stop("allow_groups without the bastet group (or bastet in allow_users)")
    for knob in ("deny_users", "deny_groups"):
        if settings.get(knob) is not None and BASTET in _names(settings[knob]):
            stop(f"{knob} with bastet")
    for knob in ("force_command", "chroot_directory"):
        if settings.get(knob) is not None:
            stop(f"{knob} for every user (use a match with User …)")


def ssh(v: dict, host) -> list[Batch]:
    glob = {k: val for k, val in v.items() if k != "match" and val is not None}
    matches = v.get("match") or []
    _guard_ssh(glob, "ssh")
    for i, m in enumerate(matches):
        _guard_ssh(m.get("settings") or {}, f"ssh.match[{i}]", criteria=str(m["criteria"]))
    if not glob and not matches:
        return []
    for p in glob.get("port") or []:
        if not 1 <= p <= 65535:
            raise BastetError(f"ssh.port: {p} isn't a port (1–65535)")
    body = ["# Managed by Bastet (ssh role)", *_sshd_block(glob, "ssh")]
    for i, m in enumerate(matches):
        body.append(f"Match {m['criteria']}")
        body += [f"    {line}" for line in _sshd_block(m.get("settings") or {}, f"ssh.match[{i}]")]
    if matches:
        body.append("Match all")  # the drop-in is included at the top: end our Matches so sshd_config stays global
    unit = "ssh.service" if host.debian_like else "sshd.service"
    return [Batch("ssh", [
        Command(name="sshd_config includes drop-ins",
                unless="grep -qE '^[[:space:]]*Include[[:space:]]+/etc/ssh/sshd_config\\.d/\\*\\.conf' /etc/ssh/sshd_config",
                run=f"sed -i '1i {SSHD_INCLUDE}' /etc/ssh/sshd_config"),
        File(path=SSHD_DROP_IN, content="\n".join(body) + "\n", mode="0644", validate=f"{SSHD} -t -f %s",
             on_change=(reload(unit),)),
    ])]
