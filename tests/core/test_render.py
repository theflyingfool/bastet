import subprocess
from pathlib import Path

import pytest

from bastet.core.changes import write_changes
from bastet.core.factsnote import facts_path, hardware_facts_path, render_facts, render_hardware_facts
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
    "hosts/pve1.md": "---\nbastet: host\ntype: proxmox\nip: 10.0.10.11\nlocation: \"[[Closet]]\"\n---\n# pve1\n",
    "hosts/git1.md": "---\nbastet: host\ntype: lxc\nruns_on: \"[[pve1]]\"\nip: 10.0.20.21\n---\n# git1\n",
    "hosts/vps1.md": (
        "---\nbastet: host\ntype: vps\nprovider: linode\nip: 203.0.113.10\nlocation: \"[[Linode]]\"\n---\n# vps1\n"
    ),
    "hardware/Supermicro SYS-5019C-MR S123456X.md": (
        "---\nbastet: hardware\ncategory: server\nstatus: in-service\n---\n# m\n"
    ),
    "hardware/WDC WD40EFRX WD-1.md": (
        "---\nbastet: hardware\ncategory: drive\nstatus: in-service\n---\n# d\n"
    ),
    "hardware/Spare WD.md": (
        "---\nbastet: hardware\ncategory: drive\nstatus: spare\n"
        "location: \"[[Closet]]\"\nwarranty_until: 2026-11-01\n---\n# s\n"
    ),
}

FACTS = {
    "pve1": {
        "os": "Debian GNU/Linux 13 (trixie)", "kernel": "6.14.8-2-pve", "cpu": "Intel(R) Xeon(R) E-2236 CPU @ 3.40GHz",
        "cpu_cores": 6, "cpu_threads": 12, "ram": "64 GB", "storage": "9 TB", "gateway": "10.0.10.1", "chassis": "server",
    },
    "git1": {"os": "Debian 13"},
    "vps1": {"os": "Arch Linux", "ram": "1 GB", "virtualization": "kvm", "chassis": "vm"},
}

HW_FACTS = {
    "Supermicro SYS-5019C-MR S123456X": {
        "make": "Supermicro", "model": "SYS-5019C-MR", "serial": "S123456X", "installed_in": "pve1",
        "board": "Supermicro X11SCM-F", "bios": "AMI 3.4 (03/21/2023)", "memory_slots": "2 of 4 used",
        "memory": [{"slot": "DIMMA1", "size": "32 GB"}, {"slot": "DIMMB1", "size": "32 GB"}],
        "oob_address": "10.0.10.9", "oob": {"type": "ipmi", "address": "10.0.10.9"},
    },
    "WDC WD40EFRX WD-1": {
        "model": "WDC WD40EFRX", "serial": "WD-1", "size": "4 TB", "media": "hdd", "interface": "sata",
        "health": "passed", "firmware": "82.00A82", "pool": "tank", "installed_in": "pve1",
    },
}


def write_facts(root: Path, host: str, facts: dict) -> None:
    facts_path(root, host).parent.mkdir(parents=True, exist_ok=True)
    facts_path(root, host).write_text(render_facts(host, facts, "2026-10-06T10:00:00Z"))


def add_facts(root: Path, host: str, extra: dict) -> None:
    """Merge `extra` into a host's existing facts note (for tests exercising one more fact key)."""
    current = parse_document(facts_path(root, host).read_text(), facts_path(root, host))
    from bastet.core.factsnote import META_KEYS

    facts = {k: v for k, v in current.data.items() if k not in META_KEYS}
    write_facts(root, host, {**facts, **extra})


def write_hw_facts(root: Path, item: str, facts: dict) -> Path:
    """A hardware item's facts note -- the gathered side of a hardware item, paired with its own note.

    `installed_in`, if present, is a plain host name; it's linked for you, the way gather itself does.
    """
    from bastet.core.links import make_link

    data = dict(facts)
    if "installed_in" in data:
        data["installed_in"] = make_link(data["installed_in"]) if not str(data["installed_in"]).startswith("[[") else data["installed_in"]
    path = hardware_facts_path(root, item)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_hardware_facts(item, data, "2026-10-06T10:00:00Z"))
    return path


