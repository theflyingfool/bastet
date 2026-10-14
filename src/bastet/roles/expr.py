"""The small expression language of Markdown roles: `{{ }}` values and `when:` conditions, over options and host facts."""

from __future__ import annotations

import re
from types import SimpleNamespace

from jinja2 import TemplateError, Undefined, UndefinedError, meta, nodes

from bastet.core.errors import BastetError
from bastet.core.osinfo import ARCH_LIKE, DEBIAN_LIKE, os_id
from bastet.engine.templates import UnsetInText, environment

FACT_NAMES = ("host", "lab", "applied")
HOST_FACTS = ("name", "type", "os_id", "arch_like", "debian_like", "container", "physical", "cpu")
_ENV = environment(sandbox=True)
_WHOLE = re.compile(r"^\s*\{\{(?P<expr>(?:(?!\}\}).)+)\}\}\s*$", re.DOTALL)


def _templated(text: str) -> bool:
    return "{{" in text or "{%" in text


def _unknown(names: set[str], allowed: set[str]) -> list[str]:
    return sorted(names - allowed - set(FACT_NAMES))


def _parse(source: str, where: str) -> nodes.Template:
    try:
        return _ENV.parse(source)
    except TemplateError as exc:
        raise BastetError(f"{where}: {exc}") from None


def _variables(source: str, where: str) -> set[str]:
    return set(meta.find_undeclared_variables(_parse(source, where)))


def _attr_name(node: nodes.Node) -> str | None:
    if isinstance(node, nodes.Getattr):
        return node.attr
    if isinstance(node, nodes.Getitem) and isinstance(node.arg, nodes.Const) and isinstance(node.arg.value, str):
        return node.arg.value
    return None


def _fact_uses(source: str, where: str) -> tuple[set[str], set[str]]:
    """The `host.<attr>` names and the `applied.origin.<option>` names an expression or text uses."""
    tree, host_attrs, origin_options = _parse(source, where), set(), set()
    for node in tree.find_all((nodes.Getattr, nodes.Getitem)):
        attr, base = _attr_name(node), getattr(node, "node", None)
        if attr is None:
            continue
        if isinstance(base, nodes.Name) and base.name == "host":
            host_attrs.add(attr)
        elif _attr_name(base) == "origin" and isinstance(getattr(base, "node", None), nodes.Name) and base.node.name == "applied":
            origin_options.add(attr)
    return host_attrs, origin_options


def _check_facts(source: str, allowed: set[str], where: str) -> None:
    """`host.<attr>` must be a host fact and `applied.origin.<option>` an option of the role."""
    host_attrs, origin_options = _fact_uses(source, where)
    if bad := sorted(host_attrs - set(HOST_FACTS)):
        raise BastetError(f"{where}: names no host fact: {', '.join(bad)} (facts: {', '.join(HOST_FACTS)})")
    if bad := sorted(origin_options - allowed):
        raise BastetError(f"{where}: applied.origin names no option: {', '.join(bad)}")


def check_text(text: str, allowed: set[str], where: str) -> None:
    """Parse-time check of one value: valid syntax, and every name an option or a fact."""
    if not _templated(text):
        return
    if bad := _unknown(_variables(text, where), allowed):
        raise BastetError(f"{where}: names no option or fact: {', '.join(bad)}")
    _check_facts(text, allowed, where)


def check_when(text: str, allowed: set[str], where: str) -> None:
    """Parse-time check of a `when:` condition: valid syntax, and every name an option or a fact."""
    if bad := _unknown(_variables("{{ " + text + " }}", f"{where}: when"), allowed):
        raise BastetError(f"{where}: when names no option: {', '.join(bad)}")
    _check_facts("{{ " + text + " }}", allowed, f"{where}: when")


