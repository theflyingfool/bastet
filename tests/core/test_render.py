import subprocess
from pathlib import Path

import pytest

from bastet.core.changes import write_changes
from bastet.core.frontmatter import parse_document
from bastet.core.gitrepo import GitRepo
from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from bastet.core.render import (
    DASHBOARD_PATH, dashboard, generated_changes, hardware_summary, host_summary, short_cpu, summary_path,
)

TYPES = load_host_types()

FILES = {
    "Homelab.md": "---\nbastet: lab\nname: Homelab\ndomains:\n  public: example.com\n---\n# Homelab\n",
    "locations/Closet.md": "---\nbastet: location\n---\n# Closet\n",
    "locations/Linode.md": "---\nbastet: location\n---\n# Linode\n",
    "hosts/pve1.md": (
        "---\nbastet: host\ntype: proxmox-node\nip: 10.0.10.11\nlocation: \"[[Closet]]\"\nos: Debian GNU/Linux 13 (trixie)\n"
        "kernel: 6.14.8-2-pve\ncpu: Intel(R) Xeon(R) E-2236 CPU @ 3.40GHz\ncpu_cores: 6\ncpu_threads: 12\nram: 64 GB\n"
        "storage: 9 TB\ngateway: 10.0.10.1\nchassis: server\n---\n# pve1\n"
    ),
    "hosts/git1.md": "---\nbastet: host\ntype: lxc\nruns_on: \"[[pve1]]\"\nip: 10.0.20.21\nos: Debian 13\n---\n# git1\n",
    "hosts/vps1.md": (
        "---\nbastet: host\ntype: vps\nprovider: linode\nip: 203.0.113.10\nlocation: \"[[Linode]]\"\nos: Arch Linux\n"
        "ram: 1 GB\nvirtualization: kvm\nchassis: vm\n---\n# vps1\n"
    ),
    "hardware/Supermicro SYS-5019C-MR S123456X.md": (
        "---\nbastet: hardware\ncategory: server\nmake: Supermicro\nmodel: SYS-5019C-MR\nserial: S123456X\nstatus: in-service\n"
        "installed_in: \"[[pve1]]\"\nboard: Supermicro X11SCM-F\nbios: AMI 3.4 (03/21/2023)\nmemory_slots: 2 of 4 used\n"
        "memory:\n  - slot: DIMMA1\n    size: 32 GB\n  - slot: DIMMB1\n    size: 32 GB\noob_address: 10.0.10.9\n"
        "oob:\n  type: ipmi\n  address: 10.0.10.9\n---\n# m\n"
    ),
    "hardware/WDC WD40EFRX WD-1.md": (
        "---\nbastet: hardware\ncategory: drive\nmodel: WDC WD40EFRX\nserial: WD-1\nsize: 4 TB\nmedia: hdd\ninterface: sata\n"
        "health: passed\nfirmware: 82.00A82\npool: tank\nstatus: in-service\ninstalled_in: \"[[pve1]]\"\n---\n# d\n"
    ),
    "hardware/Spare WD.md": (
        "---\nbastet: hardware\ncategory: drive\nmodel: WDC WD40EFRX\nserial: WD-2\nsize: 4 TB\nstatus: spare\n"
        "location: \"[[Closet]]\"\nwarranty_until: 2026-11-01\n---\n# s\n"
    ),
}


@pytest.fixture
def repo(tmp_path) -> GitRepo:
    for rel, text in FILES.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    r = GitRepo(tmp_path)
    r.init()
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    r.commit([tmp_path / rel for rel in FILES], "gather: pve1", as_bastet=True)
    return r


def inv(repo):
    return load_inventory(repo.root, TYPES)


def test_short_cpu():
    assert short_cpu("Intel(R) Core(TM) i7-7500U CPU @ 2.70GHz") == "Intel Core i7-7500U"
    assert short_cpu("AMD EPYC 7713 64-Core Processor") == "AMD EPYC 7713 64-Core"


def test_host_summary_cards_and_warnings(repo):
    i = inv(repo)
    text = host_summary(i, i.get("pve1"), TYPES, ["ram: file says 128 GB, observed 64 GB"])
    doc = parse_document(text, Path("x.md"))
    assert doc.data["generated"] is True and doc.data["warnings"] == ["ram: file says 128 GB, observed 64 GB"]
    for card in ("[!stat] OS", "[!stat] CPU", "[!stat] RAM", "[!stat] Storage", "[!stat] Network",
                 "[!stat] Machine", "[!stat] Out-of-band", "[!stat] Guests"):
        assert card in text, card
    assert "**Intel Xeon E-2236**" in text and "6 cores · 12 threads" in text
    assert "2 of 4 used" in text and "10.0.10.9" in text and "[[git1]]" in text
    assert "[!warning]" in text and "128 GB" in text


