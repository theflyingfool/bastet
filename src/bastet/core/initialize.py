import json
import shutil
import socket
import subprocess
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from bastet.core.config import load_config
from bastet.core.errors import BastetError
from bastet.core.frontmatter import new_document
from bastet.core.gitrepo import GitRepo
from bastet.core.yamlstyle import dump_frontmatter

GITIGNORE = ".bastet/build/\n.obsidian/workspace.json\n.obsidian/workspace-mobile.json\n.trash/\n"
LAB_BODY = """# {name}

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


def _key(options: InitOptions, keys_dir: Path, actions: list[str]) -> Path:
    if options.key is not None:
        if not options.key.is_file() or not options.key.with_suffix(".pub").is_file():
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
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", f"bastet@{socket.gethostname()}", "-f", str(key)],
        check=True,
    )
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
    root.mkdir(parents=True, exist_ok=True)
    repo = GitRepo(root)
    if repo.is_repo():
        actions.append(f"kept git repository {root}")
    else:
        repo.init()
        actions.append(f"created git repository {root}")
    if options.remote and not repo.has_remote():
        repo.add_remote(options.remote)
        actions.append(f"created remote origin → {options.remote}")

    lab: dict[str, object] = {"bastet": "lab", "cssclasses": ["bastet-dashboard"], "name": options.lab_name}
    if options.domains:
        lab["domains"] = dict(options.domains)
    files = [(".gitignore", GITIGNORE), ("Homelab.md", new_document(lab, LAB_BODY.format(name=options.lab_name)))]
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

    if options.snippet:
        appearance = root / ".obsidian" / "appearance.json"
        data = json.loads(appearance.read_text(encoding="utf-8")) if appearance.exists() else {}
        snippets = data.setdefault("enabledCssSnippets", [])
        if "bastet" in snippets:
            actions.append("kept Obsidian stylesheet setting")
        else:
            snippets.append("bastet")
            appearance.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            written.append(appearance)
            actions.append("created Obsidian stylesheet setting (enabled 'bastet')")

    committed = repo.commit(written, "bastet init") if written else False
    return InitResult(actions=actions, committed=committed, public_key=key.with_suffix(".pub"))
