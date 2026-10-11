from types import SimpleNamespace

import pytest

from bastet.core.errors import BastetError
from bastet.engine import passwords

SPEC_VECTOR = "$6$saltstring$svn8UoSVapNtMuq1ukKS4tPQd8iKwSMHWjl/O817G3uBnIFNjnQJuesI68u4OTLiBFdcbYEdFCoEOfaS35inz1"


def test_the_sha_crypt_specification_vector_matches():
    assert passwords.matches("Hello world!", SPEC_VECTOR) and not passwords.matches("Hello world", SPEC_VECTOR)


def test_yescrypt_round_trip():
    h = passwords.hash("correct horse", "yescrypt")
    assert h.startswith("$y$") and passwords.matches("correct horse", h) and not passwords.matches("wrong", h)


@pytest.mark.parametrize("scheme,prefix", [("sha512", "$6$"), ("sha256", "$5$")])
def test_sha_round_trips(scheme, prefix):
    h = passwords.hash("correct horse", scheme)
    assert h.startswith(prefix) and passwords.matches("correct horse", h) and not passwords.matches("wrong", h)


def test_the_default_scheme_is_sha512_and_salts_vary():
    a, b = passwords.hash("pw"), passwords.hash("pw")
    assert a.startswith("$6$") and a != b


def test_an_unknown_scheme_is_refused():
    with pytest.raises(ValueError):
        passwords.hash("pw", "md5")


@pytest.mark.parametrize("stored", ["", "!", "*", "x", "$6$", "$6$salt", "$6$$", "$$a$b"])
def test_matches_is_false_for_anything_that_is_not_a_hash(stored):
    assert passwords.matches("pw", stored) is False


@pytest.mark.parametrize("text,scheme", [
    ("ENCRYPT_METHOD YESCRYPT", "yescrypt"),
    ("ENCRYPT_METHOD SHA512", "sha512"),
    ("  encrypt_method  sha256", "sha256"),
    ("ENCRYPT_METHOD MD5", "sha512"),
    ("#ENCRYPT_METHOD YESCRYPT", "sha512"),
    ("ENCRYPT_METHOD YESCRYPT # default", "yescrypt"),
    ("PASS_MAX_DAYS 99999", "sha512"),
    ("", "sha512"),
])
def test_scheme_for_reads_encrypt_method(text, scheme):
    assert passwords.scheme_for(text) == scheme


def test_a_password_with_a_line_break_is_refused():
    with pytest.raises(BastetError, match="can't contain a line break"):
        passwords.hash("a\nb", "sha512")


def test_without_the_library_the_error_says_what_to_install(monkeypatch):
    def broken():
        raise OSError("no libcrypt")

    passwords._library.cache_clear()
    monkeypatch.setattr(passwords, "_load", broken)
    for call in (lambda: passwords.hash("pw"), lambda: passwords.matches("pw", SPEC_VECTOR)):
        with pytest.raises(BastetError, match="needs libcrypt"):
            call()


def test_the_library_is_loaded_once(monkeypatch):
    calls = []
    passwords._library.cache_clear()
    monkeypatch.setattr(passwords, "_load", lambda: calls.append(1) or object())
    first, second = passwords._library(), passwords._library()
    passwords._library.cache_clear()
    assert first is second and len(calls) == 1


def test_a_library_that_cannot_make_yescrypt_says_so_instead_of_asking_to_install_libcrypt():
    old_libcrypt = SimpleNamespace()  # no crypt_gensalt_rn
    with pytest.raises(BastetError, match="can't make yescrypt hashes.*libxcrypt"):
        passwords.new_setting(old_libcrypt, "yescrypt")
    assert passwords.new_setting(old_libcrypt, "sha512").startswith("$6$")