def test_virtual_host_has_no_machine_cards(repo):
    i = inv(repo)
    text = host_summary(i, i.get("vps1"), TYPES, [])
    assert "[!stat] Machine" not in text and "[!stat] Guests" not in text and "[!warning]" not in text
    assert "kvm" in text


def test_hardware_summaries(repo):
    i = inv(repo)
    machine = hardware_summary(i, i.get("Supermicro SYS-5019C-MR S123456X"))
    assert "[!stat] Memory" in machine and "64 GB" in machine and "[!stat] Out-of-band" in machine
    drive = hardware_summary(i, i.get("WDC WD40EFRX WD-1"))
    assert "[!stat] Health" in drive and "passed" in drive and "tank" in drive and "[[pve1]]" in drive


def test_dashboard(repo):
    i = inv(repo)
    text = dashboard(i, TYPES, {"pve1": ["ram mismatch"]}, ["`2026-10-01` gather: pve1"])
    assert "[!stat] Hosts" in text and "**3**" in text
    assert "## Needs attention" in text and "ram mismatch" in text
    assert "```mermaid" not in text  # maps are embedded notes now, not inline graphs
    assert "## Hosts" in text and "| [[git1]] | lxc | Debian 13 | 10.0.20.21 | on [[pve1]] |" in text
    assert "| [[pve1]] | proxmox-node |" in text and "Closet" in text
    assert "example.com" in text and "Spare WD" in text and "10.0.10.9" in text
    assert "gather: pve1" in text


def test_generated_changes_idempotent_and_keep_warnings(repo):
    first = generated_changes(inv(repo), TYPES, repo, warnings={"pve1": ["ram mismatch"]})
    paths = {c.path for c in first}
    assert summary_path(repo.root, "pve1") in paths and repo.root / DASHBOARD_PATH in paths
    assert summary_path(repo.root, "Spare WD") in paths
    write_changes(first)
    repo.commit([c.path for c in first], "refresh: views")
    assert generated_changes(inv(repo), TYPES, repo) == []
    kept = parse_document(summary_path(repo.root, "pve1").read_text(), Path("x"))
    assert kept.data["warnings"] == ["ram mismatch"]


def test_recent_changes_ignore_refresh_commits(repo):
    first = generated_changes(inv(repo), TYPES, repo)
    write_changes(first)
    repo.commit([c.path for c in first], "refresh: views")
    text = (repo.root / DASHBOARD_PATH).read_text()
    assert "gather: pve1" in text and "refresh:" not in text


def test_guide_generated_and_linked(repo):
    changes = {c.path: c for c in generated_changes(inv(repo), TYPES, repo)}
    guide = changes[repo.root / "_bastet" / "Bastet guide.md"].after
    assert "generated: true" in guide and "bastet gather" in guide and "bastet refresh" in guide
    assert "[[Bastet guide]]" in changes[repo.root / DASHBOARD_PATH].after


def test_mermaid_ids_safe_and_distinct(repo):
    from bastet.core.maps import where_map
    for name in ("end", "web-1", "web.1"):
        (repo.root / "hosts" / f"{name}.md").write_text(f"---\nbastet: host\ntype: unknown\n---\n# {name}\n")
    text = where_map(inv(repo))
    mermaid = text[text.index("```mermaid"):]
    ids = [line.split("[")[0].strip() for line in mermaid.splitlines() if '["' in line and "subgraph" not in line]
    assert len(ids) == len(set(ids)) and "end" not in ids


def test_newlines_flattened_in_warnings_and_cells(repo):
    i = inv(repo)
    text = host_summary(i, i.get("pve1"), TYPES, ["line one\nline two | piped"])
    assert "> - line one line two \\| piped" in text
    dash = dashboard(i, TYPES, {"pve1": ["a\nb"]}, [])
    assert "| #warn | [[pve1]] | a b |" in dash


