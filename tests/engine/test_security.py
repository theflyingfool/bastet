from pathlib import Path

from bastet.core.shell import ProbeResult
from bastet.engine.security import AppArmorStatus, ListeningPorts, LynisReport, ServiceExposure, VulnerablePackages

FIX = Path(__file__).parent / "fixtures" / "security"


def ok(text):
    return ProbeResult(0, text)


def test_lynis_parses_index_warnings_and_date():
    text = (FIX / "lynis-report.dat").read_text() + "warning[]=SSH-7408|Root can log in|-|-|\n"
    r = LynisReport()
    cur = r.current({"report": ok(text)})
    assert cur["present"] and cur["index"] == 59 and cur["date"] == "2026-10-02 03:20:07"
    assert ("SSH-7408", "Root can log in") in cur["warnings"] and ("PKGS-7392", "Found one or more vulnerable packages.") in cur["warnings"]
    assert len(cur["suggestions"]) == 44  # 52 lines; lynis repeats some, kept once
    assert [c.field for c in r.compare(cur)] == ["warnings"]
    section = r.security_section(cur)
    assert section.startswith("## Lynis") and "59" in section and "SSH-7408" in section and "DEB-0280" in section
    missing = r.current({"report": ok("")})
    assert not missing["present"] and "bastet run applies" in str(r.compare(missing)[0].before)


def test_arch_audit_parses():
    r = VulnerablePackages(tool="arch-audit")
    cur = r.current({"tool": ok("yes"), "scan": ok((FIX / "arch-audit.txt").read_text())})
    assert cur["installed"] and cur["packages"][0] == ("libxml2", "High risk", "CVE-2025-6170, CVE-2025-49796, CVE-2025-49795, CVE-2025-49794", "")
    assert "5 packages" in str(r.compare(cur)[0].before)
    assert "libxml2" in r.security_section(cur) and r.security_section(cur).startswith("## Vulnerable packages")


def test_debsecan_parses():
    r = VulnerablePackages(tool="debsecan")
    cur = r.current({"tool": ok("yes"), "scan": ok((FIX / "debsecan-summary.txt").read_text())})
    assert cur["packages"] == [("libpcre2-8-0", "fixed", "CVE-2026-103111", "")]


def test_missing_tool_is_not_zero_vulnerabilities():
    import pytest
    from bastet.engine.model import Unsupported
    with pytest.raises(Unsupported, match="isn't installed yet"):
        VulnerablePackages(tool="debsecan").current({"tool": ok(""), "scan": ok("")})


def test_exposure_attention_only_for_managed_units():
    r = ServiceExposure(managed=("fail2ban.service", "exim4.service"), target=5.0)
    cur = r.current({"exposure": ok((FIX / "exposure.json").read_text())})
    assert ("dbus.service", 9.3, "UNSAFE") in cur["units"]
    assert [c.before for c in r.compare(cur)] == ["exim4.service exposure 6.9 > 5.0"]
    text = r.security_section(cur)
    assert text.index("exim4.service") < text.index("console-getty.service")  # managed first


def test_exposure_text_fallback():
    cur = ServiceExposure().current({"exposure": ok((FIX / "exposure.txt").read_text())})
    assert ("fail2ban.service", 4.2, "OK") in cur["units"]


def test_listening_ports_unaccounted():
    r = ListeningPorts(accounted=("tcp/22",))
    cur = r.current({"ports": ok((FIX / "ss.txt").read_text() + 'udp UNCONN 0 0 0.0.0.0:5353 0.0.0.0:* users:(("avahi-daemon",pid=9,fd=12))\n')})
    assert ("udp", "0.0.0.0", "5353", "avahi-daemon") in cur["ports"]
    assert r.unaccounted(cur) == [("udp", "0.0.0.0", "5353", "avahi-daemon")]
    assert "1 listening port" in str(r.compare(cur)[0].before)
    assert ListeningPorts(accounted=("tcp/22", "avahi-daemon")).compare(cur) == []


def test_apparmor_status():
    r = AppArmorStatus()
    on = r.current({"apparmor": ok('Y\n{"version": "2", "profiles": {"/usr/sbin/ntpd": "enforce", "lsb_release": "enforce", "nvidia_modprobe": "complain"}}')})
    assert on == {"enabled": True, "enforce": 2, "complain": 1}
    off = r.current({"apparmor": ok("N\n")})
    assert off["enabled"] is False and r.compare(off) == []
    assert "not enabled" in r.security_section(off)


def test_scanner_failure_is_not_none_known():
    import pytest
    from bastet.engine.model import Unsupported
    r = VulnerablePackages(tool="debsecan")
    with pytest.raises(Unsupported, match="scan failed"):
        r.current({"tool": ok("yes"), "scan": ok("error: could not fetch https://security-tracker.debian.org\n@@RC 1")})
    cur = r.current({"tool": ok("yes"), "scan": ok("@@RC 0")})
    assert cur["packages"] == []


def test_exposure_bad_row_doesnt_empty_the_report():
    cur = ServiceExposure().current({"exposure": ok(
        '[{"unit":"a.service","exposure":null,"predicate":"?","happy":""},{"unit":"b.service","exposure":"5.5","predicate":"MEDIUM","happy":":-|"}]')})
    assert cur["units"] == [("b.service", 5.5, "MEDIUM")]


def test_apparmor_profiles_unreadable():
    r = AppArmorStatus()
    cur = r.current({"apparmor": ok("Y\n")})
    assert "profiles not readable" in r.security_section(cur)
