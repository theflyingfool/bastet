import pytest

from bastet.core.errors import BastetError
from bastet.engine.templates import render_template


def test_render_template(tmp_path):
    (tmp_path / "motd.j2").write_text("{{ host }} · managed by Bastet\n{% for s in servers %}server {{ s }}\n{% endfor %}")
    out = render_template(tmp_path, "motd.j2", {"host": "media01", "servers": ["a", "b"]})
    assert out == "media01 · managed by Bastet\nserver a\nserver b\n"


def test_missing_value_names_template_and_value(tmp_path):
    (tmp_path / "motd.j2").write_text("{{ nope }}\n")
    with pytest.raises(BastetError) as e:
        render_template(tmp_path, "motd.j2", {})
    assert "motd.j2" in str(e.value) and "nope" in str(e.value)


def test_missing_template(tmp_path):
    with pytest.raises(BastetError):
        render_template(tmp_path, "gone.j2", {})
