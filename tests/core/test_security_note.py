from bastet.core.security_note import security_note
from bastet.engine.run import Item
from bastet.engine.security import AppArmorStatus, ListeningPorts, LynisReport, ServiceExposure, VulnerablePackages


def item(resource, current=None, status="compliant", error=None):
    return Item(resource, ["harden"], [], status=status, current=current or {}, error=error)


def test_security_note_sections_in_order():
    items = [
        item(AppArmorStatus(), {"enabled": True, "enforce": 3, "complain": 0}),
        item(ListeningPorts(accounted=("tcp/22",)), {"ports": [("tcp", "0.0.0.0", "22", "sshd")]}),
        item(LynisReport(), {"present": True, "date": "2026-10-02 03:20:07", "index": 59, "version": "3.1.4",
                             "warnings": [], "suggestions": []}),
        item(VulnerablePackages(tool="debsecan"), {"installed": True, "packages": []}),
        item(ServiceExposure(), {"units": [("ssh.service", 9.6, "UNSAFE")]}),
    ]
    text = security_note("pve1", items, "2026-10-02 10:00")
    assert text.startswith('---\nsecurity_of: "[[pve1]]"\nchecked: 2026-10-02 10:00\n---\n')
    order = [text.index(h) for h in ("## Lynis", "## Vulnerable packages", "## Service exposure", "## Listening ports", "## AppArmor")]
    assert order == sorted(order) and "Hardening index **59**" in text


def test_failed_report_shows_not_read():
    text = security_note("pve1", [item(VulnerablePackages(tool="debsecan"), status="skipped",
                                       error="debsecan isn't installed yet (apply installs it)")], "now")
    assert "## Vulnerable packages\n\n_not read: debsecan isn't installed yet (apply installs it)_" in text
