"""File contents from Jinja2 templates, rendered on the controller."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateError, TemplateNotFound, UndefinedError
from jinja2.sandbox import SandboxedEnvironment

from bastet.core.errors import BastetError


class UnsetInText(BastetError):
    """An unset option (None) was about to be written into text."""


def reject_none(value: object) -> object:
    """`finalize` for role text: an unset option never turns into the word None; guard optional parts with {% if %}."""
    if value is None:
        raise UnsetInText("an unset option is used inside text (write the optional part as {% if option %}...{% endif %})")
    return value


def environment(loader=None, sandbox: bool = False) -> Environment:
    """The plain environment, or the sandboxed one (no Python internals, unset options refused) for role data."""
    if sandbox:
        return SandboxedEnvironment(loader=loader, undefined=StrictUndefined, keep_trailing_newline=True, autoescape=False,
                                    finalize=reject_none)
    return Environment(loader=loader, undefined=StrictUndefined, keep_trailing_newline=True, autoescape=False)


def render_template(directory: Path, name: str, values: dict, sandbox: bool = False) -> str:
    env = environment(FileSystemLoader(str(directory)), sandbox)
    try:
        return env.get_template(name).render(**values)
    except TemplateNotFound:
        raise BastetError(f"template {name} not found in {directory}") from None
    except UnsetInText as e:
        raise BastetError(f"{name}: {e.message}") from None
    except UndefinedError as e:
        raise BastetError(f"{name}: {e.message}") from None
    except TemplateError as e:
        raise BastetError(f"{name}: {e}") from None