def test_installed_snippet_is_kept_current(repo):
    snippet = repo.root / ".obsidian" / "snippets" / "bastet.css"
    snippet.parent.mkdir(parents=True)
    snippet.write_text("/* old */\n")
    changes = {c.path: c for c in generated_changes(inv(repo), TYPES, repo)}
    assert '#drift' in changes[snippet].after
    snippet.unlink()
    assert snippet not in {c.path for c in generated_changes(inv(repo), TYPES, repo)}


def test_ports_shown_on_host_and_machine_pages(repo):
    m = repo.root / "hardware" / "Supermicro SYS-5019C-MR S123456X.md"
    m.write_text(m.read_text().replace("oob_address:", "interfaces:\n  - name: eno1\n    mac: aa:aa:aa:aa:aa:01\n  - name: eno2\n    mac: aa:aa:aa:aa:aa:02\noob_address:"))
    (repo.root / "hardware" / "pve1 X710.md").write_text(
        '---\nbastet: hardware\ncategory: nic\nmodel: X710-2\nports:\n  - name: enp1s0f0\n  - name: enp1s0f1\n'
        'status: in-service\ninstalled_in: "[[pve1]]"\n---\n# c\n')
    i = inv(repo)
    host = host_summary(i, i.get("pve1"), TYPES, [])
    assert "[!stat] Ports" in host and "**4**" in host and "eno1, eno2, enp1s0f0, enp1s0f1" in host
    machine = hardware_summary(i, i.get("Supermicro SYS-5019C-MR S123456X"))
    assert "[!stat] Network" in machine and "eno1, eno2" in machine


def test_new_category_summaries_and_cards(repo):
    (repo.root / "hardware" / "cpu.md").write_text('---\nbastet: hardware\ncategory: cpu\nmodel: AMD Ryzen 9 5950X 16-Core Processor\ncores: 16\nthreads: 32\nsocket: AM4\nstatus: in-service\ninstalled_in: "[[pve1]]"\n---\n')
    (repo.root / "hardware" / "psu.md").write_text('---\nbastet: hardware\ncategory: psu\nmodel: PWS-504P-1R\nmax_power: 500 W\nstatus: in-service\ninstalled_in: "[[pve1]]"\n---\n')
    (repo.root / "hardware" / "dimm.md").write_text('---\nbastet: hardware\ncategory: memory\nmodel: M391A4G43MB1-CTD\nsize: 32 GB\ntype: DDR4\nslot: DIMMA1\nstatus: in-service\ninstalled_in: "[[pve1]]"\n---\n')
    (repo.root / "hardware" / "stick.md").write_text('---\nbastet: hardware\ncategory: usb\nmodel: ConBee II\nusb_id: 1cf1:0030\nstatus: in-service\ninstalled_in: "[[pve1]]"\n---\n')
    h = repo.root / "hosts" / "pve1.md"
    h.write_text(h.read_text().replace("chassis: server\n", "chassis: server\nbridges:\n  - name: vmbr0\n    ports:\n      - eno1\n"))
    m = repo.root / "hardware" / "Supermicro SYS-5019C-MR S123456X.md"
    m.write_text(m.read_text().replace("oob_address:", "boot: uefi\ntpm: TPM 2.0\nsecure_boot: disabled\noob_address:"))
    i = inv(repo)
    cpu = hardware_summary(i, i.get("cpu"))
    assert "[!stat] CPU" in cpu and "AMD Ryzen 9 5950X 16-Core" in cpu and "16 cores · 32 threads" in cpu
    assert "500 W" in hardware_summary(i, i.get("psu"))
    assert "[!stat] Memory" in hardware_summary(i, i.get("dimm")) and "DIMMA1" in hardware_summary(i, i.get("dimm"))
    assert "1cf1:0030" in hardware_summary(i, i.get("stick"))
    machine = hardware_summary(i, i.get("Supermicro SYS-5019C-MR S123456X"))
    assert "[!stat] Firmware" in machine and "UEFI" in machine and "Secure Boot disabled" in machine
    host = host_summary(i, i.get("pve1"), TYPES, [])
    assert "[!stat] Bridges" in host and "vmbr0" in host


def test_summary_of_deleted_host_is_removed(repo):
    write_changes(generated_changes(inv(repo), TYPES, repo))
    stale = summary_path(repo.root, "git1")
    assert stale.exists()
    (repo.root / "hosts" / "git1.md").unlink()
    (repo.root / "_bastet" / "summary" / "notes.md").write_text("my own note\n")
    changes = generated_changes(inv(repo), TYPES, repo)
    gone = [c for c in changes if c.after is None]
    assert [c.path for c in gone] == [stale]


