from pathlib import Path

import pytest

from bastet.core.errors import BastetError
from bastet.roles.builtin import HostInfo
from bastet.roles.expr import FACT_NAMES, check_text, check_when, context, names_in, resolve, truthy


def host(**kw):
    base = dict(name="vps1", type="vps", data={"os": "Arch Linux", "cpu": "AuthenticAMD"}, root=Path("/x"), lab={"domain": "example.net"})
    return HostInfo(**{**base, **kw})


def ctx(values=None, options=("tools", "tz"), **kw):
    return context({o: None for o in options}, values or {}, host(**kw))


def test_a_whole_expression_keeps_its_type():
    c = ctx({"tools": ["git", "vim"], "tz": "UTC"})
    assert resolve("{{ tools }}", c) == ["git", "vim"]
    assert resolve("{{ tz }}", c) == "UTC"
    assert resolve("{{ tz is none }}", c) is False
    assert resolve("{{ 3 }}", c) == 3


def test_text_around_an_expression_renders_to_text():
    assert resolve("zone={{ tz }}!", ctx({"tz": "UTC"})) == "zone=UTC!"


def test_plain_values_and_collections_pass_through_and_nest():
    c = ctx({"tz": "UTC"})
    assert resolve("plain", c) == "plain" and resolve(5, c) == 5 and resolve(None, c) is None
    assert resolve({"a": ["{{ tz }}", 1]}, c) == {"a": ["UTC", 1]}


def test_unset_option_is_none_not_text():
    assert resolve("{{ tz }}", ctx()) is None


def test_host_facts():
    c = ctx()
    assert resolve("{{ host.name }}", c) == "vps1"
    assert truthy("host.arch_like", c) is True and truthy("host.debian_like", c) is False
    assert truthy("host.container", c) is False and truthy("host.physical", c) is False
    assert resolve("{{ host.cpu }}", c) == "AuthenticAMD"
    assert resolve("{{ lab.domain }}", c) == "example.net"


def test_truthy_none_means_no_condition_and_bare_option_names_work():
    assert truthy(None, ctx()) is True
    assert truthy("tz", ctx({"tz": "UTC"})) is True and truthy("tz", ctx()) is False
    assert truthy("tz == 'UTC' and not host.container", ctx({"tz": "UTC"})) is True


def test_check_text_accepts_known_names_and_plain_text():
    check_text("plain, no braces", set(), "k")
    check_text("{{ tools }} and {{ host.name }}", {"tools"}, "k")
    assert FACT_NAMES == ("host", "lab")


def test_check_text_refuses_unknown_names_and_bad_syntax():
    with pytest.raises(BastetError, match="nope"):
        check_text("{{ nope }}", {"tools"}, "packages[0].name")
    with pytest.raises(BastetError, match="packages\\[0\\].name"):
        check_text("{{ tools ", {"tools"}, "packages[0].name")


def test_names_in_finds_option_names_recursively():
    assert names_in({"a": ["{{ tz }} x", "plain"], "b": "{{ host.name }}"}) == {"tz", "host"}
    assert names_in("plain") == set()
    assert names_in([]) == set() and names_in({}) == set() and names_in(3) == set()


def test_check_when_refuses_unknown_names():
    check_when("tz and host.physical", {"tz"}, "k")
    with pytest.raises(BastetError, match="when names no option: nope"):
        check_when("nope", {"tz"}, "k")
    with pytest.raises(BastetError, match="when:"):
        check_when("tz ==", {"tz"}, "k")


def test_the_sandbox_refuses_python_internals():
    with pytest.raises(BastetError):
        resolve("{{ ''.__class__ }}", ctx())
    with pytest.raises(BastetError):
        resolve("x {{ ''.__class__ }}", ctx())
    with pytest.raises(BastetError):
        truthy("''.__class__", ctx())


def test_evaluation_errors_are_bastet_errors():
    with pytest.raises(BastetError):
        resolve("{{ host.nope }}", ctx())
    with pytest.raises(BastetError):
        resolve("{{ 1 / 0 }}", ctx())
