from pathlib import Path

import pytest

from bastet.core.errors import BastetError
from bastet.engine.packages import Package
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import check_values, load_roles, with_defaults
from bastet.roles.resolve import Applied

ROLES = load_roles()


def ap(role, values):
    r = ROLES[role]
    return Applied(r, with_defaults(r, check_values(r, values, role)))


def host(os="Debian GNU/Linux 13 (trixie)", physical=False, **data):
    return HostInfo(name="h", type="server" if physical else "vm", data={"os": os, **data}, root=Path("/x"),
                    lab={}, physical=physical)


def names(applied, h):
    return [r.name for b in batches_for([applied], h) for r in b.resources if isinstance(r, Package)]


def test_base_tools_default_and_extra():
    assert names(ap("base", {"extra_tools": ["jq"]}), host()) == ["vim", "zsh", "git", "htop", "tree", "gdu", "wget", "less", "jq"]


def test_microcode_only_on_physical_hosts():
    assert not any("code" in n for n in names(ap("base", {}), host()))
    assert names(ap("base", {}), host(os="Arch Linux", physical=True, cpu="AMD Ryzen 9 5950X 16-Core Processor"))[-1] == "amd-ucode"
    assert names(ap("base", {}), host(physical=True, cpu="Intel(R) Xeon(R) CPU E5-2650 v4"))[-1] == "intel-microcode"
    assert not any("code" in n for n in names(ap("base", {"microcode": "never"}), host(physical=True, cpu="Intel")))


def test_microcode_needs_cpu_fact():
    with pytest.raises(BastetError, match="run bastet run -g"):
        batches_for([ap("base", {})], host(physical=True))


def test_pacman_lines():
    from bastet.engine.files import Settings
    out = [r for b in batches_for([ap("pacman", {"parallel_downloads": 10, "candy": False})], host(os="Arch Linux"))
           for r in b.resources if isinstance(r, Settings)]
    [block] = out
    assert block.keys == ("ParallelDownloads", "Color", "ILoveCandy") and block.lines == ("ParallelDownloads = 10", "Color")
    text = "[options]\n#Color\nILoveCandy\nParallelDownloads = 5\n\n[core]\nInclude = /etc/pacman.d/mirrorlist\n"
    wanted = block.wanted(text)
    head, core = wanted.split("[core]")
    assert "ParallelDownloads = 10\nColor\n" in head and "#bastet: ParallelDownloads = 5" in head
    assert "#bastet: ILoveCandy" in head and "Include = /etc/pacman.d/mirrorlist" in core


def test_pacman_refuses_non_arch():
    with pytest.raises(BastetError, match="isn't Arch-based"):
        batches_for([ap("pacman", {})], host())


def test_pacman_parallel_downloads_positive():
    with pytest.raises(BastetError, match="parallel_downloads"):
        batches_for([ap("pacman", {"parallel_downloads": 0})], host(os="Arch Linux"))


def test_same_package_from_base_and_packages_merges():
    from bastet.engine.run import collect_items
    batches = batches_for([ap("base", {}), ap("packages", {"install": [{"name": "git", "refresh": False}],
                                                          "extra_args": ["--quiet"]})], host())
    items = [i for _, mine in collect_items(batches) for i in mine if getattr(i.resource, "name", "") == "git"]
    assert len(items) == 1 and items[0].resource.refresh is False and items[0].resource.extra_args == ("--quiet",)


def test_aur_setup_is_its_own_batch_and_helper_is_tracked():
    from bastet.engine.packages import Unaccounted
    batches = batches_for([ap("packages", {"install": [{"name": "foo-bin", "aur": True}]})], host(os="Arch Linux"))
    assert [b.name for b in batches] == ["packages (AUR setup)", "packages"]
    unacc = next(r for b in batches for r in b.resources if isinstance(r, Unaccounted))
    assert "yay-bin" in unacc.tracked


