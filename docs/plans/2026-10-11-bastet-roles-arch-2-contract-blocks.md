# Roles architecture, step 2: the contract exposes the building blocks — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. In this repo, the `bastet-run-plan` skill supplies the Bastet-specific parts.

**Goal:** a Markdown role can call the `packages`, `systemd`, `users` and `files` building blocks directly from its frontmatter, with `{{ }}` values and a `when:` condition on every entry, so roles like `time`, `base` and `example-app` need no Python. The `users` block also gets a read-only report of accounts no role manages, like the packages block's unaccounted report, to detect drift.

**Architecture:** today a Markdown role file carries only `files:` (`edit: ini` / `render: apt`) and `commands:` entries (`src/bastet/roles/declarative.py`). Each new entry kind is a thin, validated mapping from frontmatter fields to an existing engine resource (`Package`, `Unit`, `User`, `File`, …). Values may be literal or `{{ }}` expressions over the role's options and a few host facts; `when:` is one expression on any entry. Blocks never call each other: a role that needs two lists entries for both.

**Tech Stack:** Python ≥3.12, Jinja2 (sandboxed, already a dependency), pytest.

**Spec:** `docs/specs/2026-10-10-bastet-roles-architecture-design.md` (§2 decisions "Direct use of a block", §3 "Where logic lives", §7 reserved keys, §8 open questions: the `when:` expression language). Roadmap: `docs/ROADMAP.md`, "VPS apps" step 1.

## Global Constraints

- **Unit tests** never touch the real inventory, `~/.config/bastet`, `~/.local/share/bastet`, `~/.ssh`, the real `~/.cache` or `$XDG_RUNTIME_DIR`; no network; `tmp_path` only; placeholder data only (see "Example data" in `docs/ROADMAP.md`).
- **Test file basenames unique across `tests/`** (no `__init__.py`).
- Every message goes through `bastet.ui.out`; no `typer.echo` in `src/` (`tests/test_no_raw_echo.py`).
- The version is written only in `pyproject.toml`; do not bump it.
- Nothing deletes notes or records. Blocks do not call each other; only roles call blocks.
- Existing tests keep passing unchanged, except where a task names a test it edits.
- Block entry types are added only when a role needs them; this plan adds only the entry kinds listed here. Planned-but-unbuilt kinds are recorded in docs (Task 7), not built.
- `api: 0` stays a draft; new frontmatter keys need no version bump.
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## The contract this plan builds

Frontmatter keys, all optional lists (`ROLE_NOTE_KEYS`; `packages` leaves `ROLE_NOTE_RESERVED`):

```yaml
packages:                          # -> Package resources
  - example-app                          # a bare name
  - {name: "{{ tools }}"}          # a name that resolves to a list expands to one Package each
  - {name: amd-ucode, when: "host.physical"}
systemd:                           # -> Unit / TimeSettings / Hostname / Locale / drop_in
  - {kind: unit, name: example-app.service, enabled: true, state: up}
  - {kind: time, timezone: "{{ timezone }}", ntp: "{{ ntp }}"}
  - {kind: hostname}               # the host's own name
  - {kind: locale, lang: "{{ locale }}"}
  - {kind: dropin, unit: example-app.service, name: bastet, content: "...", restart: true}
users:                             # -> User / Group / AuthorizedKey / sudoer
  - {kind: user, name: git, system: true, shell: /bin/bash}
  - {kind: group, name: git}
  - {kind: key, user: git, key: "ssh-ed25519 AAAA…"}
  - {kind: sudoer, name: git, user: git, commands: [/usr/bin/systemctl]}
files:                             # existing edit/render, plus whole-file kinds
  - {path: /etc/example-app/app.conf, content: "import conf.d/*\n", mode: "0644", reload: [example-app.service]}
  - {path: /etc/example-app/app.conf, template: app.conf.j2}      # Jinja2 file in the role's own folder
  - {path: /etc/example-app/conf.d, directory: true, mode: "0755"}
  - {path: /srv/current, link: /srv/app}
  - {path: /etc/default/x, line: "A=1", match: "^A=", unique: true}
  - {path: /etc/x.conf, block: "...", marker: "bastet x", comment: "#"}
commands:                          # existing
  - {name: n, run: r, unless: u, when: "..."}
```

**Common to every entry:** `when:` (an expression, true = build the entry; unset = always), and for ordering `before:` / `after:` (a block slot name, never both). Block entries accept `when`, `before`, `after`; `files` entries also accept `restart:` / `reload:` (lists of unit names, becoming end-of-run triggers).

**Expressions** (`{{ … }}` values and `when:`): Jinja2 in a sandbox with `StrictUndefined`. The context is every option of the role (unset options are `None`), `host` (`name`, `type`, `os_id`, `arch_like`, `debian_like`, `container`, `physical`, `cpu`), and `lab` (the lab-wide data). A value that is exactly one `{{ expr }}` keeps the expression's type (a list, a bool, an int, `None`); anything else is rendered as text. A field that resolves to `None` is treated as unset and dropped. `when:` uses Jinja's expression syntax, so `when: on` (a bare option name, as `commands:` used before) still works. Literal `{{` in a value is written `{% raw %}{{{% endraw %}`. Cross-host variables are not in the context yet (deferred until a role needs them).

## Review Focus

