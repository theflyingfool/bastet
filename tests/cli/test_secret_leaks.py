def test_tracebacks_never_show_locals():
    from bastet.cli.app import app
    assert app.pretty_exceptions_show_locals is False


def test_top_level_errors_are_masked(capsys):
    import typer
    import pytest
    from bastet.cli.common import handles_errors
    from bastet.core.errors import BastetError
    from bastet.core.secrets.redact import ACTIVE

    ACTIVE.add("SENTINEL-9999")

    @handles_errors
    def boom():
        raise BastetError("command failed: echo SENTINEL-9999")

    with pytest.raises(typer.Exit):
        boom()
    err = capsys.readouterr().err
    assert "SENTINEL-9999" not in err and "‹secret›" in err
