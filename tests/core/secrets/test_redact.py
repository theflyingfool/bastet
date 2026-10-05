from bastet.core.secrets.redact import ACTIVE, Redactor


def test_short_values_are_never_masked():
    r = Redactor()
    r.add("abc")
    assert r.mask("the abc value") == "the abc value"


def test_whole_value_masked():
    r = Redactor()
    r.add("Hunter2Secret")
    assert "Hunter2Secret" not in r.mask("password=Hunter2Secret!")


def test_multiline_value_masks_each_line():
    r = Redactor()
    r.add("-----BEGIN KEY-----\nabcdefgh\n-----END KEY-----\n")
    text = "before\n-----BEGIN KEY-----\nabcdefgh\n-----END KEY-----\nafter"
    masked = r.mask(text)
    assert "abcdefgh" not in masked
    assert "BEGIN KEY" not in masked


def test_shlex_quoted_form_is_masked():
    r = Redactor()
    r.add("it's a secret")
    masked = r.mask("ran: echo " + __import__("shlex").quote("it's a secret"))
    assert "it's a secret" not in masked


def test_json_dumps_form_is_masked():
    import json

    r = Redactor()
    r.add('weird"value')
    body = json.dumps({"k": 'weird"value'})
    masked = r.mask(body)
    assert "weird" not in masked


def test_protected_text_is_never_masked_even_if_it_matches_a_value():
    r = Redactor()
    r.add("box/role/option")  # a path, coincidentally also registered as a "value"
    r.protect("box/role/option")
    assert r.mask("missing secret box/role/option (bastet secret set box role option)") == (
        "missing secret box/role/option (bastet secret set box role option)"
    )


def test_clear_forgets_values_and_protections():
    r = Redactor()
    r.add("Hunter2Secret")
    r.protect("box/role/option")
    r.clear()
    assert r.mask("Hunter2Secret and box/role/option") == "Hunter2Secret and box/role/option"


def test_active_is_cleared_between_tests_by_the_autouse_fixture():
    assert ACTIVE.mask("SENTINEL-LEFTOVER") == "SENTINEL-LEFTOVER"  # nothing registered yet: untouched
    ACTIVE.add("SENTINEL-LEFTOVER")
    assert "SENTINEL-LEFTOVER" not in ACTIVE.mask("SENTINEL-LEFTOVER")


def test_active_was_actually_cleared_from_the_previous_test():
    # if the autouse fixture didn't run, ACTIVE would still contain SENTINEL-LEFTOVER here
    assert ACTIVE.mask("SENTINEL-LEFTOVER") == "SENTINEL-LEFTOVER"
