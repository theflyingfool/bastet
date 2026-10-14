from pathlib import Path

from bastet.roles.contract import Option, RoleDef
from bastet.roles.pages import role_page, roles_markdown


def _role(**options) -> RoleDef:
    return RoleDef(name="demo", description="Demo role.", options=options, path=Path("demo role.md"))


def test_requires_and_conflicts_show_in_description():
    role = _role(
        ntp=Option(type="bool", description="Sync the clock."),
        servers=Option(type="list", description="Servers.", requires={"ntp": (True,)}, conflicts=("pool",)),
        pool=Option(type="string", description="Pool.", requires={"ntp": None}),
        mode=Option(type="string", description="Mode.", requires={"ntp": ("a", "b")}))
    for text in (role_page(role, []), roles_markdown({"demo": role})):
        assert "| Servers. (needs ntp: true; can't be set with pool) |" in text
        assert "| Pool. (needs ntp) |" in text
        assert "| Mode. (needs ntp: a or b) |" in text
        assert "| Sync the clock. |" in text


def test_relations_in_object_fields_stay_escaped():
    field = Option(type="string", description="Field.", requires={"a|b": None})
    obj = Option(type="object", description="Obj.", fields={"x": field})
    text = role_page(_role(o=Option(type="list", description="L.", items=obj)), [])
    assert "| o[].x | string |  | Field. (needs a\\|b) |" in text
