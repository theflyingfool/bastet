import subprocess

from bastet.core.hostkeys import check, parse_keyscan, preferred, record, write_known_hosts


def test_fingerprint_matches_ssh_keygen(tmp_path):
    key = tmp_path / "k"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
    ktype, blob = (tmp_path / "k.pub").read_text().split()[:2]
    expected = subprocess.run(["ssh-keygen", "-lf", str(tmp_path / "k.pub")], capture_output=True, text=True).stdout.split()[1]
    [hk] = parse_keyscan(f"# comment\nhost {ktype} {blob}\n")
    assert hk.type == "ssh-ed25519" and hk.fingerprint == expected


def test_parse_skips_junk():
    assert parse_keyscan("garbage\nhost ssh-rsa !!notbase64!!\n") == []


def test_preferred_and_record():
    keys = parse_keyscan("h ssh-rsa QUFBQQ==\nh ssh-ed25519 QkJCQg==\n")
    assert preferred(keys).type == "ssh-ed25519"
    assert record(preferred(keys)).startswith("ssh-ed25519 SHA256:")


def test_check():
    keys = parse_keyscan("h ssh-ed25519 QkJCQg==\n")
    assert check(None, keys) == "new"
    assert check(record(keys[0]), keys) == "match"
    assert check("ssh-ed25519 SHA256:other", keys) == "changed"


def test_write_known_hosts(tmp_path):
    keys = parse_keyscan("h ssh-ed25519 QkJCQg==\n")
    p = write_known_hosts(keys, "203.0.113.10", 22, tmp_path)
    assert p.read_text() == "203.0.113.10 ssh-ed25519 QkJCQg==\n"
    p2 = write_known_hosts(keys, "203.0.113.10", 2222, tmp_path / "x")
    assert p2.read_text().startswith("[203.0.113.10]:2222 ")


def test_pinned_keys_only_the_recorded_one():
    from bastet.core.hostkeys import pinned

    keys = parse_keyscan("h ssh-ed25519 QkJCQg==\nh ssh-rsa QUFBQQ==\n")
    real = keys[0]
    assert pinned(record(real), keys) == [real]
    rsa_only = parse_keyscan("h ssh-rsa QUFBQQ==\n")
    assert pinned(record(keys[1]), keys) == rsa_only
    assert pinned("ssh-ed25519 SHA256:nope", keys) == []


import pytest

import bastet.core.hostkeys as hk
from bastet.core.errors import Unreachable

ED = "h ssh-ed25519 QkJCQg=="
RSA = "h ssh-rsa QUFBQQ=="
BANNER = "# h:22 SSH-2.0-OpenSSH_10.0"


def fake_keyscan(monkeypatch, by_type: dict[str, str], *, answered=True):
    calls = []

    def run(cmd, *a, **k):
        types = cmd[cmd.index("-t") + 1]
        calls.append(types)
        out = (BANNER + "\n" if answered else "") + "\n".join(by_type.get(t, "") for t in types.split(","))
        return subprocess.CompletedProcess(cmd, 0, out, "")

    monkeypatch.setattr(hk.shutil, "which", lambda name: "/usr/bin/ssh-keyscan")
    monkeypatch.setattr(hk.subprocess, "run", run)
    return calls


def test_scan_new_host_asks_for_ed25519_only(monkeypatch):
    calls = fake_keyscan(monkeypatch, {"ed25519": ED, "rsa": RSA})
    keys = hk.scan("h")
    assert calls == ["ed25519"] and [k.type for k in keys] == ["ssh-ed25519"]


def test_scan_falls_back_when_no_ed25519(monkeypatch):
    calls = fake_keyscan(monkeypatch, {"rsa": RSA})
    assert [k.type for k in hk.scan("h")] == ["ssh-rsa"]
    assert calls == ["ed25519", "ecdsa,rsa"]


def test_scan_recorded_type_only(monkeypatch):
    calls = fake_keyscan(monkeypatch, {"ed25519": ED, "rsa": RSA})
    hk.scan("h", recorded="ssh-rsa SHA256:x")
    assert calls == ["rsa"]


def test_scan_recorded_type_gone_scans_all_so_change_is_visible(monkeypatch):
    calls = fake_keyscan(monkeypatch, {"ed25519": ED})
    keys = hk.scan("h", recorded="ssh-rsa SHA256:x")
    assert calls == ["rsa", "ed25519,ecdsa,rsa"] and keys[0].type == "ssh-ed25519"


def test_nothing_answered_is_one_attempt_with_clear_message(monkeypatch):
    calls = fake_keyscan(monkeypatch, {}, answered=False)
    with pytest.raises(Unreachable) as e:
        hk.scan("h")
    assert calls == ["ed25519"]
    assert "nothing answered on port 22" in str(e.value) and "fail2ban" in str(e.value)
