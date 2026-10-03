"""Write docs/roles.md, the list of every role Bastet ships (a test keeps it in sync).

Run: uv run python scripts/gen_roles_doc.py
"""

from pathlib import Path

from bastet.roles.contract import load_roles
from bastet.roles.pages import roles_markdown

OUT = Path(__file__).parents[1] / "docs" / "roles.md"


def render() -> str:
    return roles_markdown(load_roles())


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(), encoding="utf-8")
    print(f"wrote {OUT}")
