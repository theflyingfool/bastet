# Account defaults: roles and OS defaults say which accounts are expected — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. In this repo, the `bastet-run-plan` skill supplies the Bastet-specific parts.

**Goal:** the unaccounted-users report stops listing accounts that are expected: `bastet` and `root`, the accounts a role brings (`alpm` with pacman, the `systemd-*` ones with the `systemd` block), and the accounts an OS always has (Arch first). The Arch OS group also comes with the `systemd` role applied by default.

**Architecture:** a role definition (Markdown or `role.yml`) gets an optional `accounts:` list. A new shipped data folder `src/bastet/data/oses/` holds one file per OS family (Arch only for now) with default `roles:` and always-present `accounts:`, loaded like host types. `sources_for` adds the OS default roles as a new source ranked between the type defaults and groups. `batches_for` hands the report everything expected: `root`, `bastet`, the OS accounts, the accounts of every applied role and every `User` a role manages. The bootstrap script creates `bastet` as a system account on new hosts.

**Tech Stack:** Python ≥3.12, pydantic, PyYAML, pytest, ruff.

**Spec:** `docs/specs/2026-10-10-bastet-roles-architecture-design.md` (roles are data over the blocks); background: `docs/plans/2026-10-11-bastet-roles-arch-2-contract-blocks.md`, Task 6 (the unaccounted-users report).

## Global Constraints

- **Unit tests** never touch the real inventory, `~/.config/bastet`, `~/.local/share/bastet`, `~/.ssh`, the real `~/.cache` or `$XDG_RUNTIME_DIR`; no network; `tmp_path` only; placeholder data only (see "Example data" in `docs/ROADMAP.md`).
- **Test file basenames unique across `tests/`** (no `__init__.py`).
- Every message goes through `bastet.ui.out`; no `typer.echo` in `src/`.
- The version is written only in `pyproject.toml`; do not bump it.
- Nothing deletes notes or records. Existing hosts keep their current `bastet` uid; only newly set-up hosts get the system account.
- `ruff check src tests` must pass before each commit (config is in `pyproject.toml`).
- `docs/roles.md` is generated; regenerate with `scripts/gen_roles_doc.py` whenever a `role.yml` or role note changes (a repo test checks it).
- Owner decisions (2026-10-11): `alpm` belongs to the pacman role; the six `systemd-*` accounts belong to the `systemd` block role (not to the OS file); `systemd-timesync` moves to the `time` role when that role exists; the other Arch always-present accounts go on the Arch OS defaults; Debian is ignored for now; `bastet` is always accounted; `root` always exists.
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

