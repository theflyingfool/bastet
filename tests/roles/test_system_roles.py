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
    with pytest.raises(BastetError, match="run bastet gather"):
        batches_for([ap("base", {})], host(physical=True))


def test_pacman_lines():
    from bastet.engine.files import Line
    out = [r for b in batches_for([ap("pacman", {"parallel_downloads": 10, "candy": False})], host(os="Arch Linux"))
           for r in b.resources]
    by_line = {r.line: r for r in out if isinstance(r, Line)}
    assert set(by_line) == {"Color", "#ILoveCandy", "ParallelDownloads = 10"}
    assert by_line["Color"].match == r"^#?\s*Color\s*$"
    text = "[options]\n#Color\n#ParallelDownloads = 5\n\n[core]\nInclude = /etc/pacman.d/mirrorlist\n"
    for r in out:
        text = r.wanted(text)
    assert text == "[options]\nColor\n#ILoveCandy\nParallelDownloads = 10\n\n[core]\nInclude = /etc/pacman.d/mirrorlist\n"


def test_pacman_refuses_non_arch():
    with pytest.raises(BastetError, match="isn't Arch-based"):
        batches_for([ap("pacman", {})], host())


def test_pacman_parallel_downloads_positive():
    with pytest.raises(BastetError, match="parallel_downloads"):
        batches_for([ap("pacman", {"parallel_downloads": 0})], host(os="Arch Linux"))


def pve(**data):
    return host(os="Debian GNU/Linux 13 (trixie)", physical=True, cpu="Intel", **data)


def test_proxmox_repositories_for_trixie():
    from bastet.engine.packages import Repository
    out = [r for b in batches_for([ap("proxmox", {})], pve()) for r in b.resources]
    repos = {r.name: r for r in out if isinstance(r, Repository)}
    assert repos["debian"].suites == ("trixie", "trixie-updates")
    assert repos["debian"].components == ("main", "contrib", "non-free-firmware")
    assert repos["debian-security"].suites == ("trixie-security",)
    assert repos["proxmox"].components == ("pve-no-subscription",) and repos["proxmox"].enabled
    assert not repos["pve-enterprise"].enabled
    assert [r.name for r in out if isinstance(r, Package)] == ["libguestfs-tools"]


def test_proxmox_enterprise_and_custom_mirror():
    from bastet.engine.packages import Repository
    out = [r for b in batches_for([ap("proxmox", {"repository": "enterprise", "debian_mirror": "http://ftp.us.debian.org/debian"})], pve())
           for r in b.resources]
    repos = {r.name: r for r in out if isinstance(r, Repository)}
    assert repos["pve-enterprise"].enabled and not repos["proxmox"].enabled
    assert repos["debian"].uris == ("http://ftp.us.debian.org/debian",)


def test_proxmox_needs_a_suite():
    with pytest.raises(BastetError, match="suite"):
        batches_for([ap("proxmox", {})], host(os="Proxmox", physical=True, cpu="Intel"))


def test_subscription_notice_command():
    from bastet.engine.command import Command
    out = [r for b in batches_for([ap("proxmox", {})], pve()) for r in b.resources]
    notice = next(r for r in out if isinstance(r, Command))
    assert "BASTET-NOTICE-OFF" in notice.unless and "pattern not found" in notice.run
    assert "systemctl restart pveproxy.service" in notice.run
    kept = [r for b in batches_for([ap("proxmox", {"subscription_notice": "keep"})], pve()) for r in b.resources]
    assert not any(isinstance(r, Command) for r in kept)


def test_subscription_notice_patch_really_works(tmp_path):
    """Run the patch command's sed on a copy of the real line, then check it's disabled and marked."""
    import subprocess
    from bastet.engine.command import Command
    from bastet.roles import system
    js = tmp_path / "proxmoxlib.js"
    js.write_text("                    if (\n"
                  "                        res.data.status.toLowerCase() !== 'active'\n"
                  "                    ) {\n"
                  "    x = 1; if (res.data.status.toLowerCase() !== 'active') { nag(); }\n")
    cmd = next(r for b in batches_for([ap("proxmox", {})], pve()) for r in b.resources if isinstance(r, Command))
    run = cmd.run.replace(system.PVE_JS, str(js)).replace(" && systemctl restart pveproxy.service", "")
    unless = cmd.unless.replace(system.PVE_JS, str(js))
    assert subprocess.run(["sh", "-c", unless]).returncode != 0
    assert subprocess.run(["sh", "-c", run]).returncode == 0
    text = js.read_text()
    assert "!== 'active'" not in text and text.count("false /* BASTET-NOTICE-OFF */") == 2
    assert subprocess.run(["sh", "-c", unless]).returncode == 0


def test_subscription_notice_fails_loudly_when_proxmox_changes(tmp_path):
    import subprocess
    from bastet.engine.command import Command
    from bastet.roles import system
    js = tmp_path / "proxmoxlib.js"
    js.write_text("something else entirely\n")
    cmd = next(r for b in batches_for([ap("proxmox", {})], pve()) for r in b.resources if isinstance(r, Command))
    r = subprocess.run(["sh", "-c", cmd.run.replace(system.PVE_JS, str(js))], capture_output=True, text=True)
    assert r.returncode != 0 and "pattern not found" in r.stderr


def test_proxmox_node_type_baseline_includes_proxmox():
    from bastet.core.hosttypes import load_host_types
    assert "proxmox" in load_host_types()["proxmox-node"].roles


def test_stray_sources_keep_every_planned_repository():
    from bastet.engine.packages import StraySources
    batches = batches_for([ap("proxmox", {}), ap("packages", {"repositories": [
        {"name": "backports", "uris": ["http://deb.debian.org/debian"], "suites": ["trixie-backports"]}]})], pve())
    stray = next(r for b in batches for r in b.resources if isinstance(r, StraySources))
    assert "backports" in stray.keep and "debian" in stray.keep


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


def test_proxmox_ceph_repository_managed():
    from bastet.engine.packages import Repository
    out = [r for b in batches_for([ap("proxmox", {})], pve()) for r in b.resources]
    ceph = next(r for r in out if isinstance(r, Repository) and r.name == "ceph")
    assert not ceph.enabled and ceph.uris == ("https://enterprise.proxmox.com/debian/ceph-squid",)
    out = [r for b in batches_for([ap("proxmox", {"ceph": "no-subscription"})], pve()) for r in b.resources]
    ceph = next(r for r in out if isinstance(r, Repository) and r.name == "ceph")
    assert ceph.enabled and ceph.uris == ("http://download.proxmox.com/debian/ceph-squid",) and ceph.components == ("no-subscription",)


def test_notice_comes_last_and_hints_at_old_patches():
    from bastet.engine.command import Command
    out = [r for b in batches_for([ap("proxmox", {})], pve()) for r in b.resources]
    assert isinstance(out[-1], Command) and "apt reinstall proxmox-widget-toolkit" in out[-1].run


def test_pacman_settings_fall_back_to_options_section():
    from bastet.engine.files import Line
    out = [r for b in batches_for([ap("pacman", {"parallel_downloads": 4})], host(os="Arch Linux")) for r in b.resources]
    text = "[options]\nHoldPkg = pacman\n\n[core]\nInclude = x\n"
    for r in out:
        if isinstance(r, Line):
            text = r.wanted(text)
    head, core = text.split("[core]")
    assert "Color" in head and "ILoveCandy" in head and "ParallelDownloads = 4" in head and "Color" not in core
