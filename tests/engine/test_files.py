import os
import stat

from bastet.core.remote import LocalRunner
from bastet.engine.files import Block, Directory, File, Line, Symlink
from bastet.engine.run import Batch, run_host

TRICKY = "say \"hi\" to $HOME \\ 'q' · ünïcode\n@@BASTET-0000@@\nno trailing newline"


def converge(resources):
    batches = [Batch("t", resources)]
    first = run_host(LocalRunner(), "h", batches, apply=True)
    assert first.ok, [(i.resource.label, i.status, i.error) for i in first.items]
    second = run_host(LocalRunner(), "h", batches, apply=True)
    assert [i.status for i in second.items] == ["compliant"] * len(resources)
    return first


def test_file_content_round_trips(tmp_path):
    p = tmp_path / "etc" / "a.conf"
    run = converge([File(path=str(p), content=TRICKY, mode="0640", root=False)])
    assert p.read_bytes() == TRICKY.encode() and stat.S_IMODE(os.stat(p).st_mode) == 0o640
    [item] = run.items
    assert [c.field for c in item.changes][0] == "content" and item.changes[0].before == "(absent)"


def test_file_update_shows_diff_and_keeps_mode(tmp_path):
    p = tmp_path / "motd"
    p.write_text("Welcome to Debian\n")
    os.chmod(p, 0o600)
    check = run_host(LocalRunner(), "h", [Batch("t", [File(path=str(p), content="media01 · managed by Bastet\n", root=False)])], apply=False)
    [item] = check.items
    assert item.diff == "@@ -1 +1 @@\n-Welcome to Debian\n+media01 · managed by Bastet"
    converge([File(path=str(p), content="media01 · managed by Bastet\n", root=False)])
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600


def test_mode_only_change(tmp_path):
    p = tmp_path / "x"
    p.write_text("same\n")
    os.chmod(p, 0o644)
    run = converge([File(path=str(p), content="same\n", mode="0600", root=False)])
    assert [(c.field, c.before, c.after) for c in run.items[0].changes] == [("mode", "0644", "0600")]


def test_validate_failure_keeps_original(tmp_path):
    p = tmp_path / "sudoers"
    p.write_text("original\n")
    run = run_host(LocalRunner(), "h", [Batch("t", [File(path=str(p), content="broken\n", validate="grep -q VALID %s", root=False)])], apply=True)
    [item] = run.items
    assert item.status == "failed" and p.read_text() == "original\n"
    assert sorted(x.name for x in tmp_path.iterdir()) == ["sudoers"]


def test_secret_file_has_no_diff(tmp_path):
    p = tmp_path / "token"
    p.write_text("old-secret\n")
    run = run_host(LocalRunner(), "h", [Batch("t", [File(path=str(p), content="new-secret\n", secret=True, root=False)])], apply=False)
    assert run.items[0].diff is None


def test_directory_and_symlink(tmp_path):
    d = tmp_path / "srv" / "app"
    link = tmp_path / "current"
    converge([Directory(path=str(d), mode="0750", root=False), Symlink(path=str(link), target=str(d), root=False)])
    assert d.is_dir() and stat.S_IMODE(os.stat(d).st_mode) == 0o750 and os.readlink(link) == str(d)


def test_symlink_never_replaces_a_real_file(tmp_path):
    p = tmp_path / "real"
    p.write_text("keep me\n")
    run = run_host(LocalRunner(), "h", [Batch("t", [Symlink(path=str(p), target="/etc/hosts", root=False)])], apply=True)
    assert run.items[0].status == "failed" and "isn't a symlink" in run.items[0].error and p.read_text() == "keep me\n"


def test_block_and_line_in_one_file(tmp_path):
    p = tmp_path / "sshd_config"
    p.write_text("Port 22\n#PermitRootLogin yes\n")
    converge([
        Block(path=str(p), block="ClientAliveInterval 60\nClientAliveCountMax 3", marker="bastet keepalive", root=False),
        Line(path=str(p), line="PermitRootLogin no", match=r"^#?PermitRootLogin\b", root=False),
    ])
    assert p.read_text() == (
        "Port 22\nPermitRootLogin no\n"
        "# BEGIN bastet keepalive\nClientAliveInterval 60\nClientAliveCountMax 3\n# END bastet keepalive\n"
    )


def test_block_replaces_its_own_block_only(tmp_path):
    p = tmp_path / "conf"
    p.write_text("a\n# BEGIN bastet x\nold\n# END bastet x\nb\n")
    converge([Block(path=str(p), block="new", marker="bastet x", root=False)])
    assert p.read_text() == "a\n# BEGIN bastet x\nnew\n# END bastet x\nb\n"


def test_line_appends_when_nothing_matches(tmp_path):
    p = tmp_path / "conf"
    p.write_text("a")
    converge([Line(path=str(p), line="b", root=False)])
    assert p.read_text() == "a\nb\n"
