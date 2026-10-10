from pathlib import Path

import pytest
import yaml

from bastet.core.errors import BastetError
from bastet.engine.files import File, Line
from bastet.engine.run import Batch
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import parse_role
from bastet.roles.declarative import build
from bastet.roles.resolve import Applied

CONF = "/etc/demo.conf"
OPTIONS = r"^\[options\]\s*$"


def make(tmp_path, options, files, **front):
    folder = tmp_path / "demo"
    folder.mkdir(exist_ok=True)
    data = {"bastet": "role-definition", "name": "demo", "version": "1.0.0", "api": 0, "description": "A demo role",
            "options": options, "files": files, **front}
    path = folder / "demo role.md"
    path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\nNotes.\n", encoding="utf-8")
    return parse_role(path)


def host(os="Arch Linux"):
    return HostInfo(name="laptop1", type="laptop", data={"os": os} if os else {}, root=Path("/nonexistent"), lab={})


def line(key, text):
    return Line(path=CONF, line=text, match=rf"^#?\s*{key}\s*(=.*)?$", after=OPTIONS, unique=True)


def ini(tmp_path, options, values, **front):
    return build(make(tmp_path, options, [{"path": CONF, "edit": "ini"}], **front), values, host())[0].resources


def test_flag_true_and_false(tmp_path):
    opts = {"a": {"type": "bool", "key": "Color", "section": "options"},
            "b": {"type": "bool", "key": "ILoveCandy", "section": "options"}}
    assert ini(tmp_path, opts, {"a": True, "b": False}) == [line("Color", "Color"), line("ILoveCandy", "#ILoveCandy")]


def test_list_empty_list_and_value(tmp_path):
    opts = {"h": {"type": "list", "items": {"type": "string"}, "key": "HoldPkg", "section": "options"},
            "i": {"type": "list", "items": {"type": "string"}, "key": "IgnorePkg", "section": "options"},
            "p": {"type": "int", "key": "ParallelDownloads", "section": "options"}}
    assert ini(tmp_path, opts, {"h": [], "i": ["x", "y"], "p": 8}) == [
        line("HoldPkg", "#HoldPkg ="), line("IgnorePkg", "IgnorePkg = x y"), line("ParallelDownloads", "ParallelDownloads = 8")]


def test_no_key_and_none_are_skipped(tmp_path):
    opts = {"a": {"type": "bool"}, "b": {"type": "bool", "key": "Color", "section": "options"},
            "c": {"type": "string", "key": "LogFile", "section": "options"}}
    assert ini(tmp_path, opts, {"a": True, "b": None, "c": None}) == []


def test_no_section_means_no_anchor(tmp_path):
    opts = {"c": {"type": "string", "key": "LogFile"}}
    [r] = ini(tmp_path, opts, {"c": "/x"})
    assert r.after is None


def test_values_follow_contract_order(tmp_path):
    opts = {"z": {"type": "string", "key": "Z", "section": "options"}, "a": {"type": "string", "key": "A", "section": "options"}}
    assert [r.line for r in ini(tmp_path, opts, {"a": "1", "z": "2"})] == ["Z = 2", "A = 1"]


def apt(tmp_path, values, **entry):
    opts = {"b": {"type": "bool", "key": "Flag"}, "l": {"type": "list", "items": {"type": "string"}, "key": "List"},
            "s": {"type": "string", "key": "Name"}, "n": {"type": "string"}}
    role = make(tmp_path, opts, [{"path": "/etc/apt/apt.conf.d/50demo", "render": "apt", **entry}])
    return build(role, values, host("Debian GNU/Linux 13"))[0].resources


def test_apt_render_every_value_type(tmp_path):
    [f] = apt(tmp_path, {"b": True, "l": ["a", "b"], "s": 'say "hi" \\ now', "n": "skipped"},
              mode="0644", owner="root", group="root", validate="true")
    assert f == File(path="/etc/apt/apt.conf.d/50demo", mode="0644", owner="root", group="root", validate="true", content=(
        '# Managed by Bastet (apt role). Edit the role file, not this file.\n'
        'Flag "true";\nList { "a"; "b"; };\nName "say \\"hi\\" \\\\ now";\n'))


def test_apt_render_false_and_empty_list(tmp_path):
    [f] = apt(tmp_path, {"b": False, "l": []})
    assert f.content.splitlines()[1:] == ['Flag "false";', "List { };"]


def test_provides_and_placement_reach_resources(tmp_path):
    opts = {"a": {"type": "bool", "key": "Color", "section": "options"}}
    role = make(tmp_path, opts, [{"path": CONF, "edit": "ini", "before": "packages", "after": "base"}], provides=["ntp"])
    [r] = build(role, {"a": True}, host())[0].resources
    assert (r.run_before, r.run_after, r.provides) == ("packages", "base", ("ntp",))


@pytest.mark.parametrize("os,label,family,bad", [("arch", "Arch", "arch", "Debian GNU/Linux 13"),
                                                  ("debian", "Debian", "debian", "Arch Linux")])
def test_wrong_os_is_refused(tmp_path, os, label, family, bad):
    role = make(tmp_path, {}, [{"path": CONF, "edit": "ini"}], os=[os])
    with pytest.raises(BastetError) as e:
        build(role, {}, host(bad))
    assert str(e.value) == f"demo role: laptop1 isn't {label}-based ({bad}); aim it at [[{family}]]"


def test_unknown_os_text(tmp_path):
    role = make(tmp_path, {}, [{"path": CONF, "edit": "ini"}], os=["arch"])
    with pytest.raises(BastetError, match=r"\(OS unknown\)"):
        build(role, {}, host(None))


def test_matching_os_builds(tmp_path):
    role = make(tmp_path, {}, [{"path": CONF, "edit": "ini"}], os=["debian", "arch"])
    assert build(role, {}, host()) == [Batch("demo", [])]


def test_markdown_role_through_batches_for(tmp_path):
    opts = {"a": {"type": "bool", "key": "Color", "section": "options"}}
    role = make(tmp_path, opts, [{"path": CONF, "edit": "ini"}])
    [batch] = batches_for([Applied(role, {"a": True})], host())
    assert batch.name == "demo" and batch.resources == [line("Color", "Color")]
