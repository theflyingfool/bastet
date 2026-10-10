"""User docs shipped into every inventory under `_bastet/docs/` (see data/docs/*.md)."""

import re
import subprocess
from pathlib import Path

import pytest

from bastet.cli.common import Context
from bastet.core.changes import write_changes
from bastet.core.config import Config, InventoryConfig
from bastet.core.doctor import diagnose, merged_changes
from bastet.core.gitrepo import GitRepo
from bastet.core.hosttypes import load_host_types
from bastet.core.initialize import InitOptions, initialize
from bastet.core.inventory import load_inventory
from bastet.core.render import DOC_TITLES, docs, generated_changes, hardware_summary, host_summary
from bastet.core.templates import templates_for_inventory

TYPES = load_host_types()


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


def _lab(tmp_path: Path, body: str = "# Homelab\n") -> Path:
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "Homelab.md").write_text(f"---\nbastet: lab\n---\n{body}", encoding="utf-8")
    GitRepo(tmp_path).init()
    git(tmp_path, "config", "user.name", "Tester")
    git(tmp_path, "config", "user.email", "tester@example.com")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "seed")
    return tmp_path


def _ctx(root: Path) -> Context:
    return Context(
        config=Config(inventory=InventoryConfig(path=root)), root=root, repo=GitRepo(root),
        types=TYPES, inventory=load_inventory(root, TYPES),
    )


def test_docs_shipped_and_regenerated_on_version_change(tmp_path, monkeypatch):
    root = _lab(tmp_path)
    repo = GitRepo(root)
    changes = generated_changes(load_inventory(root, TYPES), TYPES, repo)
    write_changes(changes)
    for title in DOC_TITLES:
        text = (root / "_bastet" / "docs" / f"{title}.md").read_text(encoding="utf-8")
        assert "generated: true" in text

    monkeypatch.setattr("bastet.__version__", "9.9.9-test")
    bumped = generated_changes(load_inventory(root, TYPES), TYPES, repo)
    bumped_docs = {c.path.name: c.after for c in bumped if c.path.parent.name == "docs"}
    assert set(bumped_docs) == {f"{t}.md" for t in DOC_TITLES}
    assert all("bastet_version: 9.9.9-test" in text for text in bumped_docs.values())


@pytest.mark.parametrize("text,expected", [
    (templates_for_inventory(TYPES)["Host - server.md"], "[[Hosts and facts]]"),
    (templates_for_inventory(TYPES)["Hardware - drive.md"], "[[Hardware]]"),
    (templates_for_inventory(TYPES)["Role file.md"], "[[Using roles]]"),
])
def test_contextual_links_in_templates(text, expected):
    assert expected in text


def test_contextual_link_in_facts_notes(tmp_path):
    root = _lab(tmp_path)
    (root / "hosts").mkdir()
    (root / "hosts" / "pve1.md").write_text("---\nbastet: host\ntype: server\nip: 10.0.10.5\n---\n# pve1\n")
    (root / "hardware").mkdir()
    (root / "hardware" / "drive1.md").write_text("---\nbastet: hardware\ncategory: drive\nstatus: in-service\n---\n# drive1\n")
    inv = load_inventory(root, TYPES)
    assert "[[Hosts and facts]]" in host_summary(inv, inv.get("pve1"), TYPES, [])
    assert "[[Hosts and facts]]" in hardware_summary(inv, inv.get("drive1"))


def test_homelab_docs_line_from_init_and_doctor_fix_offer(tmp_path):
    # init adds the line on a new lab
    r = initialize(
        tmp_path / "cfg" / "bastet.yml",
        InitOptions(inventory=tmp_path / "Homelab", remote=None, key=None, bootstrap_user="alice", lab_name="Homelab"),
        keys_dir=tmp_path / "cfg" / "ssh",
    )
    lab_text = (tmp_path / "Homelab" / "Homelab.md").read_text(encoding="utf-8")
    assert "Docs: [[Bastet guide]]" in lab_text

    # an existing lab from before this existed gets it offered by `doctor --fix`
    root = _lab(tmp_path / "old-lab", body="# Homelab\n\n![[bastet dashboard]]\n")
    ctx = _ctx(root)
    problems = diagnose(ctx)
    [p] = [p for p in problems if "Docs: [[Bastet guide]]" in (p.fix_note or "")]
    changes = merged_changes(problems)
    write_changes([c for c in changes if c.path == root / "Homelab.md"])
    assert "Docs: [[Bastet guide]]" in (root / "Homelab.md").read_text(encoding="utf-8")


_LINK = re.compile(r"\[\[([^\]|#]+)")


def test_no_dangling_links_in_shipped_docs():
    rendered = docs()
    for title, text in rendered.items():
        for target in _LINK.findall(text):
            assert target in rendered, f"{title} links to unknown doc {target!r}"
