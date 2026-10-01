import json
import subprocess
from pathlib import Path

import pytest

from bastet.core.config import load_config
from bastet.core.errors import BastetError
from bastet.core.initialize import InitOptions, initialize


def log(root):
    return subprocess.run(["git", "-C", str(root), "log", "--format=%an %s"], capture_output=True, text=True).stdout.splitlines()


def opts(tmp_path: Path, **kw) -> InitOptions:
    base = dict(
        inventory=tmp_path / "Homelab", remote=None, key=None, bootstrap_user="nick",
        lab_name="Homelab", domains={"public": "example.com"}, snippet=True,
    )
    base.update(kw)
    return InitOptions(**base)


def test_init_from_nothing(tmp_path):
    cfg = tmp_path / "cfg" / "bastet.yml"
    r = initialize(cfg, opts(tmp_path), keys_dir=tmp_path / "cfg" / "ssh")
    inv = tmp_path / "Homelab"
    loaded = load_config(cfg)
    assert loaded.inventory.path == inv
    assert loaded.ssh.key == tmp_path / "cfg" / "ssh" / "id_ed25519"
    assert loaded.ssh.bootstrap_user == "nick"
    lab = (inv / "Homelab.md").read_text()
    assert lab.startswith("---\nbastet: lab\n") and "name: Homelab\n" in lab and "public: example.com\n" in lab
    assert (inv / ".obsidian" / "snippets" / "bastet.css").exists()
    assert json.loads((inv / ".obsidian" / "appearance.json").read_text())["enabledCssSnippets"] == ["bastet"]
    assert r.public_key.read_text().startswith("ssh-ed25519 ")
    assert r.committed and log(inv)[0] == "Bastet bastet init"


def test_init_is_idempotent(tmp_path):
    cfg = tmp_path / "cfg" / "bastet.yml"
    initialize(cfg, opts(tmp_path), keys_dir=tmp_path / "ssh")
    before = log(tmp_path / "Homelab")
    r = initialize(cfg, opts(tmp_path), keys_dir=tmp_path / "ssh")
    assert not r.committed
    assert all(a.startswith("kept") for a in r.actions), r.actions
    assert log(tmp_path / "Homelab") == before


def test_existing_key_is_used_not_generated(tmp_path):
    key = tmp_path / "mykey"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
    cfg = tmp_path / "bastet.yml"
    r = initialize(cfg, opts(tmp_path, key=key), keys_dir=tmp_path / "ssh")
    assert load_config(cfg).ssh.key == key
    assert not (tmp_path / "ssh").exists()
    assert r.public_key == key.with_suffix(".pub")


def test_missing_existing_key_is_error(tmp_path):
    with pytest.raises(BastetError) as e:
        initialize(tmp_path / "bastet.yml", opts(tmp_path, key=tmp_path / "nope"), keys_dir=tmp_path / "ssh")
    assert e.value.file == tmp_path / "nope"


def test_no_snippet(tmp_path):
    initialize(tmp_path / "bastet.yml", opts(tmp_path, snippet=False), keys_dir=tmp_path / "ssh")
    assert not (tmp_path / "Homelab" / ".obsidian").exists()


def test_keeps_existing_repo_and_merges_appearance(tmp_path):
    inv = tmp_path / "Homelab"
    (inv / ".obsidian").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(inv)], check=True)
    (inv / ".gitignore").write_text("custom\n")
    (inv / ".obsidian" / "appearance.json").write_text('{"theme": "obsidian", "enabledCssSnippets": ["mine"]}')
    initialize(tmp_path / "bastet.yml", opts(tmp_path), keys_dir=tmp_path / "ssh")
    assert (inv / ".gitignore").read_text() == "custom\n"
    data = json.loads((inv / ".obsidian" / "appearance.json").read_text())
    assert data == {"theme": "obsidian", "enabledCssSnippets": ["mine", "bastet"]}


def test_remote_written_and_added(tmp_path):
    cfg = tmp_path / "bastet.yml"
    initialize(cfg, opts(tmp_path, remote="git@example.com:me/inv.git"), keys_dir=tmp_path / "ssh")
    assert load_config(cfg).inventory.remote == "git@example.com:me/inv.git"
    remotes = subprocess.run(["git", "-C", str(tmp_path / "Homelab"), "remote", "-v"], capture_output=True, text=True).stdout
    assert "git@example.com:me/inv.git" in remotes
