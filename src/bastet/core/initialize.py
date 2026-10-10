import json
import shutil
import socket
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import pyrage.x25519

from bastet.core.bootstrap import _KEY
from bastet.core.config import load_config
from bastet.core.errors import BastetError
from bastet.core.frontmatter import new_document, parse_document, set_keys
from bastet.core.gitrepo import GitRepo
from bastet.core.views import VIEWS
from bastet.core.yamlstyle import dump_frontmatter

GITIGNORE = ".bastet/build/\n.obsidian/workspace.json\n.obsidian/workspace-mobile.json\n.trash/\n"
LAB_BODY = """# {name}

![[bastet dashboard]]

Lab-wide settings live in this page's properties: domains, networks, and so on.
The overview appears here once Bastet generates it.
"""


@dataclass
class InitOptions:
    inventory: Path
    remote: str | None
    key: Path | None
    bootstrap_user: str
    lab_name: str
    domains: dict[str, str] = field(default_factory=dict)
    snippet: bool = True
    recipients: list[str] | None = None  # secrets.recipients to add to Homelab.md; None = leave alone


@dataclass
class InitResult:
    actions: list[str]
    committed: bool
    public_key: Path


def _tilde(path: Path) -> str:
    try:
        return "~/" + path.resolve().relative_to(Path.home().resolve()).as_posix()
    except ValueError:
        return str(path)


def _css() -> str:
    return (resources.files("bastet") / "data" / "obsidian" / "bastet.css").read_text(encoding="utf-8")


def _pub(key: Path) -> Path:
    return Path(str(key) + ".pub")


def generate_recovery_key() -> tuple[str, str]:
    """A fresh age identity for lab recovery: (private, public). The private half is never written to disk;
    it's the caller's job to show it once and then forget it."""
    identity = pyrage.x25519.Identity.generate()
    return str(identity), str(identity.to_public())


def existing_recipients(homelab_path: Path) -> list[str]:
    """`secrets.recipients` already in Homelab.md, or `[]` when the file or the key doesn't exist yet."""
    if not homelab_path.is_file():
        return []
    doc = parse_document(homelab_path.read_text(encoding="utf-8"), homelab_path)
    if doc is None:
        return []
    return list((doc.data.get("secrets") or {}).get("recipients") or [])


def _key(options: InitOptions, keys_dir: Path, actions: list[str]) -> Path:
    if options.key is not None:
        if not options.key.is_file() or not _pub(options.key).is_file():
            raise BastetError("SSH private key (and its .pub) not found", file=options.key)
        actions.append(f"kept SSH key {options.key} (yours)")
        return options.key
    key = keys_dir / "id_ed25519"
    if key.exists():
        actions.append(f"kept SSH key {key}")
        return key
    if shutil.which("ssh-keygen") is None:
        raise BastetError("ssh-keygen not found; install OpenSSH")
    keys_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", f"bastet@{socket.gethostname()}", "-f", str(key)],
            check=True, capture_output=True, text=True,
        )
    except (subprocess.CalledProcessError, OSError) as exc:
        detail = getattr(exc, "stderr", None) or str(exc)
        raise BastetError(f"ssh-keygen failed: {str(detail).strip()}", file=key) from None
    actions.append(f"created SSH key {key}")
    return key


