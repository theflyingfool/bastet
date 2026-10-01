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


def test_remote_written_and_added(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_SSH_COMMAND", "false")
    cfg = tmp_path / "bastet.yml"
    initialize(cfg, opts(tmp_path, remote="git@example.com:me/inv.git"), keys_dir=tmp_path / "ssh")
    assert load_config(cfg).inventory.remote == "git@example.com:me/inv.git"
    remotes = subprocess.run(["git", "-C", str(tmp_path / "Homelab"), "remote", "-v"], capture_output=True, text=True).stdout
    assert "git@example.com:me/inv.git" in remotes


def test_bad_appearance_json_is_located_error(tmp_path):
    inv = tmp_path / "Homelab"
    (inv / ".obsidian").mkdir(parents=True)
    (inv / ".obsidian" / "appearance.json").write_text("{not json")
    with pytest.raises(BastetError) as e:
        initialize(tmp_path / "bastet.yml", opts(tmp_path), keys_dir=tmp_path / "ssh")
    assert e.value.file == inv / ".obsidian" / "appearance.json"


def test_existing_key_with_extension(tmp_path):
    key = tmp_path / "bastet.key"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
    r = initialize(tmp_path / "bastet.yml", opts(tmp_path, key=key), keys_dir=tmp_path / "ssh")
    assert r.public_key == tmp_path / "bastet.key.pub"


def test_ssh_keygen_failure_is_bastet_error(tmp_path, monkeypatch):
    import bastet.core.initialize as init_mod

    def boom(*a, **k):
        raise subprocess.CalledProcessError(1, a[0], stderr="nope")

    monkeypatch.setattr(init_mod.subprocess, "run", boom)
    with pytest.raises(BastetError):
        initialize(tmp_path / "bastet.yml", opts(tmp_path), keys_dir=tmp_path / "ssh")


def _bare_with_commit(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", "-q", str(bare), str(seed)], check=True, capture_output=True)
    (seed / "hosts").mkdir()
    (seed / "hosts" / "pve1.md").write_text("---\nbastet: host\ntype: proxmox-node\nip: 10.0.10.11\n---\n")
    for args in (["add", "."], ["-c", "user.name=T", "-c", "user.email=t@example.com", "commit", "-q", "-m", "seed"], ["push", "-q"]):
        subprocess.run(["git", "-C", str(seed), *args], check=True, capture_output=True)
    return bare


def test_init_clones_remote_with_history(tmp_path):
    bare = _bare_with_commit(tmp_path)
    r = initialize(tmp_path / "bastet.yml", opts(tmp_path, remote=str(bare)), keys_dir=tmp_path / "ssh")
    inv = tmp_path / "Homelab"
    assert (inv / "hosts" / "pve1.md").exists()
    assert any(a.startswith("cloned") for a in r.actions)
    remote_log = subprocess.run(["git", "--git-dir", str(bare), "log", "--format=%s"], capture_output=True, text=True).stdout
    assert "bastet init" in remote_log


def test_init_pushes_to_empty_remote(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    initialize(tmp_path / "bastet.yml", opts(tmp_path, remote=str(bare)), keys_dir=tmp_path / "ssh")
    remote_log = subprocess.run(["git", "--git-dir", str(bare), "log", "--format=%s"], capture_output=True, text=True).stdout
    assert "bastet init" in remote_log
