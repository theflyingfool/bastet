import json
import subprocess
from pathlib import Path

import pytest

from bastet.cli.common import Context
from bastet.core.config import Config, InventoryConfig
from bastet.core.doctor import Problem, diagnose, merged_changes
from bastet.core.gitrepo import GitRepo
from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory

TYPES = load_host_types()


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


def put(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


@pytest.fixture
def root(tmp_path) -> Path:
    r = tmp_path / "inv"
    r.mkdir()
    put(r, "Homelab.md", "---\nbastet: lab\n---\n# Homelab\n")
    GitRepo(r).init()
    git(r, "config", "user.name", "Tester")
    git(r, "config", "user.email", "tester@example.com")
    return r


def make_ctx(root: Path) -> Context:
    config = Config(inventory=InventoryConfig(path=root))
    repo = GitRepo(root)
    return Context(config=config, root=root, repo=repo, types=TYPES, inventory=load_inventory(root, TYPES))


def commit_all(root: Path, message: str = "seed") -> None:
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", message)


# --- stale gathered keys: host notes ---


def test_stale_host_keys_fixed_only_when_facts_note_has_the_value(root):
    put(root, "hosts/pve1.md",
        "---\nbastet: host\ntype: server\nip: 10.0.10.5\nos: Debian 12\nkernel: 6.9\n---\n# pve1\n\n![[pve1 facts]]\n")
    put(root, "_bastet/facts/pve1 facts.md", '---\nbastet: facts\nhost: "[[pve1]]"\nos: Debian 12\n---\n')
    commit_all(root)
    ctx = make_ctx(root)
    problems = diagnose(ctx)
    [p] = [p for p in problems if "os, kernel" in p.message or ("os" in p.message and "kernel" in p.message)]
    assert p.fix is not None
    assert p.fix_note == "hosts/pve1.md: removed os (now in pve1 facts)"
    after = p.fix.after
    assert "os:" not in after and "kernel: 6.9" in after  # only the key the facts note actually holds


def test_stale_host_key_with_no_facts_value_is_not_fixed(root):
    put(root, "hosts/pve1.md", "---\nbastet: host\ntype: server\nip: 10.0.10.5\nos: Debian 12\n---\n# pve1\n\n![[pve1 facts]]\n")
    commit_all(root)
    ctx = make_ctx(root)
    problems = diagnose(ctx)
    [p] = [p for p in problems if "os" in p.message and "gathered facts" in p.message]
    assert p.fix is None


# --- stale gathered keys: hardware notes ---


def test_stale_hardware_key_fixed_when_facts_note_has_the_value(root):
    put(root, "hardware/dimm1.md", '---\nbastet: hardware\ncategory: memory\nserial: "ABC123"\n---\n# dimm1\n\n![[dimm1 facts]]\n')
    put(root, "_bastet/facts/dimm1 facts.md", '---\nbastet: facts\nitem: "[[dimm1]]"\nserial: "ABC123"\n---\n')
    commit_all(root)
    ctx = make_ctx(root)
    problems = diagnose(ctx)
    [p] = [p for p in problems if "serial" in p.message and "gathered facts" in p.message]
    assert p.fix is not None
    assert p.fix_note == "hardware/dimm1.md: removed serial (now in dimm1 facts)"
    assert "serial:" not in p.fix.after


# --- retired embeds ---


def test_retired_summary_embed_on_host_note_is_replaced(root):
    put(root, "hosts/pve1.md", "---\nbastet: host\ntype: server\nip: 10.0.10.5\n---\n# pve1\n\n![[pve1 summary]]\n")
    commit_all(root)
    ctx = make_ctx(root)
    problems = diagnose(ctx)
    [p] = [p for p in problems if "retired" in p.message]
    assert p.fix is not None
    assert "![[pve1 facts]]" in p.fix.after
    assert "pve1 summary" not in p.fix.after
    assert p.fix_note == "hosts/pve1.md: replaced the retired embed with ![[pve1 facts]]"


def test_retired_reports_embed_is_also_replaced(root):
    put(root, "hosts/pve1.md", "---\nbastet: host\ntype: server\nip: 10.0.10.5\n---\n# pve1\n\n![[pve1 reports]]\n")
    commit_all(root)
    ctx = make_ctx(root)
    problems = diagnose(ctx)
    [p] = [p for p in problems if "retired" in p.message]
    assert "![[pve1 facts]]" in p.fix.after


def test_both_retired_embeds_collapse_to_one_facts_embed(root):
    put(root, "hosts/pve1.md",
        "---\nbastet: host\ntype: server\nip: 10.0.10.5\n---\n# pve1\n\n![[pve1 summary]]\n\n![[pve1 reports]]\n")
    commit_all(root)
    ctx = make_ctx(root)
    problems = diagnose(ctx)
    [p] = [p for p in problems if "retired" in p.message]
    assert p.fix.after.count("pve1 facts") == 1


def test_page_already_on_the_facts_embed_has_nothing_to_fix(root):
    put(root, "hosts/pve1.md", "---\nbastet: host\ntype: server\nip: 10.0.10.5\n---\n# pve1\n\n![[pve1 facts]]\n")
    commit_all(root)
    ctx = make_ctx(root)
    problems = diagnose(ctx)
    assert not [p for p in problems if "retired" in p.message]


# --- stale keys and a retired embed on the same file: both fixes chain ---


def test_stale_keys_and_retired_embed_on_same_file_both_apply(root):
    put(root, "hosts/pve1.md",
        "---\nbastet: host\ntype: server\nip: 10.0.10.5\nos: Debian 12\n---\n# pve1\n\n![[pve1 summary]]\n")
    put(root, "_bastet/facts/pve1 facts.md", '---\nbastet: facts\nhost: "[[pve1]]"\nos: Debian 12\n---\n')
    commit_all(root)
    ctx = make_ctx(root)
    problems = diagnose(ctx)
    changes = merged_changes(problems)
    [change] = [c for c in changes if c.path.name == "pve1.md"]
    assert "os:" not in change.after
    assert "![[pve1 facts]]" in change.after
    assert "pve1 summary" not in change.after


# --- inventory problems: no duplicate stale-key lines ---


def test_stale_key_problem_not_duplicated_in_the_generic_bucket(root):
    put(root, "hosts/pve1.md", "---\nbastet: host\ntype: server\nip: 10.0.10.5\nos: Debian 12\n---\n# pve1\n\n![[pve1 facts]]\n")
    commit_all(root)
    ctx = make_ctx(root)
    problems = diagnose(ctx)
    matches = [p for p in problems if "are gathered facts" in p.message]
    assert len(matches) == 1


def test_a_real_inventory_error_still_surfaces(root):
    put(root, "hosts/bad.md", "---\nbastet: host\n---\n# bad\n")
    commit_all(root)
    ctx = make_ctx(root)
    problems = diagnose(ctx)
    assert any(p.severity == "error" and "missing 'type'" in p.message for p in problems)


# --- refresh skip reason ---


def test_refresh_skip_reason_is_listed_until_cleared(root):
    from bastet.core import refreshstate

    commit_all(root)
    refreshstate.write(root, "couldn't sync with the remote (offline)")
    ctx = make_ctx(root)
    problems = diagnose(ctx)
    assert any("couldn't sync with the remote" in p.message for p in problems)


def test_no_refresh_skip_problem_when_nothing_was_skipped(root):
    commit_all(root)
    ctx = make_ctx(root)
    problems = diagnose(ctx)
    assert not [p for p in problems if "refresh skipped" in p.message]


# --- push pending ---


def test_push_pending_listed_when_remote_has_a_commit_it_never_saw(tmp_path, root):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    GitRepo(root).add_remote(str(bare))
    commit_all(root)
    ctx = make_ctx(root)
    problems = diagnose(ctx)
    assert any("not pushed" in p.message for p in problems)


def test_no_push_pending_problem_with_no_remote(root):
    commit_all(root)
    ctx = make_ctx(root)
    problems = diagnose(ctx)
    assert not [p for p in problems if "not pushed" in p.message]


# --- merged_changes ---


def test_merged_changes_one_change_per_path():
    from bastet.core.changes import Change

    path = Path("/v/hosts/pve1.md")
    p1 = Problem(where="hosts/pve1.md", message="a", severity="warning", fix=Change(path, "orig", "mid"))
    p2 = Problem(where="hosts/pve1.md", message="b", severity="warning", fix=Change(path, "mid", "final"))
    [change] = merged_changes([p1, p2])
    assert change.before == "orig" and change.after == "final"


# --- Obsidian's Bases core plugin ---

BASES_MESSAGE = "Obsidian's Bases core plugin isn't enabled; Bastet's tables and boards need it"


def bases_problems(root):
    return [p for p in diagnose(make_ctx(root)) if "Bases core plugin" in p.message]


def test_bases_not_enabled_is_a_problem_with_a_fix_that_keeps_other_keys(root):
    path = put(root, ".obsidian/core-plugins.json", '{"graph": true, "canvas": false}')
    commit_all(root)
    [p] = bases_problems(root)
    assert p.message == BASES_MESSAGE
    assert p.fix is not None and p.fix.path == path
    assert json.loads(p.fix.after) == {"graph": True, "canvas": False, "bases": True}


def test_bases_fix_keeps_list_form(root):
    put(root, ".obsidian/core-plugins.json", '["graph", "templates"]')
    commit_all(root)
    [p] = bases_problems(root)
    assert json.loads(p.fix.after) == ["graph", "templates", "bases"]


def test_bases_disabled_in_a_map_is_enabled_by_the_fix(root):
    put(root, ".obsidian/core-plugins.json", '{"bases": false, "graph": true}')
    commit_all(root)
    [p] = bases_problems(root)
    assert json.loads(p.fix.after) == {"bases": True, "graph": True}


def test_bases_enabled_is_no_problem(root):
    put(root, ".obsidian/core-plugins.json", '{"bases": true}')
    commit_all(root)
    assert bases_problems(root) == []


def test_bases_in_list_form_is_no_problem(root):
    put(root, ".obsidian/core-plugins.json", '["bases"]')
    commit_all(root)
    assert bases_problems(root) == []


def test_no_obsidian_folder_is_no_bases_problem(root):
    commit_all(root)
    assert bases_problems(root) == []
