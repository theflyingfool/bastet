from bastet.cli.app import app
from bastet.core.config import load_config


def test_cli_init_yes_uses_defaults_and_flags(runner, tmp_path, monkeypatch):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    result = runner.invoke(app, ["init", "--inventory", str(tmp_path / "Homelab"), "--public-domain", "example.com", "-y"])
    assert result.exit_code == 0, result.output
    assert "created" in result.output and "ssh-ed25519" in result.output
    lab = (tmp_path / "Homelab" / "Homelab.md").read_text()
    assert "public: example.com" in lab and "internal: example.com" in lab


def test_cli_init_interactive(runner, tmp_path, monkeypatch):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    answers = "\n".join([
        str(tmp_path / "Lab"),   # inventory
        "",                      # remote: none
        "new",                   # key
        "nick",                  # bootstrap user
        "My Lab",                # lab name
        "example.com",           # public domain
        "-",                     # internal domain: none
        "y",                     # stylesheet
        "y",                     # go ahead
    ]) + "\n"
    result = runner.invoke(app, ["init"], input=answers)
    assert result.exit_code == 0, result.output
    assert load_config(cfg).inventory.path == tmp_path / "Lab"
    assert "name: My Lab" in (tmp_path / "Lab" / "Homelab.md").read_text()


def test_cli_init_declined_writes_nothing(runner, tmp_path, monkeypatch):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    answers = "\n".join([str(tmp_path / "Lab"), "", "new", "nick", "Homelab", "", "-", "y", "n"]) + "\n"
    result = runner.invoke(app, ["init"], input=answers)
    assert result.exit_code == 0
    assert not cfg.exists() and not (tmp_path / "Lab").exists()


def test_cli_init_builds_dashboard(runner, tmp_path, monkeypatch):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    result = runner.invoke(app, ["init", "--inventory", str(tmp_path / "Homelab"), "-y"])
    assert result.exit_code == 0, result.output
    assert "![[bastet dashboard]]" in (tmp_path / "Homelab" / "Homelab.md").read_text()
    assert (tmp_path / "Homelab" / "_bastet" / "bastet dashboard.md").exists()
