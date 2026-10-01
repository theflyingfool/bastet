"""File contents from Jinja2 templates, rendered on the controller (spec 9.2)."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateError, TemplateNotFound, UndefinedError

from bastet.core.errors import BastetError


def render_template(directory: Path, name: str, values: dict) -> str:
    env = Environment(loader=FileSystemLoader(str(directory)), undefined=StrictUndefined,
                      keep_trailing_newline=True, autoescape=False)
    try:
        return env.get_template(name).render(**values)
    except TemplateNotFound:
        raise BastetError(f"template {name} not found in {directory}") from None
    except UndefinedError as e:
        raise BastetError(f"{name}: {e.message}") from None
    except TemplateError as e:
        raise BastetError(f"{name}: {e}") from None
