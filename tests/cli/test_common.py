import io
from pathlib import Path

import typer

from bastet.cli.common import Context, guard_prompts, next_hint, print_problems, resolve_jobs
from bastet.core.config import Config, InventoryConfig, ParallelConfig
from bastet.core.errors import BastetError
from bastet.core.gitrepo import GitRepo
from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from bastet.core.parallel import run_parallel


def test_guard_prompts_blocks_confirm_and_prompt_in_worker():
    captured = {}

    def work(host, log):
        try:
            typer.confirm("ok?")
        except BastetError as exc:
            captured["confirm"] = exc.message
        try:
            typer.prompt("value?")
        except BastetError as exc:
            captured["prompt"] = exc.message
        return None

    with guard_prompts():
        run_parallel(["a"], work, jobs=1)

    assert captured["confirm"] == "internal: tried to ask a question while running in parallel"
    assert captured["prompt"] == "internal: tried to ask a question while running in parallel"


def test_guard_prompts_leaves_main_thread_untouched(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))
    with guard_prompts():
        assert typer.confirm("proceed?") is True


def test_guard_prompts_restores_originals_after_exit():
    before = typer.confirm
    with guard_prompts():
        pass
    assert typer.confirm is before


def _config(jobs: int = 8) -> Config:
    return Config(inventory=InventoryConfig(path=Path("/tmp/Homelab")), parallel=ParallelConfig(jobs=jobs))


def test_resolve_jobs_uses_config_default_when_option_not_given():
    assert resolve_jobs(None, _config(jobs=8)) == 8


def test_resolve_jobs_config_override():
    assert resolve_jobs(None, _config(jobs=3)) == 3


def test_resolve_jobs_option_overrides_config():
    assert resolve_jobs(5, _config(jobs=3)) == 5


def test_print_problems_shows_a_role_file_error_with_file_and_key(tmp_path, capsys):
    """A bad value in a role file reaches the terminal through the same `print_problems`/
    `problem_line` every command that loads roles already uses for every other inventory problem."""
    (tmp_path / "hosts").mkdir()
    (tmp_path / "hosts" / "pve1.md").write_text("---\nbastet: host\ntype: proxmox\nip: 10.0.10.11\n---\n# pve1\n")
    (tmp_path / "_roles" / "hosts" / "pve1").mkdir(parents=True)
    (tmp_path / "_roles" / "hosts" / "pve1" / "ssh.md").write_text(
        '---\nbastet: role\nrole: ssh\napplies_to: "[[pve1]]"\nclient_alive_interval: maybe\n---\n# ssh for pve1\n'
    )
    types = load_host_types()
    inv = load_inventory(tmp_path, types)
    ctx = Context(config=_config(), root=tmp_path, repo=GitRepo(tmp_path), types=types, inventory=inv)

    print_problems(ctx)

    out = capsys.readouterr().out
    assert "_roles/hosts/pve1/ssh.md" in out
    assert "client_alive_interval" in out
    assert "expected a whole number" in out


# --- next-step hints: one line, only on a terminal, never with -y ---


def test_next_hint_appears_on_a_terminal_without_yes(capsys, monkeypatch):
    monkeypatch.setattr("bastet.cli.common._stdout_is_tty", lambda: True)
    next_hint("bastet add host", yes=False)
    out = capsys.readouterr().out
    assert "next: bastet add host" in out


def test_next_hint_suppressed_with_yes(capsys, monkeypatch):
    monkeypatch.setattr("bastet.cli.common._stdout_is_tty", lambda: True)
    next_hint("bastet add host", yes=True)
    assert capsys.readouterr().out == ""


def test_next_hint_suppressed_off_a_terminal(capsys, monkeypatch):
    monkeypatch.setattr("bastet.cli.common._stdout_is_tty", lambda: False)
    next_hint("bastet add host", yes=False)
    assert capsys.readouterr().out == ""
