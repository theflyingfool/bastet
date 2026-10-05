import io
from pathlib import Path

import typer

from bastet.cli.common import guard_prompts, resolve_jobs
from bastet.core.config import Config, InventoryConfig, ParallelConfig
from bastet.core.errors import BastetError
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