def test_host_summary_lists_ports(repo):
    (repo.root / "hosts" / "nas.md").write_text(
        '---\nbastet: host\ntype: server\nlinks:\n  - {port: eno1, to: "[[pve1]]", to_port: "7"}\n---\n# nas\n')
    text = host_summary(inv(repo), inv(repo).get("pve1"), TYPES, [])
    assert "## Ports" in text and "| 7 | [[nas]] eno1 |" in text


def test_maps_are_generated(repo):
    (repo.root / "hosts" / "nas.md").write_text(
        '---\nbastet: host\ntype: server\nlinks:\n  - {port: eno1, to: "[[pve1]]", to_port: "3"}\n---\n# nas\n')
    paths = {c.path.relative_to(repo.root).as_posix() for c in generated_changes(inv(repo), TYPES, repo)}
    assert "_bastet/maps/Cabling.md" in paths


def test_broken_host_file_keeps_its_summary(repo):
    write_changes(generated_changes(inv(repo), TYPES, repo))
    git1 = repo.root / "hosts" / "git1.md"
    git1.write_text(git1.read_text().replace("os: Debian 13\n", "os: Debian 13\nnotes: [unclosed\n"))
    assert [c for c in generated_changes(inv(repo), TYPES, repo) if c.after is None] == []


def test_os_groups_generated_for_seen_oses(repo):
    paths = {c.path.relative_to(repo.root).as_posix(): c for c in generated_changes(inv(repo), TYPES, repo)}
    debian = paths["_bastet/groups/debian.md"].after
    assert "bastet: group" in debian and "os: debian" in debian
    assert "_bastet/groups/arch.md" in paths  # vps1 is Arch Linux in this fixture


def test_generated_group_removed_when_user_note_takes_the_name(repo):
    write_changes(generated_changes(inv(repo), TYPES, repo))
    gen = repo.root / "_bastet" / "groups" / "debian.md"
    assert gen.exists()
    (repo.root / "hosts" / "debian.md").write_text("---\nbastet: host\ntype: unknown\n---\n# debian\n")
    gone = [c.path for c in generated_changes(inv(repo), TYPES, repo) if c.after is None]
    assert gen in gone


def test_dashboard_lists_every_machine_spares_and_embeds_maps(repo):
    (repo.root / "hardware" / "HP Spectre 5CD.md").write_text(
        '---\nbastet: hardware\ncategory: laptop\nmake: HP\nmodel: Spectre x360\nstatus: in-service\ninstalled_in: "[[vps1]]"\n---\n# x\n')
    (repo.root / "hosts" / "nas.md").write_text(
        '---\nbastet: host\ntype: server\nlinks:\n  - {port: eno1, to: "[[pve1]]", to_port: "3"}\n---\n# nas\n')
    text = dashboard(inv(repo), TYPES, {}, [])
    hardware = text[text.index("## Hardware"):]
    assert "[[HP Spectre 5CD]]" in hardware and "laptop" in hardware
    assert "## Spares" in text and "[[Spare WD]]" in text[text.index("## Spares"):]
    assert "![[_bastet/maps/Cabling]]" in text and "[[_bastet/maps/Where|" in text


def test_where_map_is_generated(repo):
    paths = {c.path.relative_to(repo.root).as_posix() for c in generated_changes(inv(repo), TYPES, repo)}
    assert "_bastet/maps/Where.md" in paths


def test_hardware_table_includes_network_devices_without_repeating_the_make(repo):
    (repo.root / "hardware" / "Ubiquiti Gateway Fiber X.md").write_text(
        '---\nbastet: hardware\ncategory: gateway\nmake: Ubiquiti\nmodel: Gateway Fiber\nstatus: in-service\n---\n# g\n')
    (repo.root / "hardware" / "HP Spectre 5CD.md").write_text(
        '---\nbastet: hardware\ncategory: laptop\nmake: HP\nmodel: HP Spectre x360\nstatus: in-service\n---\n# x\n')
    hardware = dashboard(inv(repo), TYPES, {}, [])
    hardware = hardware[hardware.index("## Hardware"):]
    assert "[[Ubiquiti Gateway Fiber X]]" in hardware and "| HP Spectre x360 |" in hardware