def add_hw_facts(root: Path, item: str, extra: dict) -> None:
    """Merge `extra` into a hardware item's existing facts note."""
    from bastet.core.factsnote import META_KEYS

    current = parse_document(hardware_facts_path(root, item).read_text(), hardware_facts_path(root, item))
    facts = {k: v for k, v in current.data.items() if k not in META_KEYS}
    write_hw_facts(root, item, {**facts, **extra})


@pytest.fixture
def repo(tmp_path) -> GitRepo:
    for rel, text in FILES.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    fact_paths = []
    for host, facts in FACTS.items():
        write_facts(tmp_path, host, facts)
        fact_paths.append(facts_path(tmp_path, host))
    for item, facts in HW_FACTS.items():
        fact_paths.append(write_hw_facts(tmp_path, item, facts))
    r = GitRepo(tmp_path)
    r.init()
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    r.commit([tmp_path / rel for rel in FILES] + fact_paths, "gather: pve1", as_bastet=True)
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
    assert "| [[pve1]] | proxmox |" in text and "Closet" in text
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


def test_guide_explains_the_notes_facts_split(repo):
    changes = {c.path: c for c in generated_changes(inv(repo), TYPES, repo)}
    guide = changes[repo.root / "_bastet" / "Bastet guide.md"].after
    assert "your notes hold what you decide" in guide.lower() and "_bastet/facts/" in guide
    assert "what bastet saw" in guide.lower()


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
    add_hw_facts(repo.root, "Supermicro SYS-5019C-MR S123456X", {
        "interfaces": [{"name": "eno1", "mac": "aa:aa:aa:aa:aa:01"}, {"name": "eno2", "mac": "aa:aa:aa:aa:aa:02"}],
    })
    (repo.root / "hardware" / "pve1 X710.md").write_text('---\nbastet: hardware\ncategory: nic\nstatus: in-service\n---\n# c\n')
    write_hw_facts(repo.root, "pve1 X710", {
        "model": "X710-2", "ports": [{"name": "enp1s0f0"}, {"name": "enp1s0f1"}], "installed_in": "pve1",
    })
    i = inv(repo)
    host = host_summary(i, i.get("pve1"), TYPES, [])
    assert "[!stat] Ports" in host and "**4**" in host and "eno1, eno2, enp1s0f0, enp1s0f1" in host
    machine = hardware_summary(i, i.get("Supermicro SYS-5019C-MR S123456X"))
    assert "[!stat] Network" in machine and "eno1, eno2" in machine