- An account is hidden from the report only when it is `root`/`bastet`, in the OS file, declared by a role that is applied to that host, managed by a `User` entry, or in `allowed`. A role that is not applied to the host hides nothing (a Debian host never has `alpm` hidden by the pacman role's declaration).
- An OS default role is overridable: a lab, group or host note setting the same role's options wins, and the resolved table names the origin as "OS default (arch)".
- A host with an unknown or missing OS gets no OS defaults and no error.
- Arch-like systems (`manjaro`, `endeavouros`, `cachyos`) get the Arch defaults.
- `bastet` is created with `--system` only when it does not exist yet; running the script on a host that has it changes nothing.
- A bad `accounts:` entry (not a list of valid account names) is refused when the role or OS file is read, with the file and key.

---

## File structure

| File | Responsibility |
|---|---|
| Create `src/bastet/core/osdefaults.py` | `OsDefaults` model, `load_os_defaults()`, `defaults_for(os_id)`; the account-name check shared with roles |
| Create `src/bastet/data/oses/arch.yml` | Arch: default roles and always-present accounts |
| Modify `src/bastet/roles/contract.py` | `RoleDef.accounts`; read `accounts:` in Markdown roles and `role.yml` |
| Modify `src/bastet/data/roles/systemd/role.yml`, `src/bastet/data/roles/pacman/pacman role.md` | Declare their accounts |
| Modify `src/bastet/roles/resolve.py` | OS default roles as a source |
| Modify `src/bastet/core/render.py` | The generated OS group note says what comes with it |
| Modify `src/bastet/roles/builtin.py` | `batches_for` fills the report's `tracked` from everything expected |
| Modify `src/bastet/core/bootstrap.py` | `useradd --system` |
| Tests (all new): `tests/core/test_osdefaults.py`, `tests/roles/test_role_accounts.py`, `tests/roles/test_os_default_roles.py`, `tests/roles/test_expected_accounts.py`; edit `tests/core/test_bootstrap.py` | One file per task |
| Modify `docs/ROADMAP.md`, `docs/roles.md` (generated), `src/bastet/data/docs/writing_roles.md` | Task 6 |

---

### Task 1: `accounts:` in role definitions

**Files:**
- Modify: `src/bastet/roles/contract.py` (`RoleDef`, `ROLE_NOTE_KEYS`, `parse_role`, `_parse_yml_role`)
- Modify: `src/bastet/data/roles/systemd/role.yml` (add `accounts:`), `src/bastet/data/roles/pacman/pacman role.md` (add `accounts:`)
- Create: `src/bastet/core/osdefaults.py` with only `check_accounts` for now (Task 2 adds the rest)
- Test: `tests/roles/test_role_accounts.py`

**Interfaces:**
- Produces:
  - `osdefaults.check_accounts(value: object, where: str, path: Path | None = None) -> tuple[str, ...]` — `None` gives `()`; otherwise it must be a list of text where each name matches `^[A-Za-z_][A-Za-z0-9_.-]*\$?$` (so `_talkd` and `systemd-network` are valid); duplicates are dropped keeping order; otherwise `BastetError(f"{where}: accounts must be a list of account names", file=path, key="accounts")` (and a message naming the bad entry).
  - `RoleDef.accounts: tuple[str, ...] = ()`.
  - A Markdown role note and a `role.yml` may carry `accounts:` (top level). `systemd`'s `role.yml` declares `systemd-coredump, systemd-network, systemd-oom, systemd-journal-remote, systemd-resolve, systemd-timesync`; pacman's note declares `alpm`.

- [ ] **Step 1: Write the failing tests** (`tests/roles/test_role_accounts.py`):

```python
import pytest
import yaml

from bastet.core.errors import BastetError
from bastet.core.osdefaults import check_accounts
from bastet.roles.contract import load_roles, parse_role


def note(tmp_path, **extra):
    folder = tmp_path / "demo"
    folder.mkdir(exist_ok=True)
    data = {"bastet": "role-definition", "name": "demo", "version": "1.0.0", "api": 0, "description": "A demo role", **extra}
    path = folder / "demo role.md"
    path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\nNotes.\n", encoding="utf-8")
    return path


def test_check_accounts_accepts_names_and_drops_duplicates():
    assert check_accounts(None, "x") == ()
    assert check_accounts(["alpm", "_talkd", "systemd-network", "alpm"], "x") == ("alpm", "_talkd", "systemd-network")


@pytest.mark.parametrize("bad", ["alpm", [1], ["bad name"], ["", "a"], [["nested"]], {"a": 1}])
def test_check_accounts_refuses_anything_else(bad):
    with pytest.raises(BastetError, match="accounts"):
        check_accounts(bad, "x")


def test_a_markdown_role_can_declare_accounts(tmp_path):
    assert parse_role(note(tmp_path, accounts=["alpm"])).accounts == ("alpm",)
    assert parse_role(note(tmp_path)).accounts == ()


def test_a_bad_accounts_key_names_the_file_and_key(tmp_path):
    with pytest.raises(BastetError) as e:
        parse_role(note(tmp_path, accounts="alpm"))
    assert "accounts" in str(e.value) and "demo role.md" in str(e.value)


def test_shipped_roles_declare_their_accounts():
    roles = load_roles()
    assert roles["pacman"].accounts == ("alpm",)
    assert set(roles["systemd"].accounts) == {"systemd-coredump", "systemd-network", "systemd-oom",
                                               "systemd-journal-remote", "systemd-resolve", "systemd-timesync"}
    assert roles["packages"].accounts == () and roles["apt"].accounts == ()
```

- [ ] **Step 2: Run to verify failure.** Run: `uv run pytest tests/roles/test_role_accounts.py -q`. Expected: FAIL (`bastet.core.osdefaults` missing).

- [ ] **Step 3: Implement.** In `core/osdefaults.py` (this task adds only the name check):

```python
"""Per-OS defaults (roles applied and accounts expected) and the shared account-name check."""

from __future__ import annotations

import re
from pathlib import Path

from bastet.core.errors import BastetError

ACCOUNT = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*\$?$")


def check_accounts(value: object, where: str, path: Path | None = None) -> tuple[str, ...]:
    """A list of account names (accounts a role or an OS expects on a host), or () when absent."""
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) and ACCOUNT.match(v) for v in value):
        bad = next((v for v in value if not (isinstance(v, str) and ACCOUNT.match(v))), None) if isinstance(value, list) else value
        raise BastetError(f"{where}: accounts must be a list of account names (letters, digits, _ . -), not {bad!r}",
                          file=path, key="accounts")
    return tuple(dict.fromkeys(value))
```

In `contract.py`: add `"accounts"` to `ROLE_NOTE_KEYS`; `RoleDef.accounts: tuple[str, ...] = ()`; in `parse_role` (inside the existing `try`, so the key lookup in the error handler gets the line) `accounts = check_accounts(data.get("accounts"), f"role {name}", path)` and pass `accounts=accounts` to `RoleDef(...)`; in `_parse_yml_role` do the same with `raw.get("accounts")`. Add the two shipped declarations (`accounts:` list at the top level of `systemd/role.yml`; `accounts: [alpm]` in `pacman role.md` frontmatter next to `provides`). Regenerate `docs/roles.md` if its test demands.

- [ ] **Step 4: Run to verify pass.** Run: `uv run pytest tests/roles tests/core/test_docs.py -q && ruff check src tests`. Expected: pass.

- [ ] **Step 5: Commit** `git add src/bastet/core/osdefaults.py src/bastet/roles/contract.py src/bastet/data/roles/systemd/role.yml "src/bastet/data/roles/pacman/pacman role.md" tests/roles/test_role_accounts.py docs/roles.md` with message `roles: accounts: key in role definitions; systemd and pacman declare theirs`.

---

### Task 2: OS defaults data and loader

**Files:**
- Modify: `src/bastet/core/osdefaults.py`
- Create: `src/bastet/data/oses/arch.yml`
- Test: `tests/core/test_osdefaults.py`

**Interfaces:**
- Produces in `osdefaults.py`:
  - `class OsDefaults(BaseModel)` (`extra="forbid"`): `name: str`, `description: str = ""`, `roles: dict[str, dict] = {}`, `accounts: tuple[str, ...] = ()` (validated through `check_accounts`).
  - `load_os_defaults(directory: Path | None = None) -> dict[str, OsDefaults]` — reads every `*.yml` in `directory` (default: the packaged `bastet/data/oses`), keyed by `name`; an invalid file raises `BastetError("invalid OS defaults: …", file=path)`.
  - `defaults_for(os_id: str | None, directory: Path | None = None) -> OsDefaults | None` — `None` for a missing or unknown OS; any id in `core.osinfo.ARCH_LIKE` maps to `arch`.
- `data/oses/arch.yml`:

```yaml
name: arch
description: Arch Linux and Arch-based systems
roles:
  systemd: {}
accounts: [bin, daemon, mail, ftp, http, nobody, dbus, tss, uuidd, _talkd]
```

(`root` and `bastet` are built in everywhere, Task 4; `alpm` comes from pacman and the `systemd-*` accounts from `systemd`.)

- [ ] **Step 1: Failing tests** (`tests/core/test_osdefaults.py`): the shipped Arch file loads with `systemd` in `roles` and the accounts above; `defaults_for("manjaro")`, `("endeavouros")`, `("cachyos")` give the Arch object; `defaults_for(None)`, `("debian")`, `("fedora")` give `None`; a temp folder with an unknown key, a bad account name, or invalid YAML raises `BastetError` naming the file; `load_os_defaults(tmp_path)` of an empty folder returns `{}`.
- [ ] **Step 2: Run, see it fail.** `uv run pytest tests/core/test_osdefaults.py -q`.
- [ ] **Step 3: Implement** the model and loader, mirroring `core/hosttypes.py` (`_shipped_dir()` via `importlib.resources`, `yaml.safe_load`, `ValidationError` handling), with `field_validator("accounts", mode="before")` calling `check_accounts`. Add `src/bastet/data/oses/arch.yml`. Check that the wheel includes the new folder (hatch packages `src/bastet`, so data files under it ship; confirm by listing `src/bastet/data` handling in `pyproject.toml`, no change expected).
- [ ] **Step 4: Run, see it pass, ruff.**
- [ ] **Step 5: Commit** `core: per-OS defaults (roles and expected accounts), Arch first`.

---

### Task 3: OS default roles as a source

**Files:**
- Modify: `src/bastet/roles/resolve.py` (`sources_for`), `src/bastet/core/render.py` (the generated OS group note body)
- Test: `tests/roles/test_os_default_roles.py`; run the existing `tests/core` render tests and `tests/cli/test_add_role.py` unchanged (edit one only if a pinned body text changes, and say which)

**Interfaces:**
- Consumes: `osdefaults.defaults_for`, `core.osinfo.os_id`, `core.hostview.host_data`.
- Produces: in `sources_for`, after the host type's defaults and before the group/role-file loop, for the host's OS: `Source(role, f"OS default ({defaults.name})", (1, 1), dict(values or {}))` for each `defaults.roles` item. Rank `(1, 1)` sorts after the type default `(1,)` and before groups `(2, …)` and hosts `(3,)`, so every group, host and lab-level note can override it. The resolved table's origin label is that text.
- The generated OS group body (`render.py`, the loop over `oses_seen`) gains, when `defaults_for(ident)` exists and has roles: a line `Comes with: <role>, <role>.` and the sentence `Set that role's options in a role file to change them.` Group notes of OS ids with no defaults are unchanged byte for byte.

- [ ] **Step 1: Failing tests** (`tests/roles/test_os_default_roles.py`): build a small inventory under `tmp_path` the way `tests/roles/test_resolved_table.py` does (lab, one host with `os: Arch Linux`, one with `os: Debian GNU/Linux 13 (trixie)`, one with no OS), load roles/types, call `resolve(...)`, and assert:
  1. the Arch host's applied roles include `systemd` with `origins`/sources labelled `OS default (arch)`, and the Debian host and the no-OS host have no `systemd` unless a note adds it;
  2. a group note applying `systemd` with `timezone: UTC` to the Arch host wins over the (empty) default, and the merged value is `UTC`; a host note beats the group;
  3. an Arch-like host (`os: Manjaro Linux`) also gets it;
  4. `render`'s generated OS group note for `arch` contains `Comes with: systemd.`, and the one for `debian` is unchanged (compare with the text produced before this task).
- [ ] **Step 2: Run, see them fail.**
- [ ] **Step 3: Implement** (the lookup uses `os_id(host_data(inv, host, types))`; an unknown or missing OS returns before touching anything).
- [ ] **Step 4: Run** `uv run pytest tests/roles tests/core tests/cli -q && ruff check src tests`.
- [ ] **Step 5: Commit** `roles: OS default roles (Arch comes with systemd) as an overridable source; the generated OS group says so`.

---

### Task 4: The report knows what is expected

**Files:**
- Modify: `src/bastet/roles/builtin.py` (`batches_for`, tracking loop)
- Test: `tests/roles/test_expected_accounts.py`; adjust `tests/roles/test_unaccounted_users.py` only where its expectations say `root`/`bastet` always show (they no longer do when the OS or role provides them — see below)

**Interfaces:**
- Consumes: `RoleDef.accounts` (Task 1), `osdefaults.defaults_for` (Task 2), `HostInfo.os_id`, `Applied`.
- Produces: `BASE_ACCOUNTS = ("root", "bastet")` in `builtin.py`. In `batches_for`, the tracking loop for `UnaccountedUsers` becomes `tracked = BASE_ACCOUNTS + os_accounts + role_accounts + user_names`, where `os_accounts` is `defaults_for(host.os_id).accounts` (or `()`), `role_accounts` is the union of `a.role.accounts` over the applied roles, and `user_names` is the existing set of `User` resources' names.
- Behaviour: `root` and `bastet` never appear in the report on any host. A role's accounts are hidden only when that role is applied to the host. Everything else unchanged (`allowed`, `report_system_accounts`).

- [ ] **Step 1: Failing tests** (`tests/roles/test_expected_accounts.py`), using `batches_for` the way `tests/roles/test_unaccounted_users.py` does:
  1. Arch host, `users` role plus `systemd` and `pacman` applied: the report's `tracked` contains `root`, `bastet`, `bin`, `nobody`, `dbus`, `alpm`, `systemd-network`, `systemd-timesync`;
  2. Arch host with only the `users` role: `tracked` has `root`, `bastet` and the OS accounts but not `alpm` and not `systemd-network`;
  3. Debian host with `pacman` not applied: `alpm` is not tracked;
  4. unknown-OS host: `tracked` is `root`, `bastet` and the managed users;
  5. running `UnaccountedUsers.current` over a passwd fixture of an Arch host (root, bastet, bin, daemon, nobody, dbus, systemd-network, alpm, alice) with `tracked` built by `batches_for` for the roles above lists only `alice`;
  6. a user in `allowed` is still hidden and a `User` managed by a role is still tracked.
  Update `tests/roles/test_unaccounted_users.py` where it asserts that `root (uid 0` and `bastet (uid 1000` show up with an empty `tracked`: those tests construct `UnaccountedUsers(...)` directly, so they stay valid; only the `batches_for`-level tests, if any assert them, change. Say which test changed in the report.
- [ ] **Step 2–4:** red, implement, green (`uv run pytest tests/roles tests/engine -q && ruff check src tests`).
- [ ] **Step 5: Commit** `users: the unaccounted report expects root, bastet, the OS's accounts and the accounts of applied roles`.

---

### Task 5: `bastet` is a system account on new hosts

**Files:**
- Modify: `src/bastet/core/bootstrap.py`, `tests/core/test_bootstrap.py`
- Check: `tests/cli/test_init.py:43` (it matches on `["sudo", "-n", "useradd"]`; keep it passing)

**Interfaces:** `_SCRIPT` creates the account with `useradd --system --create-home --shell /bin/sh bastet`. Everything else in the script is unchanged. A host that already has `bastet` keeps its uid (the `if ! id bastet` guard is untouched).

- [ ] **Step 1: Failing test** in `tests/core/test_bootstrap.py`: `"useradd --system --create-home --shell /bin/sh bastet" in setup_script(KEY)`, and the guard `"if ! id bastet"` is still the first command, so an existing account is never recreated.
- [ ] **Step 2–4:** red, implement, green (`uv run pytest tests/core tests/cli -q`).
- [ ] **Step 5: Commit** `bootstrap: bastet is created as a system account on new hosts`.

Note for the report: `--system` accounts get a uid below `UID_MIN` and no mail spool; `--create-home` is explicit because system accounts do not get a home by default. `tests/contract/Containerfile` creates its own `bastet` with `useradd -m`; leave it.

---

### Task 6: Docs, roadmap, whole-plan check

**Files:**
- Modify: `docs/ROADMAP.md`, `src/bastet/data/docs/writing_roles.md`, `docs/roles.md` (generated)

- [ ] **Step 1:** In `writing_roles.md` add `accounts:` to the role-file keys with one sentence ("accounts a role brings; the unaccounted-users report treats them as expected on hosts the role is applied to") and one sentence about OS defaults ("shipped per OS, for example Arch comes with the `systemd` role").
- [ ] **Step 2:** In `ROADMAP.md`: add a "Planned additions" row "Account defaults" with: Debian OS defaults and accounts; `systemd-timesync` moves from the `systemd` role to the `time` role when that role exists; provenance ("which package owns this account") as an optional explain feature; an existing host's `bastet` uid is not changed. Update the `users` row of the blocks table to mention that role and OS defaults feed the report.
- [ ] **Step 3:** Regenerate `docs/roles.md`. Run `uv run pytest -q` (the whole suite, about 4 minutes), `ruff check src tests`, and `scripts/privacy-check`.
- [ ] **Step 4: Commit** `docs: account defaults`.

---

## Self-review

- **Spec coverage:** every owner decision maps to a task: `alpm` with pacman and `systemd-*` with `systemd` (Task 1), the other Arch accounts on the Arch OS file and the Arch group coming with `systemd` (Tasks 2 and 3), `root`/`bastet` always accounted (Task 4), `bastet` as a system account on new hosts (Task 5), Debian and the `time` move recorded as later work (Task 6).
- **Placeholders:** none; each task names its code or the exact test assertions. Task 3's inventory setup points at the existing resolved-table test as the pattern.
- **Type consistency:** `check_accounts` returns `tuple[str, ...]` everywhere; `RoleDef.accounts` and `OsDefaults.accounts` are tuples; `defaults_for(os_id)` takes the string from `core.osinfo.os_id`; `BASE_ACCOUNTS` is a tuple of names.
- **Review Focus mapping:** applied-only role accounts (Task 4 tests 2 and 3), overridability and the origin label (Task 3 tests 1 and 2), unknown OS (Tasks 2 and 3), Arch-like OSes (Tasks 2 and 3), the `bastet` guard (Task 5), bad `accounts:` (Tasks 1 and 2).