- A `{{ }}` that names an unknown option or fact fails at **parse time** with the role file and key, not at run time on a host.
- An option left unset (`None`) used in `{{ x }}` drops the field instead of writing the text `None` into a file or a package name.
- `when:` false on a `files` entry that has `backup: true` builds neither the entry nor its backup command.
- A password (or any value) from a `secret:` option never shows in check/apply output or the run record, and marks **only the entries that use it** secret, not the whole role (a role with a `users:` password and a `packages:` list still shows its package diff).
- A `users:` entry naming the `bastet` account is refused (the account is Bastet's own; the old `users` role guard stays for the Python role).
- A `files` `template:` cannot escape the role's folder (`../`, absolute path).
- A shipped role is read-only data: a user role's `{{ }}` can't reach Python internals (sandbox) — `{{ ''.__class__ }}` is refused.

---

## File structure

| File | Responsibility |
|---|---|
| Create `src/bastet/roles/expr.py` | The expression language: `check_text`, `check_when`, `resolve`, `truthy`; sandboxed Jinja2 |
| Create `src/bastet/roles/entries.py` | Entry validation (`parse_*_entries`) and building (`build_entries`) for `packages`, `systemd`, `users`, and the new `files` kinds |
| Modify `src/bastet/roles/contract.py` | New frontmatter keys; `RoleDef` fields; `when:` through `expr`; `files` entry kinds in `_file_entry` |
| Modify `src/bastet/roles/declarative.py` | `build()` calls `entries.build_entries` and filters every entry through `when:` |
| Tests (all new): `tests/roles/test_role_expressions.py`, `test_role_package_entries.py`, `test_role_systemd_entries.py`, `test_role_users_entries.py`, `test_role_files_entries.py`, `test_role_contract_end_to_end.py` | One file per task |
| Create `src/bastet/engine/passwords.py`; tests `tests/engine/test_passwords.py`, `tests/engine/test_user_password.py`; modify `src/bastet/engine/users.py` | Task 3b: plain-text passwords |
| Create `tests/roles/test_unaccounted_users.py`; modify `src/bastet/engine/users.py`, `src/bastet/roles/builtin.py`, `src/bastet/data/roles/users/role.yml` | Task 6: the unaccounted-users report |
| Modify `src/bastet/data/roles/files/role.yml`, `docs/specs/2026-10-10-bastet-roles-architecture-design.md`, `docs/ROADMAP.md` | Docs (Task 7) |

---

### Task 1: The expression language

**Files:**
- Create: `src/bastet/roles/expr.py`
- Test: `tests/roles/test_role_expressions.py`

**Interfaces:**
- Produces:
  - `FACT_NAMES: tuple[str, ...] = ("host", "lab")`
  - `check_text(text: str, allowed: set[str], where: str) -> None` — raises `BastetError` for a syntax error or a name not in `allowed | FACT_NAMES`; does nothing for text with no `{{` / `{%`.
  - `check_when(text: str, allowed: set[str], where: str) -> None` — same, for a bare expression.
  - `resolve(value: object, ctx: dict) -> object` — walks str/list/dict; a string that is exactly one `{{ expr }}` returns the expression's typed result; any other string with `{{`/`{%` is rendered to text; everything else is returned as is.
  - `names_in(value: object) -> set[str]` — every variable name used by `{{ }}` / `{% %}` in a string, or recursively in a list/dict (used to find which entries touch a secret option).
  - `truthy(text: str | None, ctx: dict) -> bool` — `None` is `True` (no condition); otherwise the expression's truthiness.
  - `context(role_options: dict, values: dict, host) -> dict` — the context described in "Expressions" above.

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path

import pytest

from bastet.core.errors import BastetError
from bastet.roles.builtin import HostInfo
from bastet.roles.expr import FACT_NAMES, check_text, check_when, context, resolve, truthy


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
    from bastet.roles.expr import names_in
    assert names_in({"a": ["{{ tz }} x", "plain"], "b": "{{ host.name }}"}) == {"tz", "host"}
    assert names_in("plain") == set()


def test_check_when_refuses_unknown_names():
    check_when("tz and host.physical", {"tz"}, "k")
    with pytest.raises(BastetError, match="when names no option: nope"):
        check_when("nope", {"tz"}, "k")


def test_the_sandbox_refuses_python_internals():
    with pytest.raises(BastetError):
        resolve("{{ ''.__class__ }}", ctx())
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/roles/test_role_expressions.py -q`
Expected: FAIL (`ModuleNotFoundError: bastet.roles.expr`).

- [ ] **Step 3: Implement `src/bastet/roles/expr.py`**

```python
"""The small expression language of Markdown roles: `{{ }}` values and `when:` conditions, over options and host facts."""

from __future__ import annotations

import re
from types import SimpleNamespace

from jinja2 import StrictUndefined, TemplateError, meta
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


def check_text(text: str, allowed: set[str], where: str) -> None:
    """Parse-time check of one value: valid syntax, and every name an option or a fact."""
    if not _templated(text):
        return
    try:
        names = meta.find_undeclared_variables(_ENV.parse(text))
    except TemplateError as exc:
        raise BastetError(f"{where}: {exc}") from None
    if bad := _unknown(names, allowed):
        raise BastetError(f"{where}: names no option or fact: {', '.join(bad)}")


def check_when(text: str, allowed: set[str], where: str) -> None:
    try:
        names = meta.find_undeclared_variables(_ENV.parse("{{ " + text + " }}"))
    except TemplateError as exc:
        raise BastetError(f"{where}: when: {exc}") from None
    if bad := _unknown(names, allowed):
        raise BastetError(f"{where}: when names no option: {', '.join(bad)}")


def _expression(text: str, ctx: dict) -> object:
    try:
        return _ENV.compile_expression(text.strip(), undefined_to_none=False)(**ctx)
    except TemplateError as exc:
        raise BastetError(f"{{{{ {text.strip()} }}}}: {exc}") from None


def resolve(value: object, ctx: dict) -> object:
    if isinstance(value, str):
        if not _templated(value):
            return value
        if (m := _WHOLE.match(value)):
            return _expression(m.group("expr"), ctx)
        try:
            return _ENV.from_string(value).render(**ctx)
        except TemplateError as exc:
            raise BastetError(f"{value[:40]!r}: {exc}") from None
    if isinstance(value, list):
        return [resolve(v, ctx) for v in value]
    if isinstance(value, dict):
        return {k: resolve(v, ctx) for k, v in value.items()}
    return value


def names_in(value: object) -> set[str]:
    if isinstance(value, str):
        return set(meta.find_undeclared_variables(_ENV.parse(value))) if _templated(value) else set()
    if isinstance(value, list):
        return set().union(*(names_in(v) for v in value)) if value else set()
    if isinstance(value, dict):
        return set().union(*(names_in(v) for v in value.values())) if value else set()
    return set()


def truthy(text: str | None, ctx: dict) -> bool:
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
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/roles/test_role_expressions.py -q`
Expected: all pass. If `test_the_sandbox_refuses_python_internals` yields `SecurityError` not wrapped, add `jinja2.exceptions.SecurityError` handling — it subclasses `TemplateError`, so it is already wrapped; confirm.

- [ ] **Step 5: Commit**

```bash
git add src/bastet/roles/expr.py tests/roles/test_role_expressions.py
git commit -m "roles: the expression language for Markdown role values and when: (sandboxed Jinja2)"
```

---

### Task 2: `when:` on every entry, and `packages:` entries

**Files:**
- Create: `src/bastet/roles/entries.py`
- Modify: `src/bastet/roles/contract.py` (`ROLE_NOTE_KEYS`, `ROLE_NOTE_RESERVED`, `RoleDef`, `parse_role`, `_command_entry`, `_file_entry`)
- Modify: `src/bastet/roles/declarative.py` (`build`, `_commands`), `src/bastet/roles/resolve.py` (`Applied.secret_options`), `src/bastet/cli/run.py:71-72` (set it), `src/bastet/roles/builtin.py` (`batches_for` passes it; Markdown roles stop being blanket-marked secret)
- Test: `tests/roles/test_role_package_entries.py`; edit `tests/roles/test_role_commands.py`

**Interfaces:**
- Consumes: `expr.check_text`, `expr.check_when`, `expr.resolve`, `expr.truthy`, `expr.context` (Task 1).
- Produces (in `entries.py`):
  - `COMMON_KEYS = {"when", "before", "after"}`
  - `check_common(entry: dict, allowed: set[str], where: str, path, key: str) -> None` — validates `when` (text, `check_when`), `before`/`after` (text naming a slot in `engine.slots.SLOTS`, never both); every other string value is passed to `check_text`.
  - `parse_packages(path, items, options) -> list[dict]` — a bare string becomes `{"name": s}`; maps allow `name, state, version, aur, purge` + common keys; `name` required; `state` in `present|absent`.
  - `Applied.secret_options: frozenset[str]` (new field in `roles/resolve.py`, default empty): the top-level option names `resolve_refs` replaced with a decrypted secret. `cli/run.py` sets it next to `a.secret` (`a.secret_options = frozenset(became_secret)`).
  - `build_entries(role, values, host, secret_options=frozenset()) -> list[Resource]` — all block entries of the role (packages here; later tasks add to it), each filtered by `when`, each resolved, each given `run_before`/`run_after`/`provides` via `declarative._placed`-equivalent (do not import `declarative`; put the small `placed()` helper in `entries.py` and have `declarative._placed` call it).
  - `RoleDef.packages: list[dict]` (new field, default empty).
- `declarative.build(role, values, host, secret_options=frozenset())` gets one extra line: `resources += entries.build_entries(role, values, host, secret_options)`; commands use `expr.truthy`. For its `edit` / `render` / `as: entries` resources it marks them secret when `secret_options` is non-empty (the old role-wide rule, kept for them). `builtin.batches_for` passes `a.secret_options` and no longer blanket-marks a Markdown role's resources afterwards (old-format roles keep the blanket rule).

Behaviour fixed by this task: `commands:` `when` is an expression (a bare option name keeps working, now by truthiness); the parse-time message for an unknown name stays `when names no option: <name>`.

- [ ] **Step 1: Write the failing tests**

`tests/roles/test_role_package_entries.py`:

```python
from pathlib import Path

import pytest
import yaml

from bastet.core.errors import BastetError
from bastet.engine.packages import Package
from bastet.roles.builtin import HostInfo
from bastet.roles.contract import parse_role
from bastet.roles.declarative import build


def role(tmp_path, packages, options=None, extra=None):
    folder = tmp_path / "demo"
    folder.mkdir(exist_ok=True)
    data = {"bastet": "role-definition", "name": "demo", "version": "1.0.0", "api": 0, "description": "A demo role",
            "options": options or {"tools": {"type": "list", "items": {"type": "string"}}}, "packages": packages, **(extra or {})}
    path = folder / "demo role.md"
    path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\nNotes.\n", encoding="utf-8")
    return parse_role(path)


def built(r, values, **host_kw):
    host = HostInfo(name="vps1", type="vps", data={"os": "Arch Linux"}, root=Path("/x"), lab={}, **host_kw)
    [batch] = build(r, values, host)
    return batch.resources


def test_bare_names_and_maps_become_packages(tmp_path):
    r = role(tmp_path, ["example-app", {"name": "git", "state": "absent"}, {"name": "yay-bin", "aur": True}])
    assert [(p.name, p.state, p.aur) for p in built(r, {})] == [("example-app", "present", False), ("git", "absent", False), ("yay-bin", "present", True)]
    assert all(isinstance(p, Package) for p in built(r, {}))


def test_a_name_that_resolves_to_a_list_expands(tmp_path):
    r = role(tmp_path, [{"name": "{{ tools }}"}])
    assert [p.name for p in built(r, {"tools": ["git", "vim"]})] == ["git", "vim"]
    assert built(r, {"tools": []}) == []


def test_a_name_that_resolves_to_nothing_is_an_error(tmp_path):
    r = role(tmp_path, [{"name": "{{ tools }}"}])
    with pytest.raises(BastetError, match="packages\\[0\\]: name resolved to nothing"):
        built(r, {})


def test_when_filters_on_host_facts(tmp_path):
    r = role(tmp_path, [{"name": "amd-ucode", "when": "host.physical"}, "git"])
    assert [p.name for p in built(r, {}, physical=False)] == ["git"]
    assert [p.name for p in built(r, {}, physical=True)] == ["amd-ucode", "git"]


def test_before_after_land_on_the_resource(tmp_path):
    [p] = built(role(tmp_path, [{"name": "git", "after": "files"}]), {})
    assert p.run_after == "files" and p.run_before is None


@pytest.mark.parametrize("entry, message", [
    ({"state": "present"}, "packages\\[0\\]: needs a name"),
    ({"name": "x", "state": "held"}, "state must be present or absent"),
    ({"name": "x", "zzz": 1}, "zzz"),
    ({"name": "{{ nope }}"}, "names no option or fact: nope"),
    ({"name": "x", "when": "nope"}, "when names no option: nope"),
    ({"name": "x", "before": "packages", "after": "files"}, "before or after, not both"),
    ({"name": "x", "before": "nonsense"}, "unknown block"),
])
def test_package_entry_errors(tmp_path, entry, message):
    with pytest.raises(BastetError, match=message):
        role(tmp_path, [entry])
```

In `tests/roles/test_role_commands.py`, change `({**ENTRY, "when": "nope"}, "when names no option: nope")` — no edit needed (message unchanged); add:

```python
def test_when_is_an_expression_over_options_and_host_facts(tmp_path):
    role = cmd_role(tmp_path, [{**ENTRY, "when": "on and not host.container"}])
    assert built(role, {"on": True}) and not built(role, {"on": False})
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/roles/test_role_package_entries.py tests/roles/test_role_commands.py -q`
Expected: FAIL (unknown key `packages` is reserved, no entries module).

- [ ] **Step 3: Implement**

`src/bastet/roles/entries.py`:

```python
"""Block entries in a Markdown role file: packages, systemd, users and whole files, handed to the building blocks."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from bastet.core.errors import BastetError
from bastet.engine.model import Resource
from bastet.engine.packages import Package
from bastet.engine.slots import SLOTS
from bastet.roles import expr

COMMON_KEYS = {"when", "before", "after"}
PACKAGE_KEYS = {"name", "state", "version", "aur", "purge"} | COMMON_KEYS


def _fail(msg: str, path: Path, key: str) -> BastetError:
    return BastetError(msg, file=path, key=key)


def check_common(entry: dict, allowed: set[str], where: str, path: Path, key: str) -> None:
    """`when`, `before`/`after` and every `{{ }}` string in an entry, checked when the role is read."""
    if "when" in entry:
        if not isinstance(entry["when"], str):
            raise _fail(f"{where}: when must be text", path, key)
        expr.check_when(entry["when"], allowed, where)
    for k in ("before", "after"):
        if k in entry and entry[k] not in SLOTS:
            raise _fail(f"{where}: {k}: unknown block {entry[k]!r} (known: {', '.join(SLOTS)})", path, key)
    if "before" in entry and "after" in entry:
        raise _fail(f"{where}: use before or after, not both", path, key)
    _walk_check(entry, allowed, where, path, key)


def _walk_check(value: object, allowed: set[str], where: str, path: Path, key: str) -> None:
    if isinstance(value, str):
        try:
            expr.check_text(value, allowed, where)
        except BastetError as exc:
            raise _fail(exc.message, path, key) from None
    elif isinstance(value, list):
        for v in value:
            _walk_check(v, allowed, where, path, key)
    elif isinstance(value, dict):
        for k, v in value.items():
            if k != "when":
                _walk_check(v, allowed, where, path, key)


def _unknown(entry: dict, keys: set[str], where: str, path: Path, key: str) -> None:
    if bad := sorted(str(k) for k in set(entry) - keys):
        raise _fail(f"{where}: unknown key {', '.join(bad)}", path, bad[0])


def parse_packages(path: Path, items: object, options: dict) -> list[dict]:
    if not isinstance(items, list):
        raise _fail("packages must be a list", path, "packages")
    allowed, out = set(options), []
    for i, item in enumerate(items):
        where = f"packages[{i}]"
        entry = {"name": item} if isinstance(item, str) else item
        if not isinstance(entry, dict):
            raise _fail(f"{where}: each entry is a name or a map", path, "packages")
        _unknown(entry, PACKAGE_KEYS, where, path, "packages")
        if not isinstance(entry.get("name"), str) or not entry["name"]:
            raise _fail(f"{where}: needs a name", path, "packages")
        if entry.get("state", "present") not in ("present", "absent"):
            raise _fail(f"{where}: state must be present or absent", path, "packages")
        check_common(entry, allowed, where, path, "packages")
        out.append(dict(entry))
    return out


def placed(resource: Resource, role, entry: dict, secret_options: frozenset = frozenset()) -> Resource:
    """Order and capabilities from the entry; secret when the entry uses a secret-valued option."""
    secret = bool(expr.names_in(entry) & secret_options)
    return replace(resource, run_before=entry.get("before"), run_after=entry.get("after"), provides=tuple(role.provides),
                   **({"secret": True} if secret else {}))


def _packages(role, ctx: dict, secrets: frozenset) -> list[Resource]:
    out: list[Resource] = []
    for i, entry in enumerate(role.packages):
        if not expr.truthy(entry.get("when"), ctx):
            continue
        fields = {k: expr.resolve(v, ctx) for k, v in entry.items() if k not in COMMON_KEYS}
        name = fields.pop("name", None)
        if name is None:
            raise BastetError(f"{role.name}: packages[{i}]: name resolved to nothing")
        fields = {k: v for k, v in fields.items() if v is not None}
        for n in name if isinstance(name, list) else [name]:
            out.append(placed(Package(name=str(n), **fields), role, entry, secrets))
    return out


def build_entries(role, values: dict, host, secret_options: frozenset = frozenset()) -> list[Resource]:
    ctx = expr.context(role.options, values, host)
    return [*_packages(role, ctx, secret_options)]
```

`contract.py`:
- `ROLE_NOTE_KEYS`: add `"packages"`; `ROLE_NOTE_RESERVED`: remove `"packages"`.
- `RoleDef`: add `packages: list[dict] = field(default_factory=list)`.
- In `parse_role`, after commands: `packages = entries.parse_packages(path, data.get("packages") or [], options)` (import `from bastet.roles import entries` inside the function or at module top; `entries` must not import `contract` — it does not) and pass `packages=packages` to `RoleDef(...)`.
- `_command_entry`: replace the `when` option-name check with `expr.check_when(entry["when"], set(options), "commands entry")`; keep `before`/`after` handling.

`declarative.py`:
- `build()`: add `resources += entries.build_entries(role, values, host)` after `_entries(...)`.
- `_commands(role, values, host)`: condition becomes `expr.truthy(c.get("when"), expr.context(role.options, values, host))`; update the call in `build`.
- `_placed` delegates: `return entries.placed(resource, role, entry)` (keep the name for existing callers).

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/roles -q`
Expected: all pass, including the unchanged command tests.

- [ ] **Step 5: Commit**

```bash
git add src/bastet/roles/entries.py src/bastet/roles/contract.py src/bastet/roles/declarative.py tests/roles/test_role_package_entries.py tests/roles/test_role_commands.py
git commit -m "roles: packages: entries and a when: expression on every entry"
```

---

### Task 3: `systemd:` entries

**Files:**
- Modify: `src/bastet/roles/entries.py`, `src/bastet/roles/contract.py`
- Test: `tests/roles/test_role_systemd_entries.py`

**Interfaces:**
- Consumes: `check_common`, `placed`, `build_entries` (Task 2), `engine.systemd` (`Unit`, `TimeSettings`, `Hostname`, `Locale`, `drop_in`).
- Produces: `parse_systemd(path, items, options) -> list[dict]`; `RoleDef.systemd: list[dict]`; `systemd` in `ROLE_NOTE_KEYS`. Kinds and their keys (all plus `COMMON_KEYS`):

| kind | keys | resource |
|---|---|---|
| `unit` | `name` (required), `enabled` (bool), `state` (`up`\|`down`) | `Unit` |
| `time` | `timezone`, `ntp` (bool), `rtc_local` (bool) | `TimeSettings` (skipped when all three resolve to `None`) |
| `hostname` | `name` (default: the host's own `hostname` fact or its note name) | `Hostname`; skipped on containers |
| `locale` | `lang`, `keymap` | `Locale` (skipped when both `None`) |
| `dropin` | `unit`, `name`, `content` (required), `restart` (bool, default true) | `drop_in(...)` |

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path

import pytest
import yaml

from bastet.core.errors import BastetError
from bastet.engine.files import File
from bastet.engine.systemd import Hostname, Locale, TimeSettings, Unit
from bastet.roles.builtin import HostInfo
from bastet.roles.contract import parse_role
from bastet.roles.declarative import build


def role(tmp_path, systemd, options=None):
    folder = tmp_path / "demo"
    folder.mkdir(exist_ok=True)
    data = {"bastet": "role-definition", "name": "demo", "version": "1.0.0", "api": 0, "description": "A demo role",
            "options": options or {"tz": {"type": "string"}, "ntp": {"type": "bool"}}, "systemd": systemd}
    path = folder / "demo role.md"
    path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\nNotes.\n", encoding="utf-8")
    return parse_role(path)


def built(r, values=None, type="vps", data=None):
    host = HostInfo(name="vps1", type=type, data={"os": "Arch Linux", **(data or {})}, root=Path("/x"), lab={})
    [batch] = build(r, values or {}, host)
    return batch.resources


def test_unit(tmp_path):
    [u] = built(role(tmp_path, [{"kind": "unit", "name": "example-app.service", "enabled": True, "state": "up"}]))
    assert isinstance(u, Unit) and (u.name, u.enabled, u.state) == ("example-app.service", True, "up")


def test_time_takes_option_values_and_drops_unset_ones(tmp_path):
    r = role(tmp_path, [{"kind": "time", "timezone": "{{ tz }}", "ntp": "{{ ntp }}"}])
    [t] = built(r, {"tz": "UTC", "ntp": True})
    assert isinstance(t, TimeSettings) and (t.timezone, t.ntp, t.rtc_local) == ("UTC", True, None)
    assert built(r, {}) == []


def test_hostname_uses_the_hosts_name_and_skips_containers(tmp_path):
    r = role(tmp_path, [{"kind": "hostname"}])
    [h] = built(r)
    assert isinstance(h, Hostname) and h.name == "vps1"
    [h] = built(r, data={"hostname": "vps1.example.net"})
    assert h.name == "vps1.example.net"
    assert built(r, type="lxc") == []


def test_locale(tmp_path):
    [loc] = built(role(tmp_path, [{"kind": "locale", "lang": "en_US.UTF-8"}]))
    assert isinstance(loc, Locale) and (loc.lang, loc.keymap) == ("en_US.UTF-8", None)


def test_dropin(tmp_path):
    [f] = built(role(tmp_path, [{"kind": "dropin", "unit": "example-app.service", "name": "bastet", "content": "[Service]\nX=1\n"}]))
    assert isinstance(f, File) and f.path == "/etc/systemd/system/example-app.service.d/bastet.conf"
    assert [t.label for t in f.on_change] == ["daemon-reload", "restart example-app.service"]
    [f] = built(role(tmp_path, [{"kind": "dropin", "unit": "u.service", "name": "n", "content": "x", "restart": False}]))
    assert [t.label for t in f.on_change] == ["daemon-reload"]


def test_when_and_ordering(tmp_path):
    r = role(tmp_path, [{"kind": "unit", "name": "a.service", "when": "ntp", "after": "files"}])
    assert built(r, {"ntp": False}) == []
    [u] = built(r, {"ntp": True})
    assert u.run_after == "files"


@pytest.mark.parametrize("entry, message", [
    ({"name": "x"}, "systemd\\[0\\]: needs a kind"),
    ({"kind": "timer", "name": "x"}, "kind must be one of"),
    ({"kind": "unit"}, "unit: needs a name"),
    ({"kind": "unit", "name": "x", "state": "running"}, "state must be up or down"),
    ({"kind": "unit", "name": "x", "enabled": "{{ nope }}"}, "names no option or fact: nope"),
    ({"kind": "unit", "name": "x", "zzz": 1}, "zzz"),
    ({"kind": "dropin", "unit": "u", "name": "n"}, "dropin: needs content"),
])
def test_systemd_entry_errors(tmp_path, entry, message):
    with pytest.raises(BastetError, match=message):
        role(tmp_path, [entry])
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/roles/test_role_systemd_entries.py -q`
Expected: FAIL (`systemd` is not an allowed key yet… it is currently an unknown key).

- [ ] **Step 3: Implement**

In `entries.py` add:

```python
from bastet.engine.systemd import Hostname, Locale, TimeSettings, Unit, drop_in

SYSTEMD_KINDS = {
    "unit": {"name", "enabled", "state"},
    "time": {"timezone", "ntp", "rtc_local"},
    "hostname": {"name"},
    "locale": {"lang", "keymap"},
    "dropin": {"unit", "name", "content", "restart"},
}
SYSTEMD_REQUIRED = {"unit": ("name",), "dropin": ("unit", "name", "content")}


def parse_systemd(path: Path, items: object, options: dict) -> list[dict]:
    if not isinstance(items, list):
        raise _fail("systemd must be a list", path, "systemd")
    allowed, out = set(options), []
    for i, entry in enumerate(items):
        where = f"systemd[{i}]"
        if not isinstance(entry, dict):
            raise _fail(f"{where}: each entry is a map", path, "systemd")
        kind = entry.get("kind")
        if kind is None:
            raise _fail(f"{where}: needs a kind", path, "systemd")
        if kind not in SYSTEMD_KINDS:
            raise _fail(f"{where}: kind must be one of {', '.join(SYSTEMD_KINDS)}", path, "systemd")
        _unknown(entry, SYSTEMD_KINDS[kind] | COMMON_KEYS | {"kind"}, where, path, "systemd")
        for need in SYSTEMD_REQUIRED.get(kind, ()):
            if entry.get(need) in (None, ""):
                raise _fail(f"{where}: {kind}: needs {need}", path, "systemd")
        if entry.get("state") not in (None, "up", "down") and not str(entry["state"]).startswith("{{"):
            raise _fail(f"{where}: state must be up or down", path, "systemd")
        check_common(entry, allowed, where, path, "systemd")
        out.append(dict(entry))
    return out


def _systemd(role, ctx: dict, host, secrets: frozenset) -> list[Resource]:
    out: list[Resource] = []
    for entry in role.systemd:
        if not expr.truthy(entry.get("when"), ctx):
            continue
        kind = entry["kind"]
        f = {k: expr.resolve(v, ctx) for k, v in entry.items() if k not in COMMON_KEYS | {"kind"}}
        if kind == "unit":
            made = [Unit(name=f["name"], enabled=f.get("enabled"), state=f.get("state"))]
        elif kind == "time":
            made = [TimeSettings(**f)] if any(v is not None for v in f.values()) else []
        elif kind == "hostname":
            made = [] if host.container else [Hostname(name=str(f.get("name") or host.data.get("hostname") or host.name))]
        elif kind == "locale":
            made = [Locale(**f)] if any(v is not None for v in f.values()) else []
        else:
            made = [drop_in(f["unit"], f["name"], f["content"], restart_unit=f.get("restart", True))]
        out += [placed(r, role, entry, secrets) for r in made]
    return out
```

`build_entries` becomes `[*_packages(role, ctx, secret_options), *_systemd(role, ctx, host, secret_options)]`. In `contract.py`: `"systemd"` into `ROLE_NOTE_KEYS`, `RoleDef.systemd`, `parse_systemd(...)` in `parse_role`. (`systemd` is not in `ROLE_NOTE_RESERVED`; nothing to remove.)

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/roles -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/bastet/roles tests/roles/test_role_systemd_entries.py
git commit -m "roles: systemd: entries (unit, time, hostname, locale, dropin)"
```

---

### Task 3b: Plain-text passwords in the users block

> **As built (supersedes the openssl text below).** Hashing uses the system crypt library (libxcrypt, through `ctypes`) on the machine running Bastet, not `openssl`. `passwords.hash(password, scheme)` makes a fresh setting for `yescrypt`, `sha512` or `sha256`; `passwords.matches` verifies a stored hash of any scheme the library knows (so a correct `$y$` password shows no change); `passwords.scheme_for(login_defs)` reads `ENCRYPT_METHOD`. `User` reads `/etc/login.defs` and writes the host's own default scheme (SHA-512 when unknown). A scheme change alone never rewrites a matching password. The managed hosts need nothing extra.

**Files:**
- Create: `src/bastet/engine/passwords.py`
- Modify: `src/bastet/engine/users.py` (`User`), `src/bastet/data/roles/users/role.yml` (`users.<name>.password`); `src/bastet/roles/builtin.py` needs nothing if `_kw` already passes fields through (confirm)
- Test: `tests/engine/test_passwords.py`, `tests/engine/test_user_password.py` (look at the existing `tests/engine` files for the pattern; basenames must stay unique across `tests/`)

**Why:** a secret note holds the password in plain text when unlocked; Bastet makes the hash on the machine running it and sends only the hash to the host (`chpasswd -e` takes any standard crypt hash). The hashing is done by `openssl passwd -6` on the controller, so no hashing code lives in Bastet. Requirement to document: the machine running Bastet needs `openssl`; the managed hosts need nothing extra. Bastet always writes SHA-512 (`$6$`) hashes, whatever a host's own default is (Debian's newer default is yescrypt): an existing yescrypt hash reads as one change and is replaced.

**Interfaces:**
- Produces (`engine/passwords.py`):
  - `hash(password: str, salt: str) -> str` — runs `openssl passwd -6 -salt <salt> -stdin` with the password on stdin (never on a command line) and returns `$6$<salt>$<86 chars>`; the salt is cut to 16 characters. A password containing a line break raises `BastetError("a password can't contain a line break")`. Without `openssl` on the PATH (`shutil.which`) it raises `BastetError("hashing a plain-text password needs openssl on the machine running Bastet; install it, or give password_hash instead")`. An `openssl` failure raises `BastetError` with its first output line.
  - `new_salt() -> str` — 16 random characters from `./0-9A-Za-z` (`secrets.choice`).
  - `matches(password: str, stored: str) -> bool` — for a stored `$6$<salt>$<tail>` hash (exactly four `$`-separated parts) re-hashes `password` with its salt and compares with `secrets.compare_digest`; false for anything else (empty, `!`, `*`, other schemes, `$6$rounds=…`, which is replaced once by a default-rounds hash).
  - `User.password: str | None = None` (plain text, new field). `password` together with `password_hash` raises `ValueError("give password or password_hash, not both")` in `__post_init__`.
- Behaviour: `compare()` treats the account as correct when `passwords.matches(self.password, current["password"])` (the hash `current()` reads from `/etc/shadow`); otherwise it reports `FieldChange("password", "(hidden)", "(new)")`, as for `password_hash` today. `update_password: on_create` leaves an existing account's password alone. `fix()` sets it with the existing `_password_cmd` using a fresh `passwords.hash(self.password, passwords.new_salt())`, so the plain text never reaches the host.

- [ ] **Step 1: Write the failing tests**

`tests/engine/test_passwords.py` (tests that need the binary are skipped when it is missing; the missing-binary test does not need it):

```python
import shutil

import pytest

from bastet.core.errors import BastetError
from bastet.engine import passwords

needs_openssl = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not installed")


@needs_openssl
def test_known_vector_from_the_sha_crypt_specification():
    assert passwords.hash("Hello world!", "saltstring") == (
        "$6$saltstring$svn8UoSVapNtMuq1ukKS4tPQd8iKwSMHWjl/O817G3uBnIFNjnQJuesI68u4OTLiBFdcbYEdFCoEOfaS35inz1")


@needs_openssl
def test_a_long_salt_is_cut_to_16_characters():
    assert passwords.hash("x", "a" * 40).startswith("$6$" + "a" * 16 + "$")


@needs_openssl
def test_matches_uses_the_stored_salt():
    stored = passwords.hash("correct horse", passwords.new_salt())
    assert passwords.matches("correct horse", stored) and not passwords.matches("wrong", stored)


@pytest.mark.parametrize("stored", ["", "!", "*", "x", "$1$abc$def", "$6$", "$6$salt", "$6$rounds=6000$abc$def", "$y$j9T$salt$hash"])
def test_matches_is_false_for_anything_that_is_not_a_plain_sha512_hash(stored):
    assert passwords.matches("pw", stored) is False


def test_new_salt_is_16_valid_characters_and_varies():
    a, b = passwords.new_salt(), passwords.new_salt()
    assert len(a) == 16 and a != b and set(a) <= set("./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")


def test_a_password_with_a_line_break_is_refused():
    with pytest.raises(BastetError, match="can't contain a line break"):
        passwords.hash("a\nb", "salt")


def test_without_openssl_the_error_says_what_to_install(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(BastetError, match="needs openssl on the machine running Bastet"):
        passwords.hash("pw", "salt")


@needs_openssl
def test_the_password_goes_to_openssl_on_stdin_never_the_command_line(monkeypatch):
    import subprocess

    seen = {}
    real = subprocess.run

    def spy(cmd, **kw):
        seen["cmd"], seen["input"] = cmd, kw.get("input")
        return real(cmd, **kw)

    monkeypatch.setattr(subprocess, "run", spy)
    passwords.hash("s3cret-value", "abc")
    assert "s3cret-value" not in " ".join(seen["cmd"]) and "s3cret-value" in seen["input"]
```

`tests/engine/test_user_password.py`: copy the construction pattern of the existing `User` tests under `tests/engine/` and assert (use the `needs_openssl` mark for tests that hash):
1. `User(name="root", password="a", password_hash="$6$s$h")` raises `ValueError` matching `password or password_hash, not both`.
2. `compare` gives no password change when the current hash was made from the same plain text with any salt, and `FieldChange("password", "(hidden)", "(new)")` when it was made from other text or the current hash is `""`, `!` or `*`.
3. With `update_password="on_create"` an existing account with a different hash gives no change.
4. `fix` for a password change returns one `chpasswd -e` command containing a `$6$` hash, and the plain text appears in no returned command.
5. The report text for the change never contains the plain text.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/engine/test_passwords.py tests/engine/test_user_password.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement `src/bastet/engine/passwords.py`**

```python
"""Password hashes for the users block: SHA-512 crypt made by `openssl passwd` on the machine running Bastet."""

import secrets
import shutil
import subprocess

from bastet.core.errors import BastetError

_ALPHABET = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def new_salt() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(16))


def hash(password: str, salt: str) -> str:
    if "\n" in password or "\r" in password:
        raise BastetError("a password can't contain a line break")
    if shutil.which("openssl") is None:
        raise BastetError("hashing a plain-text password needs openssl on the machine running Bastet; "
                          "install it, or give password_hash instead")
    done = subprocess.run(["openssl", "passwd", "-6", "-salt", salt[:16], "-stdin"], input=password + "\n",
                          capture_output=True, text=True, check=False)
    out = done.stdout.strip()
    if done.returncode != 0 or not out.startswith("$6$"):
        first = (done.stderr.strip().splitlines() or ["no output"])[0]
        raise BastetError(f"openssl could not hash the password: {first}")
    return out


def matches(password: str, stored: str) -> bool:
    parts = stored.split("$")
    if len(parts) != 4 or parts[1] != "6" or not parts[2] or not parts[3] or parts[2].startswith("rounds="):
        return False
    return secrets.compare_digest(hash(password, parts[2]), stored)
```

Then `User`: add `password: str | None = None`; the both-given check in `__post_init__`; in `current()`/`compare()` use `passwords.matches`; in `fix()` build the command with a fresh hash (`password_hash` keeps its current path). `users/role.yml`: add `password: {type: string, secret: true, description: "Plain-text password; Bastet hashes it (SHA-512) with openssl on the machine running Bastet. Set it with a secret: reference, never write it in the note"}` beside `password_hash`, and one example. Add one line to `src/bastet/data/docs/using_secrets.md` (or the users role page text): "Passwords: the secret holds the plain text; hashing needs `openssl` on the machine running Bastet."

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/engine tests/roles -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/bastet tests/engine
git commit -m "users: plain-text passwords from secrets, hashed on the controller with openssl passwd"
```

**Review Focus for this task:** a `*`, `!` or empty shadow hash (locked or no password) never counts as a match; the plain text never appears in a command line (openssl's or the host's), report, diff or run record; the same plain text with a different salt on the host is not a change; a missing `openssl` is a clear error, not a traceback.

---

### Task 4: `users:` entries

**Files:**
- Modify: `src/bastet/roles/entries.py`, `src/bastet/roles/contract.py`
- Test: `tests/roles/test_role_users_entries.py`

**Interfaces:**
- Consumes: Task 2/3 helpers; `engine.users` (`User`, `Group`, `AuthorizedKey`, `sudoer`).
- Produces: `parse_users`, `RoleDef.users`, `users` in `ROLE_NOTE_KEYS`. Kinds:

| kind | keys | resource |
|---|---|---|
| `user` | `name` (required) plus the `User` fields: `uid, group, groups, append, comment, home, create_home, move_home, shell, system, password, password_hash, update_password, locked, expires, max_days, min_days, warn_days, inactive_days, non_unique, skeleton` | `User` |
| `group` | `name` (required), `gid`, `system`, `members`, `append_members` | `Group` |
| `key` | `user`, `key` (required), `options`, `path`, `state` | `AuthorizedKey` |
| `sudoer` | `name` (required), `rules, user, group, commands, runas, hosts, nopasswd, setenv, defaults` | `sudoer(name, ...)` |

**Passwords from secrets.** A role declares `root_password: {type: string, secret: true}`, uses `password: "{{ root_password }}"` in the `user` entry, and the owner sets it with `bastet secret set <host> <role> root_password`. The secret note holds the **plain text** password (`bastet secret unlock` shows it as plain text, `lock` re-encrypts it); Bastet hashes it when it runs (Task 3b), so no one keeps a crypt hash by hand. `password_hash` (an already-made crypt hash) is still accepted; giving both is refused. Only the entries that mention a secret option are marked secret, so the rest of the role still shows its diffs. `root` is an ordinary user name here (only `bastet` is refused).

An entry whose `name` (user/group/sudoer) or `user` (key) is `bastet` is refused at parse time (`the bastet account is managed by Bastet itself`). Lists become tuples. A `password_hash` that resolves from a `secret:` option works through the existing option mechanism (the whole value is the option), no new code.

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path

import pytest
import yaml

from bastet.core.errors import BastetError
from bastet.engine.files import File
from bastet.engine.users import AuthorizedKey, Group, User
from bastet.roles.builtin import HostInfo
from bastet.roles.contract import parse_role
from bastet.roles.declarative import build


def role(tmp_path, users, options=None):
    folder = tmp_path / "demo"
    folder.mkdir(exist_ok=True)
    data = {"bastet": "role-definition", "name": "demo", "version": "1.0.0", "api": 0, "description": "A demo role",
            "options": options or {"shell": {"type": "string"}}, "users": users}
    path = folder / "demo role.md"
    path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\nNotes.\n", encoding="utf-8")
    return parse_role(path)


def built(r, values=None):
    host = HostInfo(name="vps1", type="vps", data={"os": "Arch Linux"}, root=Path("/x"), lab={})
    [batch] = build(r, values or {}, host)
    return batch.resources


def test_user_group_key_sudoer(tmp_path):
    r = role(tmp_path, [
        {"kind": "group", "name": "git", "system": True},
        {"kind": "user", "name": "git", "system": True, "shell": "{{ shell }}", "groups": ["git"]},
        {"kind": "key", "user": "git", "key": "ssh-ed25519 AAAAexample"},
        {"kind": "sudoer", "name": "git", "user": "git", "commands": ["/usr/bin/systemctl"], "nopasswd": True},
    ])
    g, u, k, s = built(r, {"shell": "/bin/bash"})
    assert isinstance(g, Group) and g.system is True
    assert isinstance(u, User) and (u.shell, u.groups, u.system) == ("/bin/bash", ("git",), True)
    assert isinstance(k, AuthorizedKey) and (k.user, k.key) == ("git", "ssh-ed25519 AAAAexample")
    assert isinstance(s, File) and s.path == "/etc/sudoers.d/git" and "NOPASSWD:" in s.content and s.validate == "visudo -cf %s"


def test_a_password_hash_from_a_secret_option_marks_only_its_entry_secret(tmp_path):
    r = role(tmp_path, [
        {"kind": "user", "name": "root", "password": "{{ pw }}", "create_home": False},
        {"kind": "group", "name": "ops"},
    ], options={"pw": {"type": "string", "secret": True}})
    host = HostInfo(name="vps1", type="vps", data={"os": "Arch Linux"}, root=Path("/x"), lab={})
    [batch] = build(r, {"pw": "correct horse"}, host, secret_options=frozenset({"pw"}))
    root, ops = batch.resources
    assert root.password == "correct horse" and root.secret is True
    assert ops.secret is False


def test_without_secret_options_nothing_is_secret(tmp_path):
    r = role(tmp_path, [{"kind": "user", "name": "root", "password": "{{ pw }}"}], options={"pw": {"type": "string", "secret": True}})
    assert built(r, {"pw": "correct horse"})[0].secret is False


def test_when_skips_an_entry(tmp_path):
    r = role(tmp_path, [{"kind": "user", "name": "git", "when": "shell"}])
    assert built(r, {}) == [] and len(built(r, {"shell": "/bin/sh"})) == 1


@pytest.mark.parametrize("entry, message", [
    ({"name": "x"}, "users\\[0\\]: needs a kind"),
    ({"kind": "role", "name": "x"}, "kind must be one of"),
    ({"kind": "user"}, "user: needs a name"),
    ({"kind": "key", "user": "git"}, "key: needs key"),
    ({"kind": "user", "name": "bastet"}, "bastet account is managed by Bastet itself"),
    ({"kind": "key", "user": "bastet", "key": "k"}, "bastet account is managed by Bastet itself"),
    ({"kind": "sudoer", "name": "bastet", "user": "x"}, "bastet account is managed by Bastet itself"),
    ({"kind": "user", "name": "x", "zzz": 1}, "zzz"),
    ({"kind": "user", "name": "x", "password": "a", "password_hash": "$6$s$h"}, "password or password_hash, not both"),
    ({"kind": "user", "name": "{{ nope }}"}, "names no option or fact: nope"),
])
def test_users_entry_errors(tmp_path, entry, message):
    with pytest.raises(BastetError, match=message):
        role(tmp_path, [entry])
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/roles/test_role_users_entries.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `entries.py`:

```python
from bastet.engine.users import AuthorizedKey, Group, User, sudoer

USER_FIELDS = {"name", "uid", "group", "groups", "append", "comment", "home", "create_home", "move_home", "shell", "system",
               "password", "password_hash", "update_password", "locked", "expires", "max_days", "min_days", "warn_days",
               "inactive_days", "non_unique", "skeleton"}
USERS_KINDS = {
    "user": USER_FIELDS,
    "group": {"name", "gid", "system", "members", "append_members"},
    "key": {"user", "key", "options", "path", "state"},
    "sudoer": {"name", "rules", "user", "group", "commands", "runas", "hosts", "nopasswd", "setenv", "defaults"},
}
USERS_REQUIRED = {"user": ("name",), "group": ("name",), "key": ("user", "key"), "sudoer": ("name",)}
BASTET_USER = "bastet"


def parse_users(path: Path, items: object, options: dict) -> list[dict]:
    if not isinstance(items, list):
        raise _fail("users must be a list", path, "users")
    allowed, out = set(options), []
    for i, entry in enumerate(items):
        where = f"users[{i}]"
        if not isinstance(entry, dict):
            raise _fail(f"{where}: each entry is a map", path, "users")
        kind = entry.get("kind")
        if kind is None:
            raise _fail(f"{where}: needs a kind", path, "users")
        if kind not in USERS_KINDS:
            raise _fail(f"{where}: kind must be one of {', '.join(USERS_KINDS)}", path, "users")
        _unknown(entry, USERS_KINDS[kind] | COMMON_KEYS | {"kind"}, where, path, "users")
        for need in USERS_REQUIRED[kind]:
            if entry.get(need) in (None, ""):
                raise _fail(f"{where}: {kind}: needs {need}", path, "users")
        if entry.get("password") is not None and entry.get("password_hash") is not None:
            raise _fail(f"{where}: give password or password_hash, not both", path, "users")
        if BASTET_USER in (entry.get("name") if kind != "key" else entry.get("user"), entry.get("user")):
            raise _fail(f"{where}: the bastet account is managed by Bastet itself", path, "users")
        check_common(entry, allowed, where, path, "users")
        out.append(dict(entry))
    return out


def _tuples(fields: dict) -> dict:
    return {k: tuple(v) if isinstance(v, list) else v for k, v in fields.items() if v is not None}


def _users(role, ctx: dict, secrets: frozenset) -> list[Resource]:
    out: list[Resource] = []
    for entry in role.users:
        if not expr.truthy(entry.get("when"), ctx):
            continue
        kind = entry["kind"]
        f = _tuples({k: expr.resolve(v, ctx) for k, v in entry.items() if k not in COMMON_KEYS | {"kind"}})
        if kind == "user":
            made = User(**f)
        elif kind == "group":
            made = Group(**f)
        elif kind == "key":
            made = AuthorizedKey(**f)
        else:
            made = sudoer(f.pop("name"), **f)
        out.append(placed(made, role, entry, secrets))
    return out
```

`build_entries` returns `[*_packages(...), *_users(role, ctx, secret_options), *_systemd(...)]` (the engine orders by slot, so the list order is irrelevant). Add `users` to `ROLE_NOTE_KEYS`, `RoleDef.users`, and the parse call. Note: the `entry.get("user")` check also catches a `sudoer` for user `bastet` and `user` entries are caught by `name`; `key` entries by `user`.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/roles -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/bastet/roles tests/roles/test_role_users_entries.py
git commit -m "roles: users: entries (user, group, key, sudoer); the bastet account is refused"
```

---

### Task 5: `files:` entries for whole files, directories, links, lines and blocks

**Files:**
- Modify: `src/bastet/roles/contract.py` (`FILE_KEYS`, `_file_entry`, `parse_role`), `src/bastet/roles/entries.py`, `src/bastet/roles/declarative.py`
- Test: `tests/roles/test_role_files_entries.py`

**Interfaces:**
- Consumes: `expr`, `check_common`, `placed`, `engine.files` (`File`, `Directory`, `Symlink`, `Line`, `Block`), `engine.systemd.restart/reload`, `engine.templates.render_template`.
- Produces: `FILE_KEYS` gains `content, template, directory, link, line, block, match, unique, comment, marker, restart, reload, when`. An entry needs `path` and **exactly one** of `edit`, `render`, `content`, `template`, `directory`, `link`, `line`, `block`. Key rules (all raise at parse time, naming the key):

| form | extra keys allowed | resource |
|---|---|---|
| `content` or `template` | `mode, owner, group, validate, restart, reload, backup` | `File` |
| `directory: true` | `mode, owner, group` | `Directory` |
| `link: <target>` | none | `Symlink` |
| `line` | `match`, `unique`, `validate`, `restart`, `reload` | `Line` |
| `block` | `marker` (required), `comment, validate, restart, reload` | `Block` |
| existing `edit` / `render` | as today, plus `when`, `restart`, `reload` | unchanged |

  `template:` names a file in the role's own folder (`role.path.parent`); a name with `..`, an absolute path or a path separator that leaves the folder is refused at parse time. The context passed to the template is the Task 1 context. `content` and `template` produce text (a `None` result is an error: `files[i]: content resolved to nothing`). `restart` / `reload` accept unit-name lists and build `on_change` triggers with `restart(unit)` / `reload(unit)`. `FILE_KEYS` and `_file_entry` are used by the existing `edit`/`render` entries; their behaviour, including the "mode/owner/group don't apply to edit" refusal, is unchanged.
- `RoleDef.entries` (the existing files list) now holds all forms; `declarative.build()` routes `edit`/`render` entries as today and every other form to `entries.build_files(role, values, host)`. A `when:` false skips an entry **and** its `backup` command.

- [ ] **Step 1: Write the failing tests**

```python
from pathlib import Path

import pytest
import yaml

from bastet.core.errors import BastetError
from bastet.engine.command import Command
from bastet.engine.files import Block, Directory, File, Line, Symlink
from bastet.roles.builtin import HostInfo
from bastet.roles.contract import parse_role
from bastet.roles.declarative import build


def role(tmp_path, files, options=None, template=None):
    folder = tmp_path / "demo"
    folder.mkdir(exist_ok=True)
    if template is not None:
        (folder / "site.j2").write_text(template, encoding="utf-8")
    data = {"bastet": "role-definition", "name": "demo", "version": "1.0.0", "api": 0, "description": "A demo role",
            "options": options or {"domain": {"type": "string"}, "on": {"type": "bool"}}, "files": files}
    path = folder / "demo role.md"
    path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\nNotes.\n", encoding="utf-8")
    return parse_role(path)


def built(r, values=None):
    host = HostInfo(name="vps1", type="vps", data={"os": "Arch Linux"}, root=Path("/x"), lab={})
    [batch] = build(r, values or {}, host)
    return batch.resources


def test_content_becomes_a_file_with_triggers(tmp_path):
    [f] = built(role(tmp_path, [{"path": "/etc/x.conf", "content": "host {{ domain }}\n", "mode": "0644", "reload": ["example-app.service"]}]),
                {"domain": "example.net"})
    assert isinstance(f, File) and f.content == "host example.net\n" and f.mode == "0644"
    assert [t.label for t in f.on_change] == ["reload example-app.service"]


def test_template_from_the_roles_folder(tmp_path):
    r = role(tmp_path, [{"path": "/etc/site", "template": "site.j2"}], template="{{ domain }}.{{ host.name }}\n")
    [f] = built(r, {"domain": "example.net"})
    assert f.content == "example.net.vps1\n"


def test_directory_link_line_block(tmp_path):
    r = role(tmp_path, [
        {"path": "/etc/example-app/conf.d", "directory": True, "mode": "0755"},
        {"path": "/srv/current", "link": "/srv/app"},
        {"path": "/etc/default/x", "line": "A=1", "match": "^A=", "unique": True},
        {"path": "/etc/x.conf", "block": "k = v", "marker": "bastet x", "comment": ";"},
    ])
    d, l, ln, b = built(r)
    assert isinstance(d, Directory) and d.mode == "0755"
    assert isinstance(l, Symlink) and l.target == "/srv/app"
    assert isinstance(ln, Line) and (ln.line, ln.match, ln.unique) == ("A=1", "^A=", True)
    assert isinstance(b, Block) and (b.marker, b.comment) == ("bastet x", ";")


def test_when_skips_an_entry_and_its_backup(tmp_path):
    r = role(tmp_path, [{"path": "/etc/pacman.conf", "edit": "ini", "backup": True, "when": "on"}], options={
        "on": {"type": "bool"}, "n": {"type": "int", "key": "N", "section": "options"}})
    assert built(r, {"on": False, "n": 1}) == []
    assert any(isinstance(x, Command) for x in built(r, {"on": True, "n": 1}))


def test_content_that_resolves_to_nothing_is_an_error(tmp_path):
    with pytest.raises(BastetError, match="files\\[0\\]: content resolved to nothing"):
        built(role(tmp_path, [{"path": "/etc/x", "content": "{{ domain }}"}]))


@pytest.mark.parametrize("entry, message", [
    ({"path": "/x"}, "exactly one of"),
    ({"path": "/x", "content": "a", "link": "/y"}, "exactly one of"),
    ({"path": "/x", "directory": True, "restart": ["a.service"]}, "restart doesn't apply"),
    ({"path": "/x", "link": "/y", "mode": "0644"}, "mode doesn't apply"),
    ({"path": "/x", "block": "b"}, "block needs a marker"),
    ({"path": "/x", "template": "../site.j2"}, "template must be a file in the role's own folder"),
    ({"path": "/x", "template": "/etc/passwd"}, "template must be a file in the role's own folder"),
    ({"path": "/x", "content": "{{ nope }}"}, "names no option or fact: nope"),
    ({"path": "/x", "content": "a", "reload": "example-app.service"}, "reload must be a list"),
])
def test_files_entry_errors(tmp_path, entry, message):
    with pytest.raises(BastetError, match=message):
        role(tmp_path, [entry])
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/roles/test_role_files_entries.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

`contract.py`:
- `FILE_KEYS` becomes `{"path", "edit", "render", "mode", "owner", "group", "validate", "before", "after", "backup", "when", "restart", "reload", "content", "template", "directory", "link", "line", "match", "unique", "block", "marker", "comment"}`.
- `FILE_FORMS = ("edit", "render", "content", "template", "directory", "link", "line", "block")`.
- `_file_entry(path, entry, options)` (new `options` argument; update the one caller in `parse_role`): replace the `("edit" in entry) == ("render" in entry)` check with `if sum(f in entry for f in FILE_FORMS) != 1: raise ... "files entry needs exactly one of edit, render, content, template, directory, link, line or block"`. Keep every existing check. Add, per form, the allowed-extra-keys table above through a dict `FORM_KEYS = {"content": {...}, ...}` where a key outside `FORM_KEYS[form] | {"path", form, "when", "before", "after"}` raises `files entry: <key> doesn't apply to <form>`. For the existing forms keep today's rules (do not tighten `edit`/`render` beyond adding `when`, `restart`, `reload`). `block` without `marker` raises `files entry: block needs a marker`. `template` must satisfy `Path(t).name == t and t not in ("", ".", "..")` else `files entry: template must be a file in the role's own folder`. `restart`/`reload` must be lists of text else `files entry: reload must be a list of unit names`. Then call `entries.check_common(entry, set(options), "files[i]", path, "files")` — pass the index by changing the list comprehension in `parse_role` to `enumerate`. (`directory` must be `true`; a false `directory` raises `directory must be true`.)

`entries.py`: add `build_files(role, values, host, ctx)` handling the non-`edit`/`render` forms with `placed()`:

```python
from bastet.engine.files import Block, Directory, File, Line, Symlink
from bastet.engine.systemd import reload, restart
from bastet.engine.templates import render_template


def _triggers(entry: dict) -> dict:
    units = [restart(u) for u in entry.get("restart") or []] + [reload(u) for u in entry.get("reload") or []]
    return {"on_change": tuple(units)} if units else {}


def build_files(role, ctx: dict, entry: dict, i: int, secrets: frozenset = frozenset()) -> list[Resource]:
    path = entry["path"]
    if "directory" in entry:
        made = Directory(path=path, owner=entry.get("owner"), group=entry.get("group"), mode=entry.get("mode"))
    elif "link" in entry:
        made = Symlink(path=path, target=expr.resolve(entry["link"], ctx))
    elif "line" in entry:
        made = Line(path=path, line=expr.resolve(entry["line"], ctx), match=entry.get("match"), unique=bool(entry.get("unique")),
                    validate=entry.get("validate"), **_triggers(entry))
    elif "block" in entry:
        made = Block(path=path, block=expr.resolve(entry["block"], ctx), marker=entry["marker"], comment=entry.get("comment", "#"),
                     validate=entry.get("validate"), **_triggers(entry))
    else:
        if "template" in entry:
            content = render_template(role.path.parent, entry["template"], ctx)
        else:
            content = expr.resolve(entry["content"], ctx)
        if content is None:
            raise BastetError(f"{role.name}: files[{i}]: content resolved to nothing")
        made = File(path=path, content=str(content), owner=entry.get("owner"), group=entry.get("group"), mode=entry.get("mode"),
                    validate=entry.get("validate"), **_triggers(entry))
    return [placed(made, role, entry, secrets)]
```

(A `mode`/`owner`/`group` of `None` is accepted by the dataclasses.)

`declarative.py` `build()`: for each files entry compute `ctx` once, skip it when `not expr.truthy(entry.get("when"), ctx)` (before emitting its backup command), route `edit`/`render` as today (and attach `restart`/`reload` triggers to their resources only if present — not needed now, so keep unchanged), route other forms to `entries.build_files(role, ctx, entry, i, secret_options)`. Use `enumerate(role.entries)` for the index.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/roles -q`
Expected: all pass, including `test_pacman_role.py`, `test_apt_role.py`, `test_ini_settings.py` unchanged.

- [ ] **Step 5: Commit**

```bash
git add src/bastet/roles tests/roles/test_role_files_entries.py
git commit -m "roles: files: entries for whole files, templates, directories, links, lines and blocks"
```

---

### Task 6: Report accounts no role manages (users drift report)

**Files:**
- Modify: `src/bastet/engine/users.py` (new `UnaccountedUsers` resource), `src/bastet/roles/builtin.py` (`_users` adds it; `batches_for` fills `tracked`), `src/bastet/data/roles/users/role.yml` (three options)
- Test: `tests/roles/test_unaccounted_users.py`

**Interfaces:**
- Produces: `UnaccountedUsers(Resource)` in `engine/users.py`: `family = "Users"`, `slot = "reports"`, `root = False`, fields `tracked: tuple[str, ...] = ()`, `allowed: tuple[str, ...] = ()`, `system_accounts: bool = True`. Report-only like `Unaccounted` in `engine/packages.py` (`report_only()` true, `fix()` returns `[]`, never changes a host).
  - `reads()`: `Read("passwd", "getent passwd")` and `Read("defs", "grep -E '^(UID_MIN|UID_MAX)[[:space:]]' /etc/login.defs || true")`.
  - `current(results)` returns `{"unaccounted": (...)}`: every `getent passwd` account whose name is not in `tracked` or `allowed` (no built-in allowance: `root` and `bastet` show up like everyone else until a role manages them or `allowed` names them); with `system_accounts=False` only accounts with `UID_MIN <= uid <= UID_MAX` (1000 and 60000 when `login.defs` lacks them). Each entry is the text `name (uid 33, /usr/bin/nologin)`, sorted by uid.
  - `compare()` gives one `FieldChange("unaccounted", f"{n} accounts", "none")` when any are left; `diff_text()` lists up to 60 then `… N more`.
- Consumes: every `User` resource in every batch (any role, old format or Markdown) is tracked; `batches_for` fills `tracked` the way it already fills `Unaccounted.tracked`.
- Options on the `users` role (`role.yml`): `allowed` (list of account names fine without a role), `report_unaccounted` (bool, default true), `report_system_accounts` (bool, default true: `root`, `bastet` and system accounts such as `nobody` and `systemd-*` are included on purpose; the first real run shows how noisy that is and decides whether the default changes).

- [ ] **Step 1: Write the failing tests** in `tests/roles/test_unaccounted_users.py`

```python
from pathlib import Path

from bastet.core.shell import ProbeResult
from bastet.engine.users import UnaccountedUsers, User
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import check_values, load_roles, with_defaults
from bastet.roles.resolve import Applied

PASSWD = ("root:x:0:0:root:/root:/bin/bash\n"
          "bastet:x:1000:1000::/home/bastet:/bin/bash\n"
          "nobody:x:65534:65534:Kernel Overflow User:/:/usr/bin/nologin\n"
          "daemon:x:1:1::/:/usr/bin/nologin\n"
          "alice:x:1001:1001::/home/alice:/bin/bash\n"
          "bob:x:1002:1002::/home/bob:/bin/zsh\n"
          "broken-line\n")


def ok(text):
    return ProbeResult(0, text)


def current(resource, defs=""):
    return resource.current({"passwd": ok(PASSWD), "defs": ok(defs)})["unaccounted"]


def host():
    return HostInfo(name="vps1", type="vps", data={"os": "Arch Linux"}, root=Path("/x"), lab={})


def test_everything_not_tracked_or_allowed_is_reported_with_uid_and_shell():
    r = UnaccountedUsers(tracked=("alice",), allowed=("daemon",))
    assert current(r) == ("root (uid 0, /bin/bash)", "bastet (uid 1000, /bin/bash)", "bob (uid 1002, /bin/zsh)",
                          "nobody (uid 65534, /usr/bin/nologin)")


def test_root_and_bastet_show_up_until_tracked_or_allowed_and_a_broken_line_is_skipped():
    names = " ".join(current(UnaccountedUsers()))
    assert "root (uid 0" in names and "bastet (uid 1000" in names and "broken" not in names
    quiet = " ".join(current(UnaccountedUsers(allowed=("root",), tracked=("bastet",))))
    assert "root" not in quiet and "bastet" not in quiet


def test_system_accounts_can_be_left_out_using_login_defs_or_the_defaults():
    r = UnaccountedUsers(system_accounts=False)
    both = ("bastet (uid 1000, /bin/bash)", "alice (uid 1001, /bin/bash)", "bob (uid 1002, /bin/zsh)")
    assert current(r, "UID_MIN 1000\nUID_MAX 60000\n") == both
    assert current(r) == both


def test_it_is_a_report_and_never_a_fix():
    r = UnaccountedUsers()
    assert r.report_only() is True and r.compare({"unaccounted": ()}) == []
    [change] = r.compare({"unaccounted": ("bob (uid 1002, /bin/zsh)",)})
    assert (change.field, change.before, change.after) == ("unaccounted", "1 accounts", "none")
    assert r.fix([change], {"unaccounted": ("x",)}) == []


def test_users_from_every_role_are_tracked_and_the_options_apply():
    role = load_roles()["users"]
    values = with_defaults(role, check_values(role, {"users": {"alice": {}}, "allowed": ["daemon"], "report_system_accounts": False}, "users"))
    batches = batches_for([Applied(role, values)], host())
    [report] = [r for b in batches for r in b.resources if isinstance(r, UnaccountedUsers)]
    assert "alice" in report.tracked and report.allowed == ("daemon",) and report.system_accounts is False
    assert any(isinstance(r, User) and r.name == "alice" for b in batches for r in b.resources)


def test_report_unaccounted_false_adds_no_report():
    role = load_roles()["users"]
    values = with_defaults(role, check_values(role, {"report_unaccounted": False}, "users"))
    assert not [r for b in batches_for([Applied(role, values)], host()) for r in b.resources if isinstance(r, UnaccountedUsers)]
```

(If `Applied(role, values)`, `check_values` or `with_defaults` differ from this, copy the pattern in `tests/roles/test_package_baselines.py`; the assertions are the point.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/roles/test_unaccounted_users.py -q`
Expected: FAIL (`UnaccountedUsers` not defined).

- [ ] **Step 3: Implement**

`engine/users.py` (import `Read` and `FieldChange` from `engine.model` as the file's other resources do):

```python
@dataclass(frozen=True, kw_only=True)
class UnaccountedUsers(Resource):
    """Accounts on the host that no role manages or allows. Reported, never changed."""

    family: ClassVar[str] = "Users"
    slot: ClassVar[str] = "reports"
    tracked: tuple[str, ...] = ()
    allowed: tuple[str, ...] = ()
    system_accounts: bool = True
    root: bool = False

    @property
    def identity(self) -> str:
        return "unaccounted users"

    @property
    def label(self) -> str:
        return "unaccounted users"

    def report_only(self) -> bool:
        return True

    def desired(self):
        return {"tracked": self.tracked, "allowed": self.allowed, "system_accounts": self.system_accounts}

    def reads(self):
        return (Read("passwd", "getent passwd"),
                Read("defs", "grep -E '^(UID_MIN|UID_MAX)[[:space:]]' /etc/login.defs || true"))

    def current(self, results):
        limits = {"UID_MIN": 1000, "UID_MAX": 60000}
        for line in results["defs"].output.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0] in limits and parts[1].isdigit():
                limits[parts[0]] = int(parts[1])
        skip = set(self.tracked) | set(self.allowed)
        found = []
        for line in results["passwd"].output.splitlines():
            f = line.split(":")
            if len(f) < 7 or not f[2].isdigit() or f[0] in skip:
                continue
            uid = int(f[2])
            if not self.system_accounts and not limits["UID_MIN"] <= uid <= limits["UID_MAX"]:
                continue
            found.append((uid, f[0], f"{f[0]} (uid {uid}, {f[6]})"))
        return {"unaccounted": tuple(text for _, _, text in sorted(found))}

    def compare(self, current):
        n = len(current["unaccounted"])
        return [FieldChange("unaccounted", f"{n} accounts", "none")] if n else []

    def diff_text(self, current):
        names = list(current["unaccounted"])
        return "\n".join(names[:60] + ([f"… {len(names) - 60} more"] if len(names) > 60 else [])) or None

    def fix(self, changes, current):
        return []
```

`builtin._users`: when `v.get("report_unaccounted", True)`, append `UnaccountedUsers(allowed=tuple(v.get("allowed") or ()), system_accounts=v.get("report_system_accounts", True))` to the returned batch's resources. `batches_for`: compute `user_names = sorted({r.name for b in batches for r in b.resources if isinstance(r, User)})` next to `present`, and in the final loop add `replace(r, tracked=tuple(dict.fromkeys((*r.tracked, *user_names)))) if isinstance(r, UnaccountedUsers)`. `users/role.yml`: add the three options with the descriptions above and one example.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/roles tests/engine -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/bastet tests/roles/test_unaccounted_users.py
git commit -m "users: report accounts no role manages (unaccounted users), tracked across all roles"
```

**Review Focus for this task:** a passwd line with fewer than 7 fields or a non-numeric uid is skipped, not a crash; a host without `login.defs` falls back to 1000 and 60000; the report never writes anything.

---

### Task 7: Whole-contract check, docs and roadmap

**Files:**
- Create: `tests/roles/test_role_contract_end_to_end.py`
- Modify: `src/bastet/data/roles/files/role.yml` (description), `docs/specs/2026-10-10-bastet-roles-architecture-design.md` ("As built"), `docs/ROADMAP.md`
- Test: `uv run pytest -q`, `scripts/privacy-check`

**Interfaces:**
- Consumes: everything above; `bastet.roles.builtin.batches_for`, `bastet.roles.resolve.Applied`.

- [ ] **Step 1: Write the end-to-end test**

A demo role with every entry kind runs through `batches_for` and the engine's ordering, proving the resources land in block order (`packages` before `files` before `systemd`), that `provides` reaches them, and that `bastet doctor`'s role lint accepts it:

```python
from pathlib import Path

import yaml

from bastet.engine.slots import apply_order
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import parse_role
from bastet.roles.resolve import Applied


def demo(tmp_path):
    folder = tmp_path / "web"
    folder.mkdir()
    data = {"bastet": "role-definition", "name": "web", "version": "1.0.0", "api": 0, "description": "A demo web role",
            "options": {"domain": {"type": "string", "required": True}},
            "packages": ["example-app"],
            "users": [{"kind": "user", "name": "web", "system": True}],
            "files": [{"path": "/etc/example-app/app.conf", "content": "{{ domain }} {\n}\n", "reload": ["example-app.service"]}],
            "systemd": [{"kind": "unit", "name": "example-app.service", "enabled": True, "state": "up"}]}
    path = folder / "web role.md"
    path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\nNotes.\n", encoding="utf-8")
    return parse_role(path)


def test_a_role_of_block_entries_runs_in_block_order(tmp_path):
    role = demo(tmp_path)
    host = HostInfo(name="vps1", type="vps", data={"os": "Arch Linux"}, root=Path("/x"), lab={})
    batches = batches_for([Applied(role=role, values={"domain": "example.net"}, secret=False)], host)
    planned = [(b.name, [type("Item", (), {"resource": r}) for r in b.resources]) for b in batches]
    order = [type(i.resource).__name__ for i in apply_order(planned)]
    assert order == ["Package", "User", "File", "Unit"]
```

(Check `Applied`'s real constructor in `src/bastet/roles/resolve.py` and adjust the keyword names; the assertion on `order` is the point.)

- [ ] **Step 2: Run, fix, commit tests**

Run: `uv run pytest tests/roles/test_role_contract_end_to_end.py -q`
Expected: pass. If `Applied` takes other arguments, adapt the test, not the code.

- [ ] **Step 3: Docs**
  - `src/bastet/data/roles/files/role.yml` description: append "Planned settings edits, added when a role needs them: `env` (KEY=value files), `sshd`, `sysctl` (key = value)." (A one-line addition so the generated page lists them.)
  - Architecture spec, "As built" list: add an entry "**Block entries** (`packages:`, `systemd:`, `users:`, and `files:` forms `content`, `template`, `directory`, `link`, `line`, `block`), `when:` on every entry, and `{{ }}` values over options and host facts (`host`, `lab`). Blocks never call each other. Cross-host variables in the context are deferred."; close the §8 open question about the `when:` language ("a small Jinja subset over option values and facts" is what was built: sandboxed Jinja2 expressions).
  - `docs/ROADMAP.md`: tick VPS apps step 1 (☑), update the Building blocks table rows `packages`, `systemd`, `users`, `files` with "Callable from a Markdown role", the `users` row with "reports unaccounted accounts (the first run decides how to treat system accounts)", and the `reports` row with "unaccounted users"; change the "Next: the contract and the blocks" paragraph to say it is built and name the next step (`time` role).
  - `README`-level or `docs/` role-authoring docs: if a role-authoring document exists under `src/bastet/data/docs/`, add a short "Calling the building blocks" section with the example from "The contract this plan builds"; otherwise skip (do not create a new doc).

- [ ] **Step 4: Full checks**

Run: `uv run pytest -q` and `scripts/privacy-check`
Expected: all tests pass; privacy check reports nothing. Then `BASTET_CONTRACT=1 uv run pytest tests/contract -q` is **not** part of this plan (it needs the container hosts); note it for the owner's hard-testing pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "roles: end-to-end contract test; docs and roadmap for block entries"
```

---

## Self-review

- **Spec coverage:** every roadmap item for this step is covered: `packages`/`systemd`/`users` entries (Tasks 2–4), `when:` on every entry (Tasks 2, 5), `files` forms example-app needs (Task 5: content, directory, `reload`), the `{{ }}`/`when` language (Task 1), docs of planned `edit:` types (Task 7), the users drift report (Task 6). Not built on purpose: new `edit:` types (`env`, `sshd`), `systemd` timers/sysctl.d/…, `packages` `hold`/AUR policy, template cross-host variables, per-OS value maps (Jinja conditionals cover them).
- **Placeholders:** none; Task 5's `FORM_KEYS` table is spelled out in the interface table, and the one place that depends on real code (`Applied`'s constructor in Task 7) says how to adapt.
- **Type consistency:** `expr` functions (`check_text`, `check_when`, `resolve`, `truthy`, `context`) and `entries` helpers (`check_common`, `placed`, `build_entries`, `build_files`, `parse_packages|systemd|users`) keep one signature across tasks. `RoleDef` gains `packages`, `systemd`, `users`; `entries` is `build_files`'s input.
- **Review Focus mapping:** unknown names at parse time (Tasks 1–5 error tables); unset option drops the field (Task 2 `resolves to nothing`, Task 3 `time`); `when` skips the backup (Task 5); `bastet` account refused (Task 4); template escape (Task 5); sandbox (Task 1).