def initialize(config_file: Path, options: InitOptions, *, keys_dir: Path) -> InitResult:
    actions: list[str] = []
    key = _key(options, keys_dir, actions)

    if config_file.exists():
        load_config(config_file)
        actions.append(f"kept {config_file}")
    else:
        inventory: dict[str, object] = {}
        if options.remote:
            inventory["remote"] = options.remote
        inventory["path"] = _tilde(options.inventory)
        data = {"inventory": inventory, "ssh": {"key": _tilde(key), "bootstrap_user": options.bootstrap_user}}
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(dump_frontmatter(data), encoding="utf-8")
        actions.append(f"created {config_file}")

    root = options.inventory
    repo = GitRepo(root)
    empty = not root.exists() or not any(root.iterdir())
    if options.remote and empty:
        if repo.clone_from(options.remote):
            actions.append(f"cloned {options.remote} into {root}")
        else:
            actions.append(f"warning: could not clone {options.remote}; starting a local repository, pushed later")
    root.mkdir(parents=True, exist_ok=True)
    if repo.is_repo():
        actions.append(f"kept git repository {root}")
    else:
        repo.init()
        actions.append(f"created git repository {root}")
    if options.remote and not repo.has_remote():
        repo.add_remote(options.remote)
        actions.append(f"created remote origin → {options.remote}")

    homelab_path = root / "Homelab.md"
    homelab_existed = homelab_path.exists()

    lab: dict[str, object] = {"bastet": "lab", "cssclasses": ["bastet-dashboard"], "name": options.lab_name}
    if options.domains:
        lab["domains"] = dict(options.domains)
    if options.recipients and not homelab_existed:
        lab["secrets"] = {"recipients": list(options.recipients)}
    files = [
        (".gitignore", GITIGNORE),
        ("Homelab.md", new_document(lab, LAB_BODY.format(name=options.lab_name))),
        *VIEWS.items(),
    ]
    if options.snippet:
        files.append((".obsidian/snippets/bastet.css", _css()))

    written: list[Path] = []
    for rel, content in files:
        path = root / rel
        if path.exists():
            actions.append(f"kept {rel}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            written.append(path)
            actions.append(f"created {rel}")

    if options.recipients and homelab_existed and not existing_recipients(homelab_path):
        text = homelab_path.read_text(encoding="utf-8")
        new_text = set_keys(text, {"secrets": {"recipients": list(options.recipients)}}, homelab_path)
        homelab_path.write_text(new_text, encoding="utf-8")
        written.append(homelab_path)
        actions.append("added secrets.recipients to Homelab.md")

    if options.snippet:
        appearance = root / ".obsidian" / "appearance.json"
        try:
            data = json.loads(appearance.read_text(encoding="utf-8")) if appearance.exists() else {}
        except json.JSONDecodeError as exc:
            raise BastetError(f"invalid JSON: {exc.msg}", file=appearance, line=exc.lineno) from None
        if not isinstance(data, dict):
            raise BastetError("expected a JSON object", file=appearance)
        snippets = data.setdefault("enabledCssSnippets", [])
        if "bastet" in snippets:
            actions.append("kept Obsidian stylesheet setting")
        else:
            snippets.append("bastet")
            appearance.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            written.append(appearance)
            actions.append("created Obsidian stylesheet setting (enabled 'bastet')")

    # Set up templates plugin if .obsidian folder exists
    obsidian_dir = root / ".obsidian"
    if obsidian_dir.is_dir() or (options.snippet and obsidian_dir.parent.exists()):
        obsidian_dir.mkdir(exist_ok=True)

        # Update templates.json
        templates_json = obsidian_dir / "templates.json"
        try:
            templates_data = json.loads(templates_json.read_text(encoding="utf-8")) if templates_json.exists() else {}
        except json.JSONDecodeError as exc:
            raise BastetError(f"invalid JSON: {exc.msg}", file=templates_json, line=exc.lineno) from None
        if not isinstance(templates_data, dict):
            raise BastetError("expected a JSON object", file=templates_json)
        if templates_data.get("folder") == "_templates":
            actions.append("kept Obsidian templates plugin setting")
        else:
            templates_data["folder"] = "_templates"
            templates_json.write_text(json.dumps(templates_data, indent=2) + "\n", encoding="utf-8")
            written.append(templates_json)
            actions.append("created Obsidian templates plugin setting (folder: _templates)")

        # Update core-plugins.json
        core_plugins_json = obsidian_dir / "core-plugins.json"
        try:
            core_plugins_data = json.loads(core_plugins_json.read_text(encoding="utf-8")) if core_plugins_json.exists() else {}
        except json.JSONDecodeError as exc:
            raise BastetError(f"invalid JSON: {exc.msg}", file=core_plugins_json, line=exc.lineno) from None

        # Handle both dict format (modern) and list format (legacy)
        if isinstance(core_plugins_data, dict):
            if core_plugins_data.get("templates") is True:
                actions.append("kept Obsidian templates core plugin enabled")
            else:
                core_plugins_data["templates"] = True
                core_plugins_json.write_text(json.dumps(core_plugins_data, indent=2) + "\n", encoding="utf-8")
                written.append(core_plugins_json)
                actions.append("enabled Obsidian templates core plugin")
        elif isinstance(core_plugins_data, list):
            if "templates" in core_plugins_data:
                actions.append("kept Obsidian templates core plugin enabled")
            else:
                core_plugins_data.append("templates")
                core_plugins_json.write_text(json.dumps(core_plugins_data, indent=2) + "\n", encoding="utf-8")
                written.append(core_plugins_json)
                actions.append("enabled Obsidian templates core plugin")

    committed = repo.commit(written, "bastet init") if written else False
    if options.remote and committed and not repo.push():
        actions.append("committed locally; push failed (offline?); it'll be pushed next time")
    return InitResult(actions=actions, committed=committed, public_key=_pub(key))


# --- setting up this machine as a Bastet host: a local `bastet` user, passwordless sudo through a
# validated sudoers drop-in, and Bastet's public key in its authorized_keys. Every system-changing
# command goes through `run`, so tests never touch the real system. ---

SUDOERS_LINE = "bastet ALL=(ALL) NOPASSWD: ALL\n"


@dataclass
class ProcResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


Runner = Callable[[list[str]], ProcResult]


def real_runner(argv: list[str]) -> ProcResult:
    try:
        r = subprocess.run(argv, capture_output=True, text=True)
    except OSError as exc:
        return ProcResult(1, "", str(exc))
    return ProcResult(r.returncode, r.stdout, r.stderr)


def _bastet_identity(run: Runner) -> tuple[str, str] | None:
    """(home, group) for the local `bastet` user, from `getent passwd` (field 6) and its own group
    name (field 4's gid, resolved the same way `id -gn` would via `getent group`)."""
    res = run(["getent", "passwd", "bastet"])
    if res.returncode != 0:
        return None
    fields = res.stdout.strip().split(":")
    if len(fields) <= 5:
        return None
    home, gid = fields[5], fields[3]
    group_res = run(["getent", "group", gid])
    group = group_res.stdout.split(":", 1)[0] if group_res.returncode == 0 and group_res.stdout else gid
    return home, group


def _require(run: Runner, argv: list[str], what: str) -> ProcResult:
    res = run(argv)
    if res.returncode != 0:
        detail = (res.stderr or res.stdout).strip()
        raise BastetError(f"{what} failed: {detail}" if detail else f"{what} failed")
    return res


def _shadow_password(run: Runner) -> str | None:
    """Field 2 of `sudo -n getent shadow bastet` (the password hash), or `None` if it can't be read."""
    res = run(["sudo", "-n", "getent", "shadow", "bastet"])
    if res.returncode != 0:
        return None
    fields = res.stdout.strip().split(":")
    return fields[1] if len(fields) > 1 else None


def local_user_setup(run: Runner, tmp_dir: Path, public_key: str) -> list[str]:
    """Create the local `bastet` user, its passwordless-sudo drop-in and its authorized_keys.
    Idempotent: a second call makes no further changes. The sudoers drop-in is validated with
    `visudo -cf` on a temp file before it's installed; sshd config is never touched here."""
    key = public_key.strip()
    if not _KEY.match(key):
        raise BastetError("Bastet's public key doesn't look like a single OpenSSH public key line")

    actions: list[str] = []
    if run(["id", "bastet"]).returncode == 0:
        actions.append("kept the local bastet user")
    else:
        _require(run, ["sudo", "-n", "useradd", "--create-home", "--shell", "/bin/sh", "bastet"], "creating the local bastet user")
        actions.append("created the local bastet user")

    identity = _bastet_identity(run)
    if identity is None:
        raise BastetError("the bastet user was created, but getent can't find it")
    home, group = identity

    password = _shadow_password(run)
    if password is not None and (password == "*" or password.startswith("!")):
        actions.append("kept the local bastet user's password locked")
    else:
        _require(run, ["sudo", "-n", "usermod", "-p", "*", "bastet"], "locking the local bastet user's password")
        actions.append("locked the local bastet user's password")

    sudoers = run(["sudo", "-n", "cat", "/etc/sudoers.d/bastet"])
    if sudoers.returncode == 0 and sudoers.stdout == SUDOERS_LINE:
        actions.append("kept bastet's passwordless sudo")
    else:
        drop_in = tmp_dir / "bastet.sudoers"
        drop_in.write_text(SUDOERS_LINE, encoding="utf-8")
        check = run(["sudo", "-n", "visudo", "-cf", str(drop_in)])
        if check.returncode != 0:
            raise BastetError(f"the sudoers drop-in failed validation: {(check.stderr or check.stdout).strip()}")
        _require(
            run, ["sudo", "-n", "install", "-o", "root", "-g", "root", "-m", "440", str(drop_in), "/etc/sudoers.d/bastet"],
            "installing bastet's sudoers drop-in",
        )
        actions.append("set up bastet's passwordless sudo")

    authorized = run(["sudo", "-n", "cat", f"{home}/.ssh/authorized_keys"])
    if authorized.returncode == 0 and authorized.stdout.strip() == key:
        actions.append("kept Bastet's key in bastet's authorized_keys")
    else:
        _require(
            run, ["sudo", "-n", "install", "-d", "-m", "700", "-o", "bastet", "-g", group, f"{home}/.ssh"],
            "creating bastet's .ssh directory",
        )
        key_file = tmp_dir / "bastet.pub"
        key_file.write_text(key + "\n", encoding="utf-8")
        _require(
            run, ["sudo", "-n", "install", "-o", "bastet", "-g", group, "-m", "600", str(key_file), f"{home}/.ssh/authorized_keys"],
            "installing Bastet's key in bastet's authorized_keys",
        )
        actions.append("installed Bastet's key in bastet's authorized_keys")

    return actions


SSHD_UNIT_NAMES = ("sshd", "ssh")  # Arch and most distros use `sshd`; Debian/Ubuntu use `ssh`


def _unit_installed(run: Runner, unit: str) -> bool:
    """Whether systemd has a unit file for this name at all. `systemctl is-active` on an unknown
    unit still prints `inactive` (with rc 4), so it can't tell an unknown unit from a known,
    inactive one; `systemctl cat` fails for a unit that was never loaded."""
    return run(["systemctl", "cat", unit]).returncode == 0


def _unit_is_active(run: Runner, unit: str) -> bool:
    return run(["systemctl", "is-active", unit]).stdout.strip() == "active"


def _known_sshd_unit(run: Runner) -> str | None:
    """The first installed unit name (`sshd`, then `ssh`), or `None` if neither is installed."""
    return next((unit for unit in SSHD_UNIT_NAMES if _unit_installed(run, unit)), None)


def sshd_inactive_unit(run: Runner) -> str | None:
    """Which installed unit (`sshd` or `ssh`) looks inactive and so could be started; `None` when
    one is already active (nothing to start) or neither name is installed at all."""
    for unit in SSHD_UNIT_NAMES:
        if not _unit_installed(run, unit):
            continue
        if _unit_is_active(run, unit):
            return None
        return unit
    return None


def sshd_ready(run: Runner, scan: Callable[..., object]) -> tuple[bool, str | None]:
    """Is sshd answering on 127.0.0.1? The scan is tried first and is authoritative: if it answers,
    sshd is ready whatever systemd reports (e.g. a socket-activated unit, or one neither known unit
    name matches). `systemctl` is only consulted, when the scan fails, to pick which hint to print;
    sshd config is never edited here."""
    try:
        scan("127.0.0.1", port=22)
        return True, None
    except BastetError:
        pass
    unit = _known_sshd_unit(run)
    if unit is None:
        return False, "no sshd or ssh unit is installed; install openssh, e.g. `sudo pacman -S openssh` or `sudo apt install openssh-server`"
    if _unit_is_active(run, unit):
        return False, "sshd isn't answering on 127.0.0.1; add `ListenAddress 127.0.0.1` to sshd_config and reload it"
    return False, f"sshd isn't active; enable and start it, e.g. `sudo systemctl enable --now {unit}`"
