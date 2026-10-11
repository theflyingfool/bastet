import pytest

from bastet.engine.files import Settings
from bastet.engine.model import ReadError

CONF = """\
# header
[options]
#RootDir = /
HoldPkg = pacman glibc
CacheDir = /var/cache/pacman/pkg/
CacheDir = /mnt/cache/
SigLevel = Required DatabaseOptional
Color
ColorFoo = 1
#ParallelDownloads = 5

[custom]
SigLevel = Never
Server = https://example.com/$repo
"""

BEGIN, END = "### Bastet Managed ###", "### End Bastet Managed ###"


def settings(lines=("SigLevel = Required", "CacheDir = /x/"), keys=("SigLevel", "CacheDir", "Color")):
    return Settings(path="/etc/pacman.conf", section="options", keys=keys, lines=lines)


EXPECTED = f"""\
# header
[options]
{BEGIN}
SigLevel = Required
CacheDir = /x/
{END}
#RootDir = /
HoldPkg = pacman glibc
#bastet: CacheDir = /var/cache/pacman/pkg/
#bastet: CacheDir = /mnt/cache/
#bastet: SigLevel = Required DatabaseOptional
#bastet: Color
ColorFoo = 1
#ParallelDownloads = 5

[custom]
SigLevel = Never
Server = https://example.com/$repo
"""


def test_originals_are_commented_inside_the_section_and_the_block_goes_right_after_the_header():
    assert settings().wanted(CONF) == EXPECTED


def test_off_keys_are_commented_and_not_written_and_unmanaged_lines_are_left_alone():
    out = settings().wanted(CONF)
    assert "#bastet: Color\n" in out and "\nColor\n" not in out
    assert "ColorFoo = 1" in out and "#ParallelDownloads = 5" in out and "HoldPkg = pacman glibc" in out


def test_another_section_with_the_same_key_is_never_touched():
    assert "[custom]\nSigLevel = Never\n" in settings().wanted(CONF)


def test_running_twice_changes_nothing():
    once = settings().wanted(CONF)
    assert settings().wanted(once) == once
    assert settings().compare({"content": once}) == []


def test_changing_the_values_replaces_the_block_without_extra_prefixes():
    once = settings().wanted(CONF)
    twice = settings(lines=("SigLevel = Never",)).wanted(once)
    assert twice.count(BEGIN) == 1 and "CacheDir = /x/" not in twice and "SigLevel = Never" in twice
    assert twice.count("#bastet: #bastet:") == 0 and twice.count("#bastet: SigLevel") == 1


def test_a_line_enabled_again_by_hand_is_commented_out_again():
    once = settings().wanted(CONF)
    edited = once.replace("#bastet: SigLevel = Required DatabaseOptional", "SigLevel = Required DatabaseOptional")
    assert settings().wanted(edited) == once


def test_no_lines_means_no_block_but_originals_are_still_commented():
    out = settings(lines=()).wanted(CONF)
    assert BEGIN not in out and "#bastet: SigLevel = Required DatabaseOptional" in out


def test_a_missing_section_is_created_at_the_end():
    out = settings().wanted("[core]\nInclude = /x\n")
    assert out == f"[core]\nInclude = /x\n\n[options]\n{BEGIN}\nSigLevel = Required\nCacheDir = /x/\n{END}\n"
    assert settings(lines=()).wanted("[core]\nInclude = /x\n") == "[core]\nInclude = /x\n"


def test_empty_file_and_no_trailing_newline():
    assert settings().wanted("") == f"[options]\n{BEGIN}\nSigLevel = Required\nCacheDir = /x/\n{END}\n"
    assert settings().wanted("[options]\nColor").endswith("#bastet: Color\n") or "#bastet: Color" in settings().wanted("[options]\nColor")


def test_an_unterminated_block_is_a_read_error():
    with pytest.raises(ReadError, match="unterminated block"):
        settings().wanted(f"[options]\n{BEGIN}\nA = 1\n")


def test_identity_is_per_path_and_section():
    other = Settings(path="/etc/pacman.conf", section="core", keys=("X",), lines=("X = 1",))
    assert settings().identity != other.identity


def test_the_files_owner_group_and_mode_are_left_alone(tmp_path):
    import stat

    from bastet.core.remote import LocalRunner
    from bastet.engine.run import Batch, run_host

    path = tmp_path / "pacman.conf"
    path.write_text(CONF)
    path.chmod(0o640)
    before = path.stat()
    edit = Settings(path=str(path), section="options", keys=("SigLevel", "CacheDir", "Color"),
                    lines=("SigLevel = Required",), root=False)
    run = run_host(LocalRunner(), "h", [Batch("x", [edit])], apply=True)
    after = path.stat()
    assert run.ok and BEGIN in path.read_text()
    assert stat.S_IMODE(after.st_mode) == 0o640 and (after.st_uid, after.st_gid) == (before.st_uid, before.st_gid)
