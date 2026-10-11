from pathlib import Path

import pytest

from bastet.core.errors import BastetError
from bastet.engine.command import Command
from bastet.engine.files import Settings
from bastet.engine.slots import SLOTS, rank
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import check_values, load_roles, with_defaults
from bastet.roles.resolve import Applied

ROLES = load_roles()
CONF = "/etc/pacman.conf"
VALIDATE = "pacman-conf --config %s >/dev/null"


def ap(values):
    r = ROLES["pacman"]
    return Applied(r, with_defaults(r, check_values(r, values, "pacman")))


def arch(os="Arch Linux"):
    return HostInfo(name="laptop1", type="laptop", data={"os": os}, root=Path("/nonexistent"), lab={})


def everything(values, host=None):
    [batch] = batches_for([ap(values)], host or arch())
    return batch.resources


def built(values, host=None):
    return [r for r in everything(values, host) if isinstance(r, Settings)]


def settings(keys, lines=None):
    keys = tuple(keys)
    return Settings(path=CONF, section="options", keys=keys, lines=keys if lines is None else tuple(lines),
                    validate=VALIDATE, provides=("package-manager",))


def test_defaults_write_color_and_candy_only():
    assert built({}) == [settings(["Color", "ILoveCandy"])]


def test_a_value_option_is_written_in_option_order():
    assert built({"parallel_downloads": 8}) == [settings(["ParallelDownloads", "Color", "ILoveCandy"],
                                                         ["ParallelDownloads = 8", "Color", "ILoveCandy"])]


def test_a_flag_set_false_keeps_its_key_but_writes_no_line():
    assert built({"color": False}) == [settings(["Color", "ILoveCandy"], ["ILoveCandy"])]


def test_list_options_join_with_spaces_and_an_empty_list_writes_no_line():
    assert built({"ignore_pkg": ["linux", "linux-headers"], "hold_pkg": []}) == [
        settings(["HoldPkg", "IgnorePkg", "Color", "ILoveCandy"], ["IgnorePkg = linux linux-headers", "Color", "ILoveCandy"])]


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
    [block] = built(values)
    assert block.keys == (
        "RootDir", "DBPath", "CacheDir", "HookDir", "GPGDir", "LogFile", "HoldPkg", "IgnorePkg", "IgnoreGroup",
        "NoUpgrade", "NoExtract", "Architecture", "XferCommand", "ParallelDownloads", "DisableDownloadTimeout",
        "DownloadUser", "DisableSandbox", "CleanMethod", "SigLevel", "LocalFileSigLevel", "RemoteFileSigLevel",
        "Color", "ILoveCandy", "NoProgressBar", "VerbosePkgLists", "CheckSpace", "UseSyslog")
    assert block.lines == (
        "RootDir = /", "DBPath = /var/lib/pacman/", "CacheDir = /var/cache/pacman/pkg/", "HookDir = /etc/pacman.d/hooks/",
        "GPGDir = /etc/pacman.d/gnupg/", "LogFile = /var/log/pacman.log", "HoldPkg = pacman glibc", "IgnorePkg = a",
        "IgnoreGroup = g", "NoUpgrade = etc/x", "NoExtract = usr/share/doc/*", "Architecture = auto",
        "XferCommand = /usr/bin/curl -fC - %u -o %o", "ParallelDownloads = 5", "DisableDownloadTimeout",
        "DownloadUser = alpm", "CleanMethod = KeepInstalled", "SigLevel = Required DatabaseOptional",
        "LocalFileSigLevel = Optional", "RemoteFileSigLevel = Required", "Color", "NoProgressBar", "VerbosePkgLists", "CheckSpace")


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


def test_pacman_lines_run_before_the_packages_slot():
    assert all(rank(r) < SLOTS.index("packages") for r in everything({}))
    assert all(rank(r) < SLOTS.index("packages") for r in built({}))


def test_the_original_pacman_conf_is_backed_up_first():
    [backup, block] = everything({})
    assert isinstance(backup, Command) and backup.run == f"cp -p {CONF} {CONF}.bastet-orig"
    assert rank(backup) <= rank(block)  # a tie runs in batch order, and the backup comes first
