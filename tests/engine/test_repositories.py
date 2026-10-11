import pytest

from bastet.core.shell import ProbeResult
from bastet.engine.model import Unsupported
from bastet.engine.packages import Repository

KEY = "-----BEGIN PGP PUBLIC KEY BLOCK-----\n\nmQINBGexample\n=abcd\n-----END PGP PUBLIC KEY BLOCK-----\n"
ABSENT_FILE = ProbeResult(0, "absent")


def results_for(repo, manager, files=None):
    """Every read answered: the manager, and every part's file read as absent unless given."""
    out = {}
    for r in repo.reads():
        out[r.name] = ProbeResult(0, manager) if r.name == "manager" else (files or {}).get(r.name, ABSENT_FILE)
    return out


def contents(repo, manager):
    current = repo.current(results_for(repo, manager))
    return {p.path: getattr(p, "content", None) or getattr(p, "block", None) or getattr(p, "line", None)
            for p in repo.parts(manager)}, current


def test_apt_deb822_with_inline_key_and_options():
    repo = Repository(name="docker", uris=("https://download.docker.com/linux/debian",), suites=("trixie",),
                      components=("stable",), architectures=("amd64",), key=KEY, options=(("X-Repolib-Name", "Docker"),))
    files, _ = contents(repo, "apt-get")
    assert files["/etc/apt/sources.list.d/docker.sources"] == (
        "Types: deb\nURIs: https://download.docker.com/linux/debian\nSuites: trixie\nComponents: stable\n"
        "Architectures: amd64\nSigned-By:\n -----BEGIN PGP PUBLIC KEY BLOCK-----\n .\n mQINBGexample\n =abcd\n"
        " -----END PGP PUBLIC KEY BLOCK-----\nX-Repolib-Name: Docker\n"
    )
    off = Repository(name="x", uris=("http://example.com/debian",), suites=("stable",), enabled=False, trusted=True,
                     signed_by="/usr/share/keyrings/x.gpg")
    assert "Enabled: no\nTrusted: yes\nSigned-By: /usr/share/keyrings/x.gpg\n" in contents(off, "apt-get")[0]["/etc/apt/sources.list.d/x.sources"]


def test_dnf_and_zypper_ini_with_key_file():
    repo = Repository(name="tailscale", uris=("https://pkgs.tailscale.com/stable/fedora/$basearch",), key=KEY,
                      options=(("repo_gpgcheck", "1"),))
    files, _ = contents(repo, "dnf")
    assert files["/etc/yum.repos.d/tailscale.repo"] == (
        "[tailscale]\nname=tailscale\nbaseurl=https://pkgs.tailscale.com/stable/fedora/$basearch\nenabled=1\n"
        "gpgcheck=1\ngpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-bastet-tailscale\nrepo_gpgcheck=1\n"
    )
    assert files["/etc/pki/rpm-gpg/RPM-GPG-KEY-bastet-tailscale"] == KEY
    assert "/etc/zypp/repos.d/tailscale.repo" in contents(repo, "zypper")[0]
    with pytest.raises(ValueError):
        Repository(name="two", uris=("http://a", "http://b")).parts("zypper")


def test_apk_lines_and_key():
    repo = Repository(name="edge", uris=("https://dl-cdn.alpinelinux.org/alpine/edge/testing",), key="-----BEGIN PUBLIC KEY-----\nMIIB\n-----END PUBLIC KEY-----\n")
    parts = repo.parts("apk")
    assert [type(p).__name__ for p in parts] == ["Line", "File"] and parts[1].path == "/etc/apk/keys/edge.rsa.pub"


def test_change_names_and_fix_for_detected_manager_only():
    repo = Repository(name="b", uris=("http://deb.debian.org/debian",), suites=("trixie-backports",), components=("main",))
    cur = repo.current(results_for(repo, "apt-get"))
    changes = repo.compare(cur)
    assert [c.field for c in changes] == ["/etc/apt/sources.list.d/b.sources:content", "/etc/apt/sources.list.d/b.sources:mode"]
    cmds = repo.fix(changes, cur)
    assert any("sources.list.d/b.sources" in c for c in cmds) and not any("yum.repos.d" in c for c in cmds)


def test_name_validation():
    for bad in ("../x", "a b", "", "-x"):
        with pytest.raises(ValueError):
            Repository(name=bad, uris=("http://a",))