def test_new_category_summaries_and_cards(repo):
    (repo.root / "hardware" / "cpu.md").write_text('---\nbastet: hardware\ncategory: cpu\nstatus: in-service\n---\n')
    write_hw_facts(repo.root, "cpu", {
        "model": "AMD Ryzen 9 5950X 16-Core Processor", "cores": 16, "threads": 32, "socket": "AM4", "installed_in": "pve1",
    })
    (repo.root / "hardware" / "psu.md").write_text('---\nbastet: hardware\ncategory: psu\nstatus: in-service\n---\n')
    write_hw_facts(repo.root, "psu", {"model": "PWS-504P-1R", "max_power": "500 W", "installed_in": "pve1"})
    (repo.root / "hardware" / "dimm.md").write_text('---\nbastet: hardware\ncategory: memory\nstatus: in-service\n---\n')
    write_hw_facts(repo.root, "dimm", {"model": "M391A4G43MB1-CTD", "size": "32 GB", "type": "DDR4", "slot": "DIMMA1", "installed_in": "pve1"})
    (repo.root / "hardware" / "stick.md").write_text('---\nbastet: hardware\ncategory: usb\nstatus: in-service\n---\n')
    write_hw_facts(repo.root, "stick", {"model": "ConBee II", "usb_id": "1cf1:0030", "installed_in": "pve1"})
    add_facts(repo.root, "pve1", {"bridges": [{"name": "vmbr0", "ports": ["eno1"]}]})
    add_hw_facts(repo.root, "Supermicro SYS-5019C-MR S123456X", {"boot": "uefi", "tpm": "TPM 2.0", "secure_boot": "disabled"})
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
    git1.write_text(git1.read_text().replace("ip: 10.0.20.21\n", "ip: 10.0.20.21\nnotes: [unclosed\n"))
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
        '---\nbastet: hardware\ncategory: laptop\nstatus: in-service\n---\n# x\n')
    write_hw_facts(repo.root, "HP Spectre 5CD", {"make": "HP", "model": "Spectre x360", "installed_in": "vps1"})
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
        '---\nbastet: hardware\ncategory: gateway\nstatus: in-service\n---\n# g\n')
    write_hw_facts(repo.root, "Ubiquiti Gateway Fiber X", {"make": "Ubiquiti", "model": "Gateway Fiber"})
    (repo.root / "hardware" / "HP Spectre 5CD.md").write_text(
        '---\nbastet: hardware\ncategory: laptop\nstatus: in-service\n---\n# x\n')
    write_hw_facts(repo.root, "HP Spectre 5CD", {"make": "HP", "model": "HP Spectre x360"})
    hardware = dashboard(inv(repo), TYPES, {}, [])
    hardware = hardware[hardware.index("## Hardware"):]
    assert "[[Ubiquiti Gateway Fiber X]]" in hardware and "| HP Spectre x360 |" in hardware


def test_where_map_runs_top_down(repo):
    from bastet.core.maps import where_map
    assert "flowchart TB" in where_map(inv(repo))


def test_summary_links_security_note_and_deleted_hosts_lose_theirs(repo):
    sec = repo.root / "_bastet" / "reports"
    sec.mkdir(parents=True)
    (sec / "pve1 reports.md").write_text('---\nsecurity_of: "[[pve1]]"\nchecked: 2026-10-02 10:00\n---\n## Lynis\n')
    (sec / "gone reports.md").write_text('---\nsecurity_of: "[[gone]]"\nchecked: x\n---\n')
    text = host_summary(inv(repo), inv(repo).get("pve1"), TYPES, [])
    assert "[[pve1 reports|security report]]" in text and "2026-10-02 10:00" in text
    removed = [c.path.name for c in generated_changes(inv(repo), TYPES, repo) if c.after is None]
    assert "gone reports.md" in removed and "pve1 reports.md" not in removed


def test_summary_ends_with_facts_link(repo):
    text = host_summary(inv(repo), inv(repo).get("pve1"), TYPES, [])
    assert text.rstrip("\n").endswith("Facts: [[pve1 facts|gathered facts]]")


def test_summary_has_no_facts_link_for_a_never_gathered_host(repo):
    """A host added but never gathered has no facts note yet -- an unresolved `Facts:` link would make
    Obsidian create `<host> facts.md` the moment anyone clicks it, pre-empting the one gather writes."""
    p = repo.root / "hosts" / "new.md"
    p.write_text('---\nbastet: host\ntype: server\nip: 10.0.10.50\n---\n# new\n')
    subprocess.run(["git", "-C", str(repo.root), "add", "."], check=True)
    repo.commit([p], "add new", as_bastet=True)
    text = host_summary(inv(repo), inv(repo).get("new"), TYPES, [])
    assert "Facts:" not in text


def test_roles_index_generated_and_linked(repo):
    changes = {c.path.relative_to(repo.root).as_posix(): c for c in generated_changes(inv(repo), TYPES, repo)}
    assert "_bastet/Roles.md" in changes and "| Role | What it does | Used by |" in changes["_bastet/Roles.md"].after
    assert "[[_bastet/Roles|" in dashboard(inv(repo), TYPES, {}, [])
