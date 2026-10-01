from typer.testing import CliRunner

from bastet import __version__
from bastet.cli.app import app

runner = CliRunner()


def test_version_flag_prints_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"bastet {__version__}"


def test_core_does_not_import_cli_or_typer():
    import importlib
    import pkgutil
    import sys

    import bastet.core

    for mod in pkgutil.walk_packages(bastet.core.__path__, "bastet.core."):
        importlib.import_module(mod.name)
    loaded = [m for m in sys.modules if m.startswith("bastet.core")]
    for name in loaded:
        module = sys.modules[name]
        source = getattr(module, "__file__", None)
        if source is None:
            continue
        text = open(source, encoding="utf-8").read()
        assert "import typer" not in text and "from typer" not in text, name
        assert "bastet.cli" not in text, name
