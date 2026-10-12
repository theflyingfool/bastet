from pathlib import Path

import pytest
import yaml

from bastet.core.errors import BastetError
from bastet.engine.slots import apply_order
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import parse_role
from bastet.roles.declarative import build
from bastet.roles.resolve import Applied

OPTIONS = {"zone": {"type": "string"}, "extra": {"type": "bool"}, "pw": {"type": "string", "secret": True}}


def role(tmp_path, **extra):
    folder = tmp_path / "demo"
    folder.mkdir(exist_ok=True)
    data = {"bastet": "role-definition", "name": "demo", "version": "1.0.0", "api": 0, "description": "A demo role",
            "options": OPTIONS, **extra}
    path = folder / "demo role.md"
    path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\nNotes.\n", encoding="utf-8")
    return parse_role(path)


def host(**data):
    return HostInfo(name="media01", type="vps", data={"os": "Arch Linux", **data}, root=Path("/x"), lab={})


def built(r, values=None, secrets=frozenset(), **data):
    [batch] = build(r, values or {}, host(**data), secrets)
    return batch.resources


def names(resources):
    return [getattr(x, "name", None) or getattr(x, "path", None) for x in resources]


def test_a_section_with_a_false_when_emits_nothing_and_a_true_one_emits_its_entries(tmp_path):
    r = role(tmp_path, sections=[{"when": "extra", "packages": ["pkg-a"], "files": [{"path": "/etc/a", "content": "a"}]}])
    assert built(r, {"extra": False}) == []
    assert sorted(names(built(r, {"extra": True}))) == ["/etc/a", "pkg-a"]


def test_the_entry_when_is_anded_with_the_section_when(tmp_path):
    r = role(tmp_path, sections=[{"when": "extra", "packages": [{"name": "pkg-a", "when": "zone == 'UTC'"}]}])
    assert names(built(r, {"extra": True, "zone": "UTC"})) == ["pkg-a"]
    assert built(r, {"extra": False, "zone": "UTC"}) == []
    assert built(r, {"extra": True, "zone": "CET"}) == []


def test_a_section_without_when_always_applies_and_only_organises(tmp_path):
    r = role(tmp_path, sections=[{"name": "base", "packages": ["pkg-a", {"name": "pkg-b", "when": "extra"}],
                                  "commands": [{"name": "c", "run": "true", "unless": "false"}]}])
    assert sorted(names(built(r))) == ["c", "pkg-a"]
    assert sorted(names(built(r, {"extra": True}))) == ["c", "pkg-a", "pkg-b"]
    assert r.packages[0] == {"name": "pkg-a"}


def test_sections_and_top_level_entries_coexist_in_listing_order(tmp_path):
    r = role(tmp_path, packages=["top-1"], files=[{"path": "/etc/top", "content": "t"}],
             sections=[{"when": "extra", "packages": ["one-1"], "systemd": [{"kind": "unit", "name": "one.service"}]},
                       {"packages": ["two-1"], "files": [{"path": "/etc/two", "content": "2"}]}])
    assert [p["name"] for p in r.packages] == ["top-1", "one-1", "two-1"]
    assert [f["path"] for f in r.entries] == ["/etc/top", "/etc/two"]
    assert sorted(names(built(r, {"extra": True}))) == sorted(["top-1", "one-1", "two-1", "/etc/top", "/etc/two", "one.service"])
    assert sorted(names(built(r))) == sorted(["top-1", "two-1", "/etc/top", "/etc/two"])
    [batch] = batches_for([Applied(role=r, values={"extra": True})], host())
    planned = [(batch.name, [type("Item", (), {"resource": x}) for x in batch.resources])]
    assert [type(i.resource).__name__ for i in apply_order(planned)] == ["Package"] * 3 + ["File"] * 2 + ["Unit"]


def test_one_section_installs_configures_and_enables_in_block_order(tmp_path):
    r = role(tmp_path, sections=[{"name": "arch", "when": "host.arch_like",
                                  "systemd": [{"kind": "unit", "name": "ntp.service", "enabled": True}],
                                  "files": [{"path": "/etc/ntp.conf", "content": "zone {{ zone }}", "restart": ["ntp.service"]}],
                                  "packages": ["ntp"]}])
    [batch] = batches_for([Applied(role=r, values={"zone": "UTC"})], host())
    planned = [(batch.name, [type("Item", (), {"resource": x}) for x in batch.resources])]
    assert [type(i.resource).__name__ for i in apply_order(planned)] == ["Package", "File", "Unit"]
    assert built(r, {"zone": "UTC"}, os="Debian 12") == []


def error(tmp_path, **extra):
    with pytest.raises(BastetError) as exc:
        role(tmp_path, **extra)
    assert exc.value.key == "sections"
    assert exc.value.file == tmp_path / "demo" / "demo role.md"
    return exc.value.message


def test_a_nested_section_is_refused(tmp_path):
    assert "sections[0]: sections can't be nested" in error(tmp_path, sections=[{"sections": [{"packages": ["a"]}]}])


def test_an_unknown_key_an_empty_section_and_a_non_list_are_refused(tmp_path):
    assert "sections[0]: unknown key packge" in error(tmp_path, sections=[{"packge": ["a"]}])
    assert "sections[1] (empty): a section needs at least one entry" in error(
        tmp_path, sections=[{"packages": ["a"]}, {"name": "empty", "when": "extra"}])
    assert "sections[0]: packages must be a list" in error(tmp_path, sections=[{"packages": "a"}])
    assert "sections must be a list" in error(tmp_path, sections={"packages": ["a"]})
    assert "sections[0]: each section is a map" in error(tmp_path, sections=["a"])


def test_a_bad_section_when_is_refused_when_the_role_is_read(tmp_path):
    assert "sections[0] (x): " in error(tmp_path, sections=[{"name": "x", "when": "nosuch", "packages": ["a"]}])
    assert "when must be text" in error(tmp_path, sections=[{"when": 3, "packages": ["a"]}])


def test_errors_name_the_section_and_the_entry(tmp_path):
    msg = error(tmp_path, sections=[{"packages": ["a"]},
                                    {"name": "arch", "files": [{"path": "/etc/a", "content": "x"}, {"path": "/etc/b"}]}])
    assert msg.startswith("sections[1] (arch): files entry needs exactly one of")
    msg = error(tmp_path, sections=[{"name": "arch", "packages": ["a", {"name": "b", "when": "nosuch"}]}])
    assert msg.startswith("sections[0] (arch): packages[1]: when names no option: nosuch")
    msg = error(tmp_path, sections=[{"name": "arch", "systemd": [{"kind": "bogus"}]}])
    assert msg.startswith("sections[0] (arch): systemd[0]: kind must be one of")


def test_a_secret_option_used_in_a_section_entry_marks_that_entry_secret(tmp_path):
    r = role(tmp_path, sections=[{"when": "extra", "files": [{"path": "/etc/s", "content": "key={{ pw }}"},
                                                             {"path": "/etc/p", "content": "plain"}]}])
    secret, plain = built(r, {"extra": True, "pw": "x"}, frozenset({"pw"}))
    assert secret.secret is True
    assert plain.secret is False
