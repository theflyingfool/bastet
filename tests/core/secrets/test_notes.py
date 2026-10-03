from bastet.core.secrets.notes import SecretNote, SecretPath, all_notes


def test_paths():
    assert SecretPath.parse("git1/gitea/admin_password").rel == "_secrets/git1/gitea/admin_password.md"
    assert SecretPath.parse("nfs/bmc_password").rel == "_secrets/nfs/bmc_password.md"
    assert SecretPath.from_cli(["lab", "caddy", "dns_token"]).text == "lab/caddy/dns_token"


def test_note_round_trip_keeps_body_byte_for_byte(tmp_path):
    sp = SecretPath.parse("git1/gitea/admin_password")
    armor = "-----BEGIN AGE ENCRYPTED FILE-----\nYWJj\n-----END AGE ENCRYPTED FILE-----"
    note = SecretNote.new(sp, source="generated", created="2026-10-03T14:22", applies_to="git1")
    note.body = armor
    note.write(tmp_path)
    text = (tmp_path / sp.rel).read_text()
    assert text.endswith(armor + "\n") and "rotated:\n" in text and "standalone: false" in text and "locked: true" in text
    loaded = SecretNote.load(tmp_path, sp)
    assert loaded.is_sealed and loaded.body.strip() == armor and loaded.data["source"] == "generated"


def test_extra_text_is_reported(tmp_path):
    sp = SecretPath.parse("lab/x")
    (tmp_path / "_secrets" / "lab").mkdir(parents=True)
    (tmp_path / sp.rel).write_text("---\nbastet: secret\n---\n-----BEGIN AGE ENCRYPTED FILE-----\nYQ==\n-----END AGE ENCRYPTED FILE-----\nmy notes\n")
    note = SecretNote.load(tmp_path, sp)
    assert not note.is_sealed and note.extra_text == "my notes"


def test_all_notes(tmp_path):
    for p in ("git1/gitea/a", "nfs/b", "lab/c"):
        SecretNote.new(SecretPath.parse(p), source="chosen", created="2026-10-03T10:00", applies_to=p.split("/")[0]).write(tmp_path)
    assert sorted(n.path.text for n in all_notes(tmp_path)) == ["git1/gitea/a", "lab/c", "nfs/b"]
