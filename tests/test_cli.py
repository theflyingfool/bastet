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
    import bastet.engine
    import bastet.roles

    for package in (bastet.core, bastet.engine, bastet.roles):
        for mod in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
            importlib.import_module(mod.name)
    loaded = [m for m in sys.modules if m.startswith(("bastet.core", "bastet.engine", "bastet.roles"))]
    for name in loaded:
        module = sys.modules[name]
        source = getattr(module, "__file__", None)
        if source is None:
            continue
        text = open(source, encoding="utf-8").read()
        assert "import typer" not in text and "from typer" not in text, name
        assert "bastet.cli" not in text, name


def test_no_arguments_prints_help_and_succeeds():
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    assert "Usage" in result.stdout and "gather" in result.stdout


def test_help_command_prints_the_main_help():
    result = runner.invoke(app, ["help"])
    assert result.exit_code == 0
    assert result.stdout == runner.invoke(app, ["--help"]).stdout


def test_help_command_prints_a_commands_help():
    assert runner.invoke(app, ["help", "gather"]).stdout == runner.invoke(app, ["gather", "--help"]).stdout
    assert runner.invoke(app, ["help", "secret", "set"]).stdout == runner.invoke(app, ["secret", "set", "--help"]).stdout


def test_help_for_an_unknown_command_fails():
    result = runner.invoke(app, ["help", "nope"])
    assert result.exit_code != 0
    assert "nope" in result.output
