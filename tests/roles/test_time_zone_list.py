import importlib.util
import tomllib
from pathlib import Path

from bastet.roles.contract import load_roles

ROOT = Path(__file__).parents[2]
ZONES = ROOT / "src" / "bastet" / "data" / "roles" / "time" / "time zones.txt"


def load_version_bump():
    spec = importlib.util.spec_from_file_location("version_bump", ROOT / "scripts" / "version_bump.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_shipped_zone_list_is_current_for_the_version_in_pyproject():
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    assert load_version_bump().check_zone_file(ZONES.read_text(encoding="utf-8"), version) == []


def test_the_time_role_loads_with_its_zone_list_filled_in():
    option = load_roles()["time"].options["timezone"]
    assert option.choices_file == "time zones.txt"
    assert {"UTC", "Europe/Berlin"} <= set(option.choices)
