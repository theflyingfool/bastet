"""The small expression language of Markdown roles: `{{ }}` values and `when:` conditions, over options and host facts."""

from __future__ import annotations

import re
from types import SimpleNamespace

from jinja2 import StrictUndefined, TemplateError, Undefined, meta
from jinja2.sandbox import SandboxedEnvironment

from bastet.core.errors import BastetError
from bastet.core.osinfo import ARCH_LIKE

FACT_NAMES = ("host", "lab")
_ENV = SandboxedEnvironment(undefined=StrictUndefined, keep_trailing_newline=True, autoescape=False)
_WHOLE = re.compile(r"^\s*\{\{(?P<expr>(?:(?!\}\}).)+)\}\}\s*$", re.DOTALL)


def _templated(text: str) -> bool:
    return "{{" in text or "{%" in text


def _unknown(names: set[str], allowed: set[str]) -> list[str]:
    return sorted(names - allowed - set(FACT_NAMES))


def _variables(source: str, where: str) -> set[str]:
    try:
        return set(meta.find_undeclared_variables(_ENV.parse(source)))
    except TemplateError as exc:
        raise BastetError(f"{where}: {exc}") from None


def check_text(text: str, allowed: set[str], where: str) -> None:
    """Parse-time check of one value: valid syntax, and every name an option or a fact."""
    if not _templated(text):
        return
    if bad := _unknown(_variables(text, where), allowed):
        raise BastetError(f"{where}: names no option or fact: {', '.join(bad)}")


def check_when(text: str, allowed: set[str], where: str) -> None:
    """Parse-time check of a `when:` condition: valid syntax, and every name an option or a fact."""
    if bad := _unknown(_variables("{{ " + text + " }}", f"{where}: when"), allowed):
        raise BastetError(f"{where}: when names no option: {', '.join(bad)}")


def _expression(text: str, ctx: dict) -> object:
    try:
        result = _ENV.compile_expression(text.strip(), undefined_to_none=False)(**ctx)
        if isinstance(result, Undefined):  # a missing attribute or a refused one comes back undefined, not raised
            result._fail_with_undefined_error()
        return result
    except Exception as exc:  # TemplateError (incl. SecurityError, UndefinedError) and runtime errors like 1 / 0
        raise BastetError(f"{{{{ {text.strip()} }}}}: {exc}") from None


def resolve(value: object, ctx: dict) -> object:
    """Fill the expressions in a role value: a lone `{{ expr }}` keeps its type, other text renders to text."""
    if isinstance(value, str):
        if not _templated(value):
            return value
        if m := _WHOLE.match(value):
            return _expression(m.group("expr"), ctx)
        try:
            return _ENV.from_string(value).render(**ctx)
        except Exception as exc:
            raise BastetError(f"{value[:40]!r}: {exc}") from None
    if isinstance(value, list):
        return [resolve(v, ctx) for v in value]
    if isinstance(value, dict):
        return {k: resolve(v, ctx) for k, v in value.items()}
    return value


def names_in(value: object) -> set[str]:
    """Every variable name used by `{{ }}` / `{% %}` in a value, however deeply nested."""
    if isinstance(value, str):
        return _variables(value, repr(value[:40])) if _templated(value) else set()
    if isinstance(value, list):
        return set().union(*(names_in(v) for v in value)) if value else set()
    if isinstance(value, dict):
        return set().union(*(names_in(v) for v in value.values())) if value else set()
    return set()


def truthy(text: str | None, ctx: dict) -> bool:
    """A `when:` condition: no condition is true, otherwise the expression's truthiness."""
    return True if text is None else bool(_expression(text, ctx))


def context(role_options: dict, values: dict, host) -> dict:
    """Every option (None when unset), the host's facts and the lab-wide data."""
    facts = SimpleNamespace(
        name=host.name, type=host.type, os_id=host.os_id, arch_like=host.os_id in ARCH_LIKE,
        debian_like=host.debian_like, container=host.container, physical=host.physical,
        cpu=str(host.data.get("cpu") or ""))
    ctx = {name: values.get(name) for name in role_options}
    ctx["host"], ctx["lab"] = facts, host.lab
    return ctx
