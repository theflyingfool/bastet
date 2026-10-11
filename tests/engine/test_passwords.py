import shutil

import pytest

from bastet.core.errors import BastetError
from bastet.engine import passwords

needs_openssl = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not installed")


@needs_openssl
def test_known_vector_from_the_sha_crypt_specification():
    assert passwords.hash("Hello world!", "saltstring") == (
        "$6$saltstring$svn8UoSVapNtMuq1ukKS4tPQd8iKwSMHWjl/O817G3uBnIFNjnQJuesI68u4OTLiBFdcbYEdFCoEOfaS35inz1")


@needs_openssl
def test_a_long_salt_is_cut_to_16_characters():
    assert passwords.hash("x", "a" * 40).startswith("$6$" + "a" * 16 + "$")


@needs_openssl
def test_matches_uses_the_stored_salt():
    stored = passwords.hash("correct horse", passwords.new_salt())
    assert passwords.matches("correct horse", stored) and not passwords.matches("wrong", stored)


@pytest.mark.parametrize("stored", ["", "!", "*", "x", "$1$abc$def", "$6$", "$6$salt", "$6$rounds=6000$abc$def", "$y$j9T$salt$hash"])
def test_matches_is_false_for_anything_that_is_not_a_plain_sha512_hash(stored):
    assert passwords.matches("pw", stored) is False


def test_new_salt_is_16_valid_characters_and_varies():
    a, b = passwords.new_salt(), passwords.new_salt()
    assert len(a) == 16 and a != b and set(a) <= set("./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")


def test_a_password_with_a_line_break_is_refused():
    with pytest.raises(BastetError, match="can't contain a line break"):
        passwords.hash("a\nb", "salt")


def test_without_openssl_the_error_says_what_to_install(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(BastetError, match="needs openssl on the machine running Bastet"):
        passwords.hash("pw", "salt")


@needs_openssl
def test_the_password_goes_to_openssl_on_stdin_never_the_command_line(monkeypatch):
    import subprocess

    seen = {}
    real = subprocess.run

    def spy(cmd, **kw):
        seen["cmd"], seen["input"] = cmd, kw.get("input")
        return real(cmd, **kw)

    monkeypatch.setattr(subprocess, "run", spy)
    passwords.hash("s3cret-value", "abc")
    assert "s3cret-value" not in " ".join(seen["cmd"]) and "s3cret-value" in seen["input"]
