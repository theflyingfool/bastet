from pathlib import Path

import pytest

from bastet.core.config import config_path, data_dir, inventory_dir, load_config
from bastet.core.errors import BastetError


def write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "bastet.yml"
    p.write_text(text, encoding="utf-8")
    return p


def test_config_path_prefers_env_var(tmp_path):
    assert config_path({"BASTET_CONFIG": str(tmp_path / "x.yml")}) == tmp_path / "x.yml"


def test_config_path_uses_xdg_then_home():
    assert config_path({"XDG_CONFIG_HOME": "/cfg"}) == Path("/cfg/bastet/bastet.yml")
    assert config_path({}) == Path.home() / ".config" / "bastet" / "bastet.yml"


def test_config_path_never_points_at_old_cli_file():
    assert config_path({}).name != "config.yml"


def test_data_dir_uses_xdg_then_home():
    assert data_dir({"XDG_DATA_HOME": "/data"}) == Path("/data/bastet")
    assert data_dir({}) == Path.home() / ".local" / "share" / "bastet"


def test_path_only(tmp_path):
    cfg = load_config(write(tmp_path, "inventory:\n  path: ~/Homelab\n"))
    assert cfg.inventory.path == Path.home() / "Homelab"
    assert cfg.inventory.remote is None
    assert inventory_dir(cfg, tmp_path) == Path.home() / "Homelab"


def test_remote_only_uses_data_dir(tmp_path):
    cfg = load_config(write(tmp_path, "inventory:\n  remote: git@example.com:me/inv.git\n"))
    assert inventory_dir(cfg, tmp_path / "data") == tmp_path / "data" / "inventory"


def test_both_set(tmp_path):
    cfg = load_config(
        write(tmp_path, "inventory:\n  remote: git@example.com:me/inv.git\n  path: ~/Homelab\n")
    )
    assert cfg.inventory.remote == "git@example.com:me/inv.git"
    assert cfg.inventory.path == Path.home() / "Homelab"


def test_missing_file_names_path(tmp_path):
    p = tmp_path / "nope.yml"
    with pytest.raises(BastetError) as e:
        load_config(p)
    assert e.value.file == p
    assert str(p) in str(e.value)


def test_neither_remote_nor_path(tmp_path):
    p = write(tmp_path, "inventory: {}\n")
    with pytest.raises(BastetError) as e:
        load_config(p)
    assert e.value.key == "inventory"
    assert "remote" in e.value.message and "path" in e.value.message
    assert not e.value.message.startswith("Value error")


def test_unknown_key_named_with_line(tmp_path):
    p = write(tmp_path, "inventory:\n  path: ~/Homelab\n  pth: ~/Other\n")
    with pytest.raises(BastetError) as e:
        load_config(p)
    assert e.value.key == "inventory.pth"
    assert e.value.line == 3


def test_relative_path_rejected(tmp_path):
    p = write(tmp_path, "inventory:\n  path: Homelab\n")
    with pytest.raises(BastetError) as e:
        load_config(p)
    assert e.value.key == "inventory.path"
    assert e.value.line == 2
    assert "absolute" in e.value.message


def test_bad_yaml_has_line(tmp_path):
    p = write(tmp_path, "inventory:\n  path: [unclosed\n")
    with pytest.raises(BastetError) as e:
        load_config(p)
    assert e.value.file == p
    assert e.value.line is not None


def test_top_level_must_be_mapping(tmp_path):
    p = write(tmp_path, "- just\n- a list\n")
    with pytest.raises(BastetError) as e:
        load_config(p)
    assert "mapping" in e.value.message


def test_age_identity_expanded(tmp_path):
    cfg = load_config(
        write(tmp_path, "inventory:\n  path: ~/Homelab\nsecrets:\n  age_identity: ~/.ssh/id_ed25519\n")
    )
    assert cfg.secrets.age_identity == Path.home() / ".ssh" / "id_ed25519"


def test_error_str_includes_location():
    err = BastetError("bad value", file=Path("/x/bastet.yml"), line=4, key="inventory.path")
    assert str(err) == "/x/bastet.yml:4: inventory.path: bad value"
    assert str(BastetError("plain")) == "plain"


def test_top_level_typo_is_named(tmp_path):
    p = write(tmp_path, "inventroy:\n  path: ~/Homelab\n")
    with pytest.raises(BastetError) as e:
        load_config(p)
    assert e.value.key == "inventroy"
    assert e.value.line == 1


def test_unreadable_config_is_a_bastet_error(tmp_path):
    d = tmp_path / "dir.yml"
    d.mkdir()
    with pytest.raises(BastetError) as e:
        load_config(d)
    assert e.value.file == d
    bad = tmp_path / "latin1.yml"
    bad.write_bytes(b"inventory:\n  path: ~/H\xe9\n")
    with pytest.raises(BastetError) as e:
        load_config(bad)
    assert e.value.file == bad


def test_ssh_section(tmp_path):
    cfg = load_config(
        write(tmp_path, "inventory:\n  path: ~/Homelab\nssh:\n  key: ~/.ssh/bastet\n  bootstrap_user: alice\n")
    )
    assert cfg.ssh.key == Path.home() / ".ssh" / "bastet"
    assert cfg.ssh.bootstrap_user == "alice"


def test_ssh_key_must_be_absolute(tmp_path):
    p = write(tmp_path, "inventory:\n  path: ~/Homelab\nssh:\n  key: bastet\n")
    with pytest.raises(BastetError) as e:
        load_config(p)
    assert e.value.key == "ssh.key"


def test_parallel_jobs_defaults_to_eight(tmp_path):
    cfg = load_config(write(tmp_path, "inventory:\n  path: ~/Homelab\n"))
    assert cfg.parallel.jobs == 8


def test_parallel_jobs_can_be_overridden(tmp_path):
    cfg = load_config(write(tmp_path, "inventory:\n  path: ~/Homelab\nparallel:\n  jobs: 3\n"))
    assert cfg.parallel.jobs == 3


def test_parallel_jobs_below_one_is_a_named_config_error(tmp_path):
    p = write(tmp_path, "inventory:\n  path: ~/Homelab\nparallel:\n  jobs: 0\n")
    with pytest.raises(BastetError) as e:
        load_config(p)
    assert e.value.key == "parallel.jobs"
    assert not e.value.message.startswith("Value error")


def test_runs_config_keeps_everything_by_default_and_validates_limits(tmp_path):
    from bastet.core.config import RunsConfig

    assert RunsConfig().keep_runs is None and RunsConfig().keep_days is None
    assert RunsConfig(keep_runs=10, keep_days=None).keep_runs == 10
    for bad in ({"keep_runs": 0}, {"keep_days": 0}):
        with pytest.raises(Exception):
            RunsConfig(**bad)


def test_an_empty_runs_section_loads_as_the_defaults(tmp_path):
    p = write(tmp_path, "inventory:\n  path: ~/Homelab\nruns:\n")
    cfg = load_config(p)
    assert cfg.runs.keep_runs is None and cfg.runs.keep_days is None
