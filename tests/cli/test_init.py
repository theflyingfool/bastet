import re

import pytest

import bastet.cli.init as init_mod
from bastet.cli.app import app
from bastet.core.config import load_config

RECOVERY_RE = re.compile(r"AGE-SECRET-KEY-1[A-Z0-9]+")


@pytest.fixture(autouse=True)
def _no_real_home(tmp_path, monkeypatch):
    """Every test here touches `~/.ssh` through `bastet init`; keep it pointed at a throwaway HOME,
    never the real one."""
    monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))


@pytest.fixture
def interactive(monkeypatch):
    """Pretend stdout is a terminal, so `init` creates the recovery key and recipients -- a
    CliRunner's captured stdout never is one, by design (m2)."""
    monkeypatch.setattr(init_mod, "_stdout_is_tty", lambda: True)


def test_cli_init_yes_uses_defaults_and_flags(runner, tmp_path, monkeypatch):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    result = runner.invoke(app, ["init", "--inventory", str(tmp_path / "Homelab"), "--public-domain", "example.com", "-y"])
    assert result.exit_code == 0, result.output
    assert "created" in result.output and "ssh-ed25519" in result.output
    lab = (tmp_path / "Homelab" / "Homelab.md").read_text()
    assert "public: example.com" in lab and "internal: example.com" in lab


def test_cli_init_interactive(runner, tmp_path, monkeypatch, interactive):
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
        "",                      # your SSH public key: skip
        "y",                     # go ahead
    ]) + "\n"
    result = runner.invoke(app, ["init"], input=answers)
    assert result.exit_code == 0, result.output
    assert load_config(cfg).inventory.path == tmp_path / "Lab"
    assert "name: My Lab" in (tmp_path / "Lab" / "Homelab.md").read_text()


def test_cli_init_declined_writes_nothing(runner, tmp_path, monkeypatch, interactive):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    answers = "\n".join([str(tmp_path / "Lab"), "", "new", "nick", "Homelab", "", "-", "y", "", "n"]) + "\n"
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


def _recovery_key(output: str) -> str:
    m = RECOVERY_RE.search(output)
    assert m, output
    return m.group(0)


def test_cli_init_prints_recovery_key_once_and_never_writes_it(runner, tmp_path, monkeypatch, interactive):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    result = runner.invoke(app, ["init", "--inventory", str(tmp_path / "Homelab"), "-y"])
    assert result.exit_code == 0, result.output
    assert "Recovery key: keep this offline" in result.output
    key = _recovery_key(result.output)
    assert result.output.count(key) == 1
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert key not in path.read_text(encoding="utf-8", errors="ignore"), path


def test_cli_init_adds_recipients_to_homelab(runner, tmp_path, monkeypatch, interactive):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    home = tmp_path / "fakehome"
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "id_ed25519.pub").write_text("ssh-ed25519 AAAAyourkey nick@laptop\n")
    result = runner.invoke(app, ["init", "--inventory", str(tmp_path / "Homelab"), "-y"])
    assert result.exit_code == 0, result.output
    lab = (tmp_path / "Homelab" / "Homelab.md").read_text()
    assert "secrets:" in lab and "recipients:" in lab
    assert "ssh-ed25519 AAAAyourkey nick@laptop" in lab
    assert "age1" in lab


def test_cli_init_recipients_are_idempotent(runner, tmp_path, monkeypatch, interactive):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    inv = tmp_path / "Homelab"
    first = runner.invoke(app, ["init", "--inventory", str(inv), "-y"])
    assert first.exit_code == 0, first.output
    lab_before = (inv / "Homelab.md").read_text()

    second = runner.invoke(app, ["init", "-y"])
    assert second.exit_code == 0, second.output
    assert "Recovery key" not in second.output
    lab_after = (inv / "Homelab.md").read_text()
    assert lab_after == lab_before


def test_cli_init_offers_recipients_for_existing_inventory(runner, tmp_path, monkeypatch, interactive):
    """An inventory from before secrets existed: `bastet init` offers to add recipients, as a diff."""
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    inv = tmp_path / "Homelab"
    first = runner.invoke(app, ["init", "--inventory", str(inv), "-y"])
    assert first.exit_code == 0, first.output
    lab = inv / "Homelab.md"
    text = lab.read_text()
    assert "secrets:" in text  # -y adds them by default; drop them to simulate an older inventory
    lines = text.splitlines()
    start = lines.index("secrets:")
    end = start + 1
    while end < len(lines) and lines[end].startswith((" ", "\t")):
        end += 1
    del lines[start:end]
    lab.write_text("\n".join(lines) + "\n")
    assert "secrets:" not in lab.read_text()

    result = runner.invoke(
        app,
        ["init", "--lab-name", "Homelab", "--public-domain", "", "--internal-domain", "", "--snippet"],
        input="\ny\ny\n",  # your SSH key: skip; add recipients: yes; go ahead: yes
    )
    assert result.exit_code == 0, result.output
    assert "Bastet will add to Homelab.md" in result.output
    assert "Recovery key: keep this offline" in result.output
    assert "secrets:" in lab.read_text() and "recipients:" in lab.read_text()


# --- m2: the recovery key is the only copy of that identity; never print it, or create recipients
# that depend on it, anywhere other than an actual terminal ---


def test_cli_init_without_a_terminal_does_not_create_a_recovery_key(runner, tmp_path, monkeypatch):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    result = runner.invoke(app, ["init", "--inventory", str(tmp_path / "Homelab"), "-y"])
    assert result.exit_code == 0, result.output
    assert "Recovery key" not in result.output
    assert not RECOVERY_RE.search(result.output)
    assert "run `bastet init` in a terminal" in result.output
    lab = (tmp_path / "Homelab" / "Homelab.md").read_text()
    assert "secrets:" not in lab


def test_cli_init_without_a_terminal_for_an_existing_inventory_does_not_offer_recipients(
    runner, tmp_path, monkeypatch, interactive
):
    cfg = tmp_path / "c" / "bastet.yml"
    monkeypatch.setenv("BASTET_CONFIG", str(cfg))
    inv = tmp_path / "Homelab"
    first = runner.invoke(app, ["init", "--inventory", str(inv), "-y"])
    assert first.exit_code == 0, first.output

    monkeypatch.setattr(init_mod, "_stdout_is_tty", lambda: False)
    second = runner.invoke(app, ["init", "-y"])
    assert second.exit_code == 0, second.output
    assert "Recovery key" not in second.output
