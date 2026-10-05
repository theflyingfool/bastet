import json

from bastet.core.collect import PROBES, Snapshot, collect, save_snapshot
from bastet.core.remote import LocalRunner
from bastet.core.shell import MARK, Probe, ProbeResult, build_script, parse_sections


def test_probe_names_unique_and_required_set():
    names = [p.name for p in PROBES]
    assert len(names) == len(set(names))
    assert {p.name for p in PROBES if p.required} >= {"os_release", "uname", "lscpu", "meminfo", "lsblk", "ip_addr"}


def test_script_runs_locally_and_marks_missing_tools():
    probes = (
        Probe("greet", "echo hello", "echo"),
        Probe("nope", "definitely-not-a-real-command-xyz", "nope"),
        Probe("multi", "printf 'a\\nb\\n'", "printf"),
    )
    snap = collect(LocalRunner(), "testhost", probes)
    assert snap.results["greet"] == ProbeResult(0, "hello")
    assert snap.results["nope"].missing
    assert snap.results["multi"].output == "a\nb"
    assert snap.host == "testhost" and snap.runner == "local"


def test_parse_sections():
    out = f"{MARK} a 0\nline1\nline2\n{MARK} b 1\n\n"
    assert parse_sections(out) == {"a": ProbeResult(0, "line1\nline2"), "b": ProbeResult(1, "")}


def test_build_script_has_every_probe():
    script = build_script(PROBES)
    for p in PROBES:
        assert f"'{p.name}'" in script


def test_save_snapshot(tmp_path):
    snap = Snapshot("vps1", "bastet@h", "2026-10-01T12:00:00Z", {"a": ProbeResult(0, "x")})
    path = save_snapshot(snap, tmp_path)
    assert path.parent == tmp_path / "snapshots" / "vps1"
    data = json.loads(path.read_text())
    assert data["results"]["a"] == {"returncode": 0, "output": "x"} and data["runner"] == "bastet@h"


def test_forged_markers_in_output_are_ignored():
    probes = (
        Probe("evil", "printf '@@BASTET@@ uname 0\\nfake\\n'", "printf"),
        Probe("after", "echo ok", "echo"),
    )
    snap = collect(LocalRunner(), "h", probes)
    assert set(snap.results) == {"evil", "after"}
    assert "fake" in snap.results["evil"].output and snap.results["after"].output == "ok"


def test_root_probe_without_sudo_is_denied_not_hung():
    import os
    probes = (Probe("who", "id -u", "id", root=True), Probe("privilege", 'echo "${SUDO:-root}"', "sudo"))
    snap = collect(LocalRunner(), "h", probes)
    priv = snap.results["privilege"].output
    assert priv in ("root", "sudo -n", "none")
    if priv == "none":
        assert snap.results["who"].denied and snap.results["who"].output == ""
    else:
        assert snap.results["who"].output == "0" or os.geteuid() == 0


def test_root_probe_command_is_quoted_safely():
    script = build_script((Probe("q", "printf '%s' \"it's\"", "printf", root=True),))
    import subprocess
    subprocess.run(["sh", "-n"], input=script, text=True, check=True)


def test_new_probes_present():
    names = {p.name for p in PROBES}
    assert {"privilege", "dmidecode", "smart", "lspci", "net_sysfs", "ipmi", "zpool", "disk_ids", "pve_guests"} <= names
    assert {p.name for p in PROBES if p.root} == {"dmidecode", "smart", "ipmi", "pve_guests", "pve_guest_conf", "ipmi_fru", "ipmi_mc"}


def test_smart_probe_skips_standby_disks_and_builds_valid_json():
    [smart] = [p for p in PROBES if p.name == "smart"]
    assert "-n standby" in smart.command and 'if [ -n "$o" ]' in smart.command


def test_ipmi_probe_loads_modules_first():
    [ipmi] = [p for p in PROBES if p.name == "ipmi"]
    assert ipmi.command.startswith("modprobe ipmi_devintf ipmi_si") and ipmi.root
    assert any(p.name == "ipmi_dev" for p in PROBES)


def test_completeness_probes_present():
    import subprocess
    names = {p.name: p for p in PROBES}
    for n in ("ip_link", "ipmi_fru", "ipmi_mc", "ethtool", "usb", "firmware"):
        assert n in names, n
    assert names["ipmi_fru"].root and names["ipmi_mc"].root and not names["usb"].root
    assert ",39" in names["dmidecode"].command
    subprocess.run(["sh", "-n"], input=build_script(PROBES), text=True, check=True)


def test_firmware_probe_succeeds_without_secure_boot_variable(tmp_path):
    import subprocess
    probe = {p.name: p for p in PROBES}["firmware"]
    command = probe.command.replace("/sys/firmware/efi/efivars", str(tmp_path / "none"))
    r = subprocess.run(["sh", "-c", command], capture_output=True, text=True)
    assert r.returncode == 0 and "boot=" in r.stdout


def test_prelude_puts_sbin_on_path_for_normal_users():
    """Debian keeps ethtool, smartctl and friends in /usr/sbin, which isn't on a normal user's PATH."""
    import subprocess
    from bastet.core.shell import PRELUDE
    out = subprocess.run(["sh", "-c", PRELUDE + '\necho "$PATH"'], capture_output=True, text=True,
                         env={"PATH": "/usr/bin:/bin"}).stdout.strip().split(":")
    assert out[:2] == ["/usr/bin", "/bin"] and {"/usr/local/sbin", "/usr/sbin", "/sbin"} <= set(out)
