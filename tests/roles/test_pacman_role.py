from pathlib import Path

import pytest

from bastet.core.errors import BastetError
from bastet.engine.files import Line
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import check_values, load_roles, with_defaults
from bastet.roles.resolve import Applied

ROLES = load_roles()
CONF = "/etc/pacman.conf"
OPTIONS = r"^\[options\]\s*$"


def ap(values):
    r = ROLES["pacman"]
    return Applied(r, with_defaults(r, check_values(r, values, "pacman")))


def arch(os="Arch Linux"):
    return HostInfo(name="laptop1", type="laptop", data={"os": os}, root=Path("/nonexistent"), lab={})


def built(values, host=None):
    [batch] = batches_for([ap(values)], host or arch())
    return batch.resources


def line(key, text):
    return Line(path=CONF, line=text, match=rf"^#?\s*{key}\s*(=.*)?$", after=OPTIONS, unique=True)


COLOR, CANDY = line("Color", "Color"), line("ILoveCandy", "ILoveCandy")


def test_defaults_write_color_and_candy_only():
    assert built({}) == [COLOR, CANDY]


def test_a_value_option_is_written_in_option_order():
    assert built({"parallel_downloads": 8}) == [line("ParallelDownloads", "ParallelDownloads = 8"), COLOR, CANDY]


def test_a_flag_set_false_is_commented_out():
    assert built({"color": False}) == [line("Color", "#Color"), CANDY]


def test_list_options_join_with_spaces_and_an_empty_list_comments_the_directive_out():
    assert built({"ignore_pkg": ["linux", "linux-headers"], "hold_pkg": []}) == [
        line("HoldPkg", "#HoldPkg ="), line("IgnorePkg", "IgnorePkg = linux linux-headers"), COLOR, CANDY]


def test_every_option_maps_to_its_pacman_directive():
    values = {
        "root_dir": "/", "db_path": "/var/lib/pacman/", "cache_dir": ["/var/cache/pacman/pkg/"], "hook_dir": ["/etc/pacman.d/hooks/"],
        "gpg_dir": "/etc/pacman.d/gnupg/", "log_file": "/var/log/pacman.log", "hold_pkg": ["pacman", "glibc"],
        "ignore_pkg": ["a"], "ignore_group": ["g"], "no_upgrade": ["etc/x"], "no_extract": ["usr/share/doc/*"],
        "architecture": "auto", "xfer_command": "/usr/bin/curl -fC - %u -o %o", "parallel_downloads": 5,
        "disable_download_timeout": True, "download_user": "alpm", "disable_sandbox": False,
        "clean_method": ["KeepInstalled"], "sig_level": "Required DatabaseOptional",
        "local_file_sig_level": "Optional", "remote_file_sig_level": "Required", "color": True, "candy": False,
        "no_progress_bar": True, "verbose_pkg_lists": True, "check_space": True, "use_syslog": False,
    }
    keys = [(r.line.split(" = ")[0].lstrip("#"), r.line) for r in built(values)]
    assert [k for k, _ in keys] == [
        "RootDir", "DBPath", "CacheDir", "HookDir", "GPGDir", "LogFile", "HoldPkg", "IgnorePkg", "IgnoreGroup",
        "NoUpgrade", "NoExtract", "Architecture", "XferCommand", "ParallelDownloads", "DisableDownloadTimeout",
        "DownloadUser", "DisableSandbox", "CleanMethod", "SigLevel", "LocalFileSigLevel", "RemoteFileSigLevel",
        "Color", "ILoveCandy", "NoProgressBar", "VerbosePkgLists", "CheckSpace", "UseSyslog"]
    lines = dict(keys)
    assert lines["DisableDownloadTimeout"] == "DisableDownloadTimeout" and lines["DisableSandbox"] == "#DisableSandbox"
    assert lines["ILoveCandy"] == "#ILoveCandy" and lines["CleanMethod"] == "CleanMethod = KeepInstalled"
    assert lines["SigLevel"] == "SigLevel = Required DatabaseOptional" and lines["UseSyslog"] == "#UseSyslog"


def test_a_host_that_is_not_arch_based_is_refused_with_the_group_to_aim_at():
    with pytest.raises(BastetError, match=r"pacman role: laptop1 isn't Arch-based \(Debian GNU/Linux 13 \(trixie\)\); aim it at \[\[arch\]\]"):
        built({}, arch("Debian GNU/Linux 13 (trixie)"))


def test_an_unknown_os_is_refused_too():
    with pytest.raises(BastetError, match=r"isn't Arch-based \(OS unknown\)"):
        built({}, HostInfo(name="laptop1", type="laptop", data={}, root=Path("/nonexistent"), lab={}))


@pytest.mark.parametrize("bad", [0, -2])
def test_parallel_downloads_must_be_one_or_more(bad):
    with pytest.raises(BastetError, match=r"pacman\.parallel_downloads:? must be 1 or more"):
        built({"parallel_downloads": bad})


@pytest.mark.parametrize("bad", ["a\nb", "   ", ""])
def test_a_value_option_must_be_one_non_empty_line(bad):
    with pytest.raises(BastetError, match=r"pacman\.xfer_command: needs a single non-empty line"):
        built({"xfer_command": bad})