def check_fact_when(text: str, options: set[str], where: str) -> None:
    """Check a `when:` that sees only the host and lab facts (the options are what is being decided)."""
    named = sorted(_variables("{{ " + text + " }}", f"{where}: when") & options)
    if named:
        raise BastetError(f"{where}: when sees only host and lab facts, not options: {', '.join(named)}")
    if "applied" in _variables("{{ " + text + " }}", f"{where}: when"):
        raise BastetError(f"{where}: when sees only host and lab facts, not applied")
    check_when(text, set(), where)


def check_option_when(text: str, options: set[str], where: str) -> None:
    """Check a role-level override's `when:`: the role's options plus the host and lab facts, never `applied`."""
    check_option_text("{{ " + text + " }}", options, f"{where}: when")
    check_when(text, options, where)


def check_option_text(text: str, options: set[str], where: str) -> None:
    """Like check_text, but for a place that sees the options, `host` and `lab` and no `applied`."""
    if _templated(text) and "applied" in _variables(text, where):
        raise BastetError(f"{where}: applied isn't available here (only the role's options, host and lab)")
    check_text(text, options, where)


def _reason(exc: Exception) -> str:
    """Why an expression failed. Syntax and sandbox errors are fixed text; others could quote a value, so give the type."""
    if isinstance(exc, TemplateError) and not isinstance(exc, UndefinedError):
        return str(exc)
    return f"{type(exc).__name__} (a name or attribute that doesn't exist, or a bad operation)"


def _expression(text: str, ctx: dict) -> object:
    try:
        result = _ENV.compile_expression(text.strip(), undefined_to_none=False)(**ctx)
        if isinstance(result, Undefined):  # a missing attribute or a refused one comes back undefined, not raised
            result._fail_with_undefined_error()
        return result
    except Exception as exc:  # TemplateError (incl. SecurityError, UndefinedError) and runtime errors like 1 / 0
        raise BastetError(f"{{{{ {text.strip()} }}}}: {_reason(exc)}") from None


def resolve(value: object, ctx: dict) -> object:
    """Fill the expressions in a role value: a lone `{{ expr }}` keeps its type, other text renders to text."""
    if isinstance(value, str):
        if not _templated(value):
            return value
        if m := _WHOLE.match(value):
            return _expression(m.group("expr"), ctx)
        try:
            return _ENV.from_string(value).render(**ctx)
        except UnsetInText:
            unset = ", ".join(f"`{n}`" for n in sorted(names_in(value)) if ctx.get(n) is None and n not in FACT_NAMES)
            raise BastetError(f"{unset or 'an option'} is unset (in {value[:40]!r}); "
                              "write the optional part as {% if option %}...{% endif %}") from None
        except Exception as exc:
            raise BastetError(f"{value[:40]!r}: {_reason(exc)}") from None
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


def host_facts(name: str, type_name: str, data: dict, physical: bool) -> SimpleNamespace:
    """The `host` an expression sees; the one place these facts are built (names in HOST_FACTS)."""
    osid = os_id(data)
    return SimpleNamespace(
        name=name, type=type_name, os_id=osid, arch_like=osid in ARCH_LIKE,
        debian_like=any(w in str(data.get("os", "")).lower() for w in DEBIAN_LIKE), container=type_name == "lxc",
        physical=physical, cpu=str(data.get("cpu") or ""))


class _Origins:
    """`applied.origin`: for each option, the label of the notes that set it here, or "" when nothing did."""

    def __init__(self, origins: dict[str, str]):
        self._origins = origins

    def __getattr__(self, name: str) -> str:
        return self._origins.get(name, "")


def context(role_options: dict, values: dict, host, origins: dict[str, str] | None = None) -> dict:
    """Every option (None when unset), the host's facts, the lab-wide data and where each option's value came from."""
    ctx = {name: values.get(name) for name in role_options}
    ctx["host"], ctx["lab"] = host_facts(host.name, host.type, host.data, host.physical), host.lab
    ctx["applied"] = SimpleNamespace(origin=_Origins(origins or {}))
    return ctx