def test_stray_sources_report_and_remove():
    from bastet.core.shell import ProbeResult
    from bastet.engine.packages import StraySources
    listing = ("/etc/apt/sources.list.d/debian.sources\n"
               "/etc/apt/sources.list.d/ftp_us_debian_org_debian.sources\n"
               "/etc/apt/sources.list.d/security_debian_org_debian_security.sources\n")
    s = StraySources(keep=("debian", "proxmox"))
    cur = s.current({"stray": ProbeResult(0, listing)})
    assert cur["stray"] == ("/etc/apt/sources.list.d/ftp_us_debian_org_debian.sources",
                            "/etc/apt/sources.list.d/security_debian_org_debian_security.sources")
    assert s.report_only() and [c.field for c in s.compare(cur)] == ["stray"]
    r = StraySources(keep=("debian",), remove=True)
    assert not r.report_only()
    assert r.fix(r.compare(cur), cur) == ["rm -f -- /etc/apt/sources.list.d/ftp_us_debian_org_debian.sources "
                                          "/etc/apt/sources.list.d/security_debian_org_debian_security.sources"]


def test_stray_sources_ignore_odd_lines():
    from bastet.core.shell import ProbeResult
    from bastet.engine.packages import StraySources
    s = StraySources(keep=())
    cur = s.current({"stray": ProbeResult(0, "grep: warning\n/etc/apt/sources.list.d/x.sources\n/etc/other\n")})
    assert cur["stray"] == ("/etc/apt/sources.list.d/x.sources",)


# repository knobs unsupported off apt, untrusted-means-signed, shared file parts, zypper/apk keys

def test_repository_knobs_unsupported_off_apt():
    for manager in ("dnf", "pacman", "apk"):
        for knob in ({"suites": ("x",)}, {"components": ("main",)}, {"architectures": ("amd64",)}, {"types": ("deb-src",)}):
            repo = Repository(name="r", uris=("http://a",), **knob)
            with pytest.raises(Unsupported):
                repo.current(results_for(repo, manager))
    for knob in ({"options": (("a", "b"),)}, {"signed_by": "/k"}, {"trusted": True}):
        repo = Repository(name="r", uris=("http://a",), **knob)
        with pytest.raises(Unsupported):
            repo.current(results_for(repo, "apk"))
    pacman = Repository(name="r", uris=("http://a",))
    with pytest.raises(Unsupported, match="pacman role"):
        pacman.current(results_for(pacman, "pacman"))
    two = Repository(name="two", uris=("http://a", "http://b"))
    with pytest.raises(Unsupported):
        two.current(results_for(two, "zypper"))
    with pytest.raises(ValueError):
        Repository(name="r", uris=("http://a",), key="K", signed_by="/k")


def test_untrusted_means_signature_required_on_dnf():
    repo = Repository(name="r", uris=("http://a",), trusted=False)
    assert "gpgcheck=1" in repo._ini("dnf")


def test_shared_file_parts_are_threaded():
    import base64
    repo = Repository(name="alp", uris=("https://a/main", "https://a/community"))
    cur = repo.current(results_for(repo, "apk"))
    final = [part.wanted(state["content"]) for part, state in repo._threaded(cur)][-1]
    assert final == "https://a/main\nhttps://a/community\n"
    script = "\n".join(repo.fix(repo.compare(cur), cur))
    last = [line for line in script.splitlines() if "base64 -d" in line][-1]
    assert base64.b64decode(last.split("'")[3]).decode() == final
    assert repo.touches() == Repository(name="other", uris=("http://b",)).touches() is not None


def test_zypper_key_imported_and_apk_key_name():
    repo = Repository(name="z", uris=("http://a",), key="-----BEGIN PGP PUBLIC KEY BLOCK-----\nX\n-----END PGP PUBLIC KEY BLOCK-----\n")
    cur = repo.current(results_for(repo, "zypper"))
    assert repo.fix(repo.compare(cur), cur)[-1] == "rpm --import /etc/pki/rpm-gpg/RPM-GPG-KEY-bastet-z"
    apk = Repository(name="edge", uris=("http://a",), key="K", key_name="alpine-devel@lists.alpinelinux.org-6165ee59.rsa.pub")
    assert apk.parts("apk")[-1].path == "/etc/apk/keys/alpine-devel@lists.alpinelinux.org-6165ee59.rsa.pub"
    with pytest.raises(ValueError):
        Repository(name="e", uris=("http://a",), key_name="../x")