def test_pacman_settings_go_in_the_options_section():
    from bastet.engine.files import Settings
    out = [r for b in batches_for([ap("pacman", {"parallel_downloads": 4})], host(os="Arch Linux")) for r in b.resources
           if isinstance(r, Settings)]
    text = "[options]\nHoldPkg = pacman\n\n[core]\nInclude = x\n"
    for r in out:
        text = r.wanted(text)
    head, core = text.split("[core]")
    assert "Color" in head and "ILoveCandy" in head and "ParallelDownloads = 4" in head and "Color" not in core


PACMAN_STOCK = ("[options]\n#RootDir     = /\nHoldPkg     = pacman glibc\n#IgnorePkg   =\nArchitecture = auto\n"
                "#Color\n#NoProgressBar\nCheckSpace\n#VerbosePkgLists\nParallelDownloads = 5\n"
                "SigLevel    = Required DatabaseOptional\nLocalFileSigLevel = Optional\n\n[core]\nInclude = /etc/pacman.d/mirrorlist\n")


def pacman_text(values, start=PACMAN_STOCK):
    from bastet.engine.files import Settings
    text = start
    for b in batches_for([ap("pacman", values)], host(os="Arch Linux")):
        for r in b.resources:
            if isinstance(r, Settings):
                text = r.wanted(text)
    return text


def test_pacman_exposes_every_options_setting():
    opts = ROLES["pacman"].options
    for name in ("root_dir", "db_path", "cache_dir", "hook_dir", "gpg_dir", "log_file", "hold_pkg", "ignore_pkg",
                 "ignore_group", "no_upgrade", "no_extract", "architecture", "xfer_command", "clean_method",
                 "sig_level", "local_file_sig_level", "remote_file_sig_level", "use_syslog", "color", "no_progress_bar",
                 "check_space", "verbose_pkg_lists", "disable_download_timeout", "parallel_downloads", "download_user",
                 "disable_sandbox", "candy"):
        assert name in opts, name


def test_pacman_lists_values_and_flags():
    text = pacman_text({"ignore_pkg": ["linux", "linux-headers"], "no_extract": ["usr/share/doc/*"],
                        "sig_level": "Required DatabaseOptional TrustedOnly", "check_space": False,
                        "clean_method": ["KeepInstalled", "KeepCurrent"], "download_user": "alpm"})
    head = text.split("[core]")[0]
    block = head.split("### Bastet Managed ###\n")[1].split("### End Bastet Managed ###")[0]
    assert "IgnorePkg = linux linux-headers\n" in block and "NoExtract = usr/share/doc/*\n" in block
    assert "CleanMethod = KeepInstalled KeepCurrent\n" in block and "SigLevel = Required DatabaseOptional TrustedOnly\n" in block
    assert "DownloadUser = alpm\n" in block and "CheckSpace" not in block  # off: no line in the block
    assert "\n#bastet: CheckSpace\n" in head and "#bastet: SigLevel    = Required DatabaseOptional\n" in head
    assert "HoldPkg     = pacman glibc" in head  # unset options are left exactly as they are
    assert pacman_text({"ignore_pkg": ["linux"]}, start=pacman_text({"ignore_pkg": ["linux"]})) == pacman_text({"ignore_pkg": ["linux"]})


def test_pacman_empty_list_comments_it_out():
    text = pacman_text({"hold_pkg": []})
    assert "\n#bastet: HoldPkg     = pacman glibc\n" in text and "\nHoldPkg" not in text


def test_pacman_clean_method_choices():
    with pytest.raises(BastetError, match="KeepAll"):
        ap("pacman", {"clean_method": ["KeepAll"]})


def test_pacman_list_replaces_every_active_line():
    start = "[options]\n#NoExtract   =\nNoExtract = usr/share/man/*\nNoExtract = usr/share/info/*\n\n[core]\nInclude = x\n"
    text = pacman_text({"no_extract": ["usr/share/doc/*"]}, start=start)
    assert text.count("\nNoExtract") == 1 and "NoExtract = usr/share/doc/*\n" in text and "#NoExtract   =" in text
    assert "#bastet: NoExtract = usr/share/man/*\n" in text and "#bastet: NoExtract = usr/share/info/*\n" in text

