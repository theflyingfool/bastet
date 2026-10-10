# Roles architecture, first slice — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this repo, the `bastet-run-plan` skill supplies the Bastet-specific parts.

**Goal:** a host runs by phase across all roles (not role by role), and two roles, `pacman` and a new `apt`, are straight Markdown with no Python, proving both ways the `files` block can turn options into config. Then we stop for hard testing.

**Architecture:** every resource belongs to a block slot (repositories, packages, users, files, systemd, commands, reports). `run_host` orders all items from all roles by slot, runs the triggers once at the end (with a health check after restarts), and an entry can move itself with `before`/`after` or by `provides`-ing something a block `wants`. A Markdown role (`<name> role.md`, draft contract `api: 0`) is read by a loader into the existing `RoleDef` and built by one generic builder; the old `role.yml` roles keep their Python builders until they are converted.

**Tech Stack:** Python ≥3.12, PyYAML, pytest. Podman for the opt-in contract tests.

**Spec:** `docs/specs/2026-10-10-bastet-roles-architecture-design.md` (approved 2026-10-10), sections 3, 4 and 5. Out of scope for this plan: format checkers beyond what `File.validate` already does, templates, other roles, capabilities beyond `wants`, the library and `role update`.

**Roadmap:** `docs/ROADMAP.md`, "Roles architecture", step 1.

## Decisions made while planning (details the spec left open)

1. **The AUR is out of scope for now.** Nothing in this plan touches the AUR code (the `aur` package option and its bootstrap in the legacy `packages` role). See "Known limitation" below.
2. **Engine field names differ from contract keys.** In a role's contract an entry says `before:` or `after:`. On the resource they are `run_before` and `run_after`, because `Line` already has an `after` field (a regex).
3. **Failure rules in the new loop.** The first failed step skips every later item on that host (`earlier failure on this host: <what>`). Triggers still run for what changed before the failure. A failed trigger stops the remaining triggers. Verify still runs. This replaces today's per-batch rules; the tests that pin the old rules are updated (listed in Task 2).
4. **Health check scope.** Only restarts get a check (the unit must be `active` within a few seconds). Reloads and other triggers do not. `restart(unit, check=False)` is the opt-out for one-shot units.
5. **apt is a curated option list for now.** apt has hundreds of settings; this slice ships about a dozen common ones, marked as incomplete in the role's body. Generating the full list from `apt-config dump` is a later task (spec §3.1).
6. **The apt role writes a whole drop-in file** (`/etc/apt/apt.conf.d/90-bastet`), validated with `apt-config` before it replaces the old one. Pacman edits lines in place. Together they prove both modes.

## Known limitation: the AUR

The AUR option of the legacy `packages` role (a build user, sudoers file, `base-devel`, `git`, a `yay` install, then the AUR packages) depends on running in exactly that order. The new block order will not respect it, so an AUR install can fail at apply time on Arch hosts. That is accepted for now: the AUR is slated for a local-repository design of its own (roadmap, roles table item 8). The plan neither fixes nor guards it; the hard-testing checklist does not cover it.

## Global Constraints

- **Unit tests** never touch the real inventory, `~/.config/bastet`, `~/.local/share/bastet`, `~/.ssh`, the real `~/.cache` or `$XDG_RUNTIME_DIR`; no network; `tmp_path` only; placeholder data only (see "Example data" in `docs/ROADMAP.md`).
- **Test file basenames must be unique across `tests/`** (no `__init__.py` files). Use the names given in each task.
- **Contract (container) tests** run only when asked (`BASTET_CONTRACT=1`, podman). Agents write them but do not run them.
- **Existing behaviour is preserved** except where a task says a test changes. After Task 2 the whole suite must be green again.
- **Import direction:** `bastet.engine` never imports `bastet.roles`; `bastet.core` never imports `bastet.events`; neither `engine` nor `events` imports `typer`. Messages from the CLI go through `bastet.ui.out`.
- **Draft contract:** a Markdown role must say `api: 0`; any other value is refused. Reserved keys (`uses`, `needs`, `contributes`, `collects`, and so on) are accepted and ignored.
- **Commit trailer:**
  ```
  Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01DBkyXRsdxwovkRErg9n9wt
  ```
  Stage by name, never `git commit -a`. The privacy pre-commit hook runs on every commit.
- **Each task:** failing tests first and seen failing, then implement, then the task's own test files green. The user runs the wider suite at the checkpoints.

## Review Focus

1. **Equivalence.** The Markdown pacman produces resources equal to the old builder's for every option and for each error case (golden tests written before anything changes).
2. **No ordering regressions in the legacy roles** (the AUR excepted, see above): ssh (include command, drop-in, reload at the end), proxmox (repositories, tools, patch), harden (package, config, unit), and systemd (package, config, unit) still work in the new order.
3. **Triggers.** Once per host, in `order`, `daemon-reload` before restarts, a changed item's triggers still run when a later item fails, and the health check does not give false failures (one-shot units, units that take a moment to start).
4. **The entry knobs.** An unknown block name in `before`/`after` is an error at plan time (also in check). `provides` only ever moves an entry earlier. Two roles giving the same entry different placements is a conflict.
5. **The draft contract.** Unknown top-level keys are an error; a folder with both `role.yml` and a Markdown role is an error; `api` other than 0 is refused; options keep their order (golden tests depend on it).

## File structure

| File | Responsibility |
|---|---|
| `src/bastet/engine/slots.py` (new) | `SLOTS`, `WANTS`, `rank`, `apply_order` |
| `src/bastet/engine/model.py` | `Resource` gains `slot` (ClassVar) and `run_before`/`run_after`/`provides`; `Trigger` gains the health-check fields |
| `src/bastet/engine/*.py` | each resource class sets its `slot` |
| `src/bastet/engine/run.py` | the apply loop over `apply_order`, triggers once at the end, health check |
| `src/bastet/engine/systemd.py` | `restart()` carries a check |
| `src/bastet/roles/contract.py` | option keys (`key`, `section`, `as`, `min`, `max`, `single_line`), `RoleDef` fields, `parse_role`, `load_roles` for both formats |
| `src/bastet/roles/declarative.py` (new) | the generic builder: `edit: ini`, `render: apt` |
| `src/bastet/roles/builtin.py` | `batches_for` uses the generic builder for Markdown roles |
| `src/bastet/data/roles/pacman/pacman role.md` | pacman as Markdown (replaces `role.yml`) |
| `src/bastet/data/roles/apt/apt role.md` | the new apt role |

---

### Task 1: Pin pacman's behaviour before changing anything

**Files:**
- Create: `tests/roles/test_pacman_role.py`
- Create (not committed): a "before" snapshot, described in Step 4

**Behaviour:** golden tests that describe what the *current* Python pacman builder produces, written against `batches_for` so they keep working unchanged after the conversion in Task 6.

- [ ] **Step 1: Write the tests.** Create `tests/roles/test_pacman_role.py`:

```python
from pathlib import Path

import pytest

from bastet.core.errors import BastetError
from bastet.engine.files import Line
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import check_values, load_roles, with_defaults
from bastet.roles.resolve import Applied

ROLES = load_roles()
CONF = "/etc/pacman.conf"
OPTIONS = r"^\[options\]\s*$"


def ap(values):
    r = ROLES["pacman"]
    return Applied(r, with_defaults(r, check_values(r, values, "pacman")))


def arch(os="Arch Linux"):
    return HostInfo(name="laptop1", type="laptop", data={"os": os}, root=Path("/nonexistent"), lab={})


def built(values, host=None):
    [batch] = batches_for([ap(values)], host or arch())
    return batch.resources


def line(key, text):
    return Line(path=CONF, line=text, match=rf"^#?\s*{key}\s*(=.*)?$", after=OPTIONS, unique=True)


COLOR, CANDY = line("Color", "Color"), line("ILoveCandy", "ILoveCandy")


def test_defaults_write_color_and_candy_only():
    assert built({}) == [COLOR, CANDY]


def test_a_value_option_is_written_in_option_order():
    assert built({"parallel_downloads": 8}) == [line("ParallelDownloads", "ParallelDownloads = 8"), COLOR, CANDY]


def test_a_flag_set_false_is_commented_out():
    assert built({"color": False}) == [line("Color", "#Color"), CANDY]


def test_list_options_join_with_spaces_and_an_empty_list_comments_the_directive_out():
    assert built({"ignore_pkg": ["linux", "linux-headers"], "hold_pkg": []}) == [
        line("HoldPkg", "#HoldPkg ="), line("IgnorePkg", "IgnorePkg = linux linux-headers"), COLOR, CANDY]


def test_every_option_maps_to_its_pacman_directive():
    values = {
        "root_dir": "/", "db_path": "/var/lib/pacman/", "cache_dir": ["/var/cache/pacman/pkg/"], "hook_dir": ["/etc/pacman.d/hooks/"],
        "gpg_dir": "/etc/pacman.d/gnupg/", "log_file": "/var/log/pacman.log", "hold_pkg": ["pacman", "glibc"],
        "ignore_pkg": ["a"], "ignore_group": ["g"], "no_upgrade": ["etc/x"], "no_extract": ["usr/share/doc/*"],
        "architecture": "auto", "xfer_command": "/usr/bin/curl -fC - %u -o %o", "parallel_downloads": 5,
        "disable_download_timeout": True, "download_user": "alpm", "disable_sandbox": False,
        "clean_method": ["KeepInstalled"], "sig_level": "Required DatabaseOptional",
        "local_file_sig_level": "Optional", "remote_file_sig_level": "Required", "color": True, "candy": False,
        "no_progress_bar": True, "verbose_pkg_lists": True, "check_space": True, "use_syslog": False,
    }
    keys = [(r.line.split(" = ")[0].lstrip("#"), r.line) for r in built(values)]
    assert [k for k, _ in keys] == [
        "RootDir", "DBPath", "CacheDir", "HookDir", "GPGDir", "LogFile", "HoldPkg", "IgnorePkg", "IgnoreGroup",
        "NoUpgrade", "NoExtract", "Architecture", "XferCommand", "ParallelDownloads", "DisableDownloadTimeout",
        "DownloadUser", "DisableSandbox", "CleanMethod", "SigLevel", "LocalFileSigLevel", "RemoteFileSigLevel",
        "Color", "ILoveCandy", "NoProgressBar", "VerbosePkgLists", "CheckSpace", "UseSyslog"]
    lines = dict(keys)
    assert lines["DisableDownloadTimeout"] == "DisableDownloadTimeout" and lines["DisableSandbox"] == "#DisableSandbox"
    assert lines["ILoveCandy"] == "#ILoveCandy" and lines["CleanMethod"] == "CleanMethod = KeepInstalled"
    assert lines["SigLevel"] == "SigLevel = Required DatabaseOptional" and lines["UseSyslog"] == "#UseSyslog"


def test_a_host_that_is_not_arch_based_is_refused_with_the_group_to_aim_at():
    with pytest.raises(BastetError, match=r"pacman role: laptop1 isn't Arch-based \(Debian GNU/Linux 13 \(trixie\)\); aim it at \[\[arch\]\]"):
        built({}, arch("Debian GNU/Linux 13 (trixie)"))


def test_an_unknown_os_is_refused_too():
    with pytest.raises(BastetError, match=r"isn't Arch-based \(OS unknown\)"):
        built({}, HostInfo(name="laptop1", type="laptop", data={}, root=Path("/nonexistent"), lab={}))


@pytest.mark.parametrize("bad", [0, -2])
def test_parallel_downloads_must_be_one_or_more(bad):
    with pytest.raises(BastetError, match=r"pacman\.parallel_downloads:? must be 1 or more"):
        built({"parallel_downloads": bad})


@pytest.mark.parametrize("bad", ["a\nb", "   ", ""])
def test_a_value_option_must_be_one_non_empty_line(bad):
    with pytest.raises(BastetError, match=r"pacman\.xfer_command: needs a single non-empty line"):
        built({"xfer_command": bad})
```

- [ ] **Step 2: Run to verify they pass.** `uv run pytest tests/roles/test_pacman_role.py -q`. They describe today's behaviour, so they must pass against the current Python builder. If one fails, the test (not the code) is wrong: fix the test to match what the builder really does and say so in your report. (For example, whether the multi-line check raises at `check_values` time or at build time is the same here because both calls are inside the `pytest.raises` block.)
- [ ] **Step 3: Commit** `tests/roles/test_pacman_role.py` as `tests: pin pacman's behaviour before the role is converted`.
- [ ] **Step 4: Take a "before" snapshot of the user-visible output** (not committed; this is for Task 6's comparison). Follow the `run-bastet` skill to make a sandbox, then: add a local host `box` (`type: laptop`, `connection: local`) with a role file `_roles/hosts/box/pacman.md` containing `role: pacman`, `applies_to: "[[box]]"` and `parallel_downloads: 8`; drive `bastet run -c box` with the connection patched to run commands locally (the scratch `drive.py` pattern from `tests/cli/test_run_recording.py`: `AsRootLocally`); save the output without timing to `.superpowers/sdd/2026-10-10-bastet-roles-arch-1-slice/before-check.txt`. Note in your report whether this machine's `/etc/pacman.conf` was Arch.

---

### Task 2: Slots and one global order in `run_host`

**Files:**
- Create: `src/bastet/engine/slots.py`, `tests/engine/test_phases.py`
- Modify: `src/bastet/engine/model.py`, every resource class (`slot`), `src/bastet/engine/run.py` (`_merge`, `run_host`), and the tests named below

**Interfaces (produces):**
```python
SLOTS = ("repositories", "packages", "users", "files", "systemd", "commands", "reports")
WANTS = {"repositories": ("package-manager",), "packages": ("package-manager",)}
def rank(res: Resource) -> float                        # position of an entry in the run
def apply_order(planned: list[tuple[Batch, list[Item]]]) -> list[Item]   # all items, in run order
```
`Resource` gains: `slot: ClassVar[str] = "commands"`, and keyword fields `run_before: str | None = None`, `run_after: str | None = None`, `provides: tuple[str, ...] = ()`.

**Behaviour:**
- **Each resource class sets its slot:** `Repository`, `StraySources` → `repositories`; `Package`, `Updates` → `packages`; `Unaccounted`, `Reboot` and every report class (`_Report` subclasses) → `reports`; `User`, `Group`, `AuthorizedKey` → `users`; `File`, `Directory`, `Symlink`, `_Edit` (so `Line` and `Block`) → `files`; `Unit`, `Hostname`, `Locale`, `TimeSettings` → `systemd`; `Command` → `commands`.
- **`rank(res)`:** the base is the position of `res.slot` in `SLOTS`. `run_before: X` gives the position of X minus 0.5; `run_after: X` gives it plus 0.5 (these override the base). An entry that `provides` something a slot `wants` is moved to just before the earliest wanting slot (it only ever moves earlier). A name in `run_before`/`run_after` that is not in `SLOTS` raises `BastetError("<what>: unknown block 'x' (known: …)")`.
- **`apply_order`:** sort by `(rank, batch index, position in batch)`. Stable, so within a slot roles keep today's `ORDER` and a role's own order.
- **`run_host`:** compute `apply_order` right after `collect_items` (so an unknown block name is an error in check too). In apply mode, walk that one sequence instead of batch by batch. Keep grouping of adjacent items with the same `group_key`, the `touches` re-read, `should_stop`, the events, and the verify phase exactly as they are. Failure rule: the first failed step sets `broken`; every later would-change item becomes `skipped` with `earlier failure on this host: <label>`. Collect each changed item's triggers into one list (no duplicates); after the loop run them once, ordered by `Trigger.order` (stable), recording a `TriggerRun` and emitting `trigger_fired` for each. A failed trigger stops the remaining triggers.
- **`_merge`:** treat `provides` like `on_change` (union, never a clash); `run_before` and `run_after` clash if two sources differ.

**Tests that change** (they pin the old per-batch rules; update only what the new rules require, and say so in the commit):
- `tests/engine/test_run.py::test_failure_skips_rest_of_batch_and_later_batches`: the same-batch skip message becomes `earlier failure on this host: <bad>`.
- `test_failed_trigger_stops_later_batches`: rewrite. Triggers now run after all items, so the later item in batch two *does* run; assert that it ran, that the failed trigger is recorded `ok=False`, and `not run.ok`.
- `test_triggers_run_once_after_batch_in_order`: keep (single batch); add the cross-batch case in the new file.
- Nothing else may change. If another existing test fails, report it instead of editing it.

- [ ] **Step 1: Write the failing tests** in `tests/engine/test_phases.py` (use `engine_fakes.Flag`, `LocalRunner`, and small subclasses that set `slot`):

```python
from typing import ClassVar

import pytest

from bastet.core.errors import BastetError
from bastet.core.remote import LocalRunner
from bastet.engine.model import Trigger
from bastet.engine.run import Batch, run_host
from bastet.engine.slots import SLOTS, apply_order, rank
from engine_fakes import Broken, Flag


class Pkg(Flag):
    slot: ClassVar[str] = "packages"


class Svc(Flag):
    slot: ClassVar[str] = "systemd"


def order(run):
    return [i.resource.label for i in run.items]


def sequence(*batches):
    from bastet.engine.run import collect_items

    return [i.resource.label for i in apply_order(collect_items(list(batches)))]


def test_items_from_different_batches_run_in_slot_order(tmp_path):
    a, b, c = (str(tmp_path / n) for n in "abc")
    first = Batch("first", [Svc(path=a, value="1"), Flag(path=b, value="2")])      # systemd, then files
    second = Batch("second", [Pkg(path=c, value="3")])                              # packages
    assert sequence(first, second) == [c, b, a]


def test_within_a_slot_batch_order_then_item_order_is_kept(tmp_path):
    a, b, c = (str(tmp_path / n) for n in "abc")
    assert sequence(Batch("one", [Flag(path=a, value="1"), Flag(path=b, value="2")]), Batch("two", [Flag(path=c, value="3")])) == [a, b, c]


def test_entry_knobs_move_an_entry(tmp_path):
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    early = Flag(path=a, value="1", run_before="packages")           # a files-slot entry that must precede packages
    assert sequence(Batch("x", [Pkg(path=b, value="2"), early])) == [a, b]
    late = Pkg(path=a, value="1", run_after="systemd")
    assert sequence(Batch("x", [late, Svc(path=b, value="2")])) == [b, a]


def test_provides_moves_an_entry_before_the_blocks_that_want_it(tmp_path):
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    cfg = Flag(path=a, value="1", provides=("package-manager",))     # a files entry; packages wants package-manager
    assert sequence(Batch("x", [Pkg(path=b, value="2"), cfg])) == [a, b]
    assert rank(cfg) < SLOTS.index("repositories")
    assert rank(Flag(path=a, value="1", provides=("something-else",))) == SLOTS.index("files")


def test_an_unknown_block_name_is_an_error_at_plan_time_even_in_check(tmp_path):
    bad = Flag(path=str(tmp_path / "a"), value="1", run_before="nonsense")
    with pytest.raises(BastetError, match="unknown block 'nonsense'"):
        run_host(LocalRunner(), "h", [Batch("x", [bad])], apply=False)


def test_every_resource_class_has_a_known_slot():
    import bastet.engine.command, bastet.engine.files, bastet.engine.packages, bastet.engine.security  # noqa: F401
    import bastet.engine.systemd, bastet.engine.users  # noqa: F401
    from bastet.engine.model import Resource

    def walk(cls):
        for sub in cls.__subclasses__():
            yield sub
            yield from walk(sub)

    for cls in walk(Resource):
        if cls.__module__.startswith("bastet.") :
            assert cls.slot in SLOTS, f"{cls.__name__}.slot = {cls.slot!r}"


def test_triggers_from_several_batches_run_once_at_the_end_in_order(tmp_path):
    log = tmp_path / "log"
    late = Trigger("late", f"echo late >> {log}", root=False)
    early = Trigger("early", f"echo early >> {log}", order=10, root=False)
    run = run_host(LocalRunner(), "h", [
        Batch("one", [Flag(path=str(tmp_path / "a"), value="1", on_change=(late, early))]),
        Batch("two", [Flag(path=str(tmp_path / "b"), value="2", on_change=(late,))]),
    ], apply=True)
    assert log.read_text() == "early\nlate\n"
    assert [(t.trigger.label, t.ok) for t in run.triggers] == [("early", True), ("late", True)]


def test_a_failure_skips_everything_later_on_the_host_but_earlier_triggers_still_fire(tmp_path):
    log = tmp_path / "log"
    t = Trigger("t", f"echo ran >> {log}", root=False)
    ok = Flag(path=str(tmp_path / "ok"), value="1", on_change=(t,))
    bad, later = str(tmp_path / "bad"), str(tmp_path / "later")
    run = run_host(LocalRunner(), "h", [Batch("x", [ok, Broken(path=bad, value="x")]), Batch("y", [Svc(path=later, value="z")])], apply=True)
    s = {i.resource.label: (i.status, i.error) for i in run.items}
    assert s[bad] == ("failed", "boom") and s[later] == ("skipped", f"earlier failure on this host: {bad}")
    assert not (tmp_path / "later").exists() and log.read_text() == "ran\n" and not run.ok


def test_a_failed_trigger_stops_the_remaining_triggers(tmp_path):
    log = tmp_path / "log"
    boom = Trigger("boom", "exit 1", order=10, root=False)
    after = Trigger("after", f"echo x >> {log}", order=20, root=False)
    run = run_host(LocalRunner(), "h", [Batch("x", [Flag(path=str(tmp_path / "a"), value="1", on_change=(after, boom))])], apply=True)
    assert [(t.trigger.label, t.ok) for t in run.triggers] == [("boom", False)] and not log.exists() and not run.ok
```

- [ ] **Step 2: Run to verify they fail:** `uv run pytest tests/engine/test_phases.py -q` (import error for `bastet.engine.slots`).
- [ ] **Step 3: Implement.**

`src/bastet/engine/slots.py`:

```python
"""Where each entry runs: the blocks in order, and the exceptions an entry can ask for."""

from __future__ import annotations

from bastet.core.errors import BastetError

SLOTS = ("repositories", "packages", "users", "files", "systemd", "commands", "reports")
WANTS = {"repositories": ("package-manager",), "packages": ("package-manager",)}   # a block's "run these first, if any"


def _position(name: str, what: str) -> int:
    try:
        return SLOTS.index(name)
    except ValueError:
        raise BastetError(f"{what}: unknown block {name!r} (known: {', '.join(SLOTS)})") from None


def rank(res) -> float:
    what = res.label
    base = float(SLOTS.index(res.slot))
    if res.run_before:
        return _position(res.run_before, f"{what}: before") - 0.5
    if res.run_after:
        return _position(res.run_after, f"{what}: after") + 0.5
    for capability in res.provides:
        for slot, wanted in WANTS.items():
            if capability in wanted:
                base = min(base, SLOTS.index(slot) - 0.5)
    return base


def apply_order(planned) -> list:
    keyed = [(rank(item.resource), b, i, item) for b, (_, items) in enumerate(planned) for i, item in enumerate(items)]
    keyed.sort(key=lambda k: k[:3])
    return [k[3] for k in keyed]
```

`engine/model.py` `Resource`: add the `slot` ClassVar and the four fields after `secret`. `engine/run.py`:
- `_merge`: `if f.name in ("on_change", "provides"): continue` and, after the loop, `updates["provides"] = tuple(dict.fromkeys((*a.provides, *b.provides)))` when they differ.
- In `run_host`, in the `collect` phase: `planned = collect_items(batches)` then `sequence = apply_order(planned)` (import from `bastet.engine.slots`); `items` stays the batch-order list used for reading and reporting.
- Replace the apply loop with:

```python
    changed: list[Item] = []
    touched: set[str] = set()
    pending: list[Trigger] = []
    broken: str | None = None
    with events.phase(host, "apply"):
        i = 0
        while i < len(sequence):
            item = sequence[i]
            i += 1
            if item.status == "failed" and not item.resource.report_only() and broken is None:
                broken = item.resource.label
            if item.status != "would-change":
                continue
            if run.stopped or (should_stop is not None and should_stop()):
                run.stopped = True
                item.status, item.error = "skipped", "stopped (Ctrl-C)"
                _item_event(host, item, "apply")
                continue
            if broken is not None:
                item.status, item.error = "skipped", f"earlier failure on this host: {broken}"
                _item_event(host, item, "apply")
                continue
            path = item.resource.touches()
            if path is not None and path in touched:
                _assess(item, _read(runner, [item], host=host, phase="apply")[0])
                if item.status == "failed":
                    broken = item.resource.label
                if item.status != "would-change":
                    _item_event(host, item, "apply")
                    continue
            group = [item]
            key = item.resource.group_key()
            if key is not None:
                while (i < len(sequence) and sequence[i].status == "would-change"
                       and sequence[i].resource.group_key() == key):
                    group.append(sequence[i])
                    i += 1
                commands = type(item.resource).fix_group([(g.resource, g.changes, g.current) for g in group])
            else:
                commands = item.resource.fix(item.changes, item.current)
            ok, error = _exec(runner, commands, any(g.resource.root for g in group), fix_timeout,
                              host=host, phase="apply", hidden=any(g.resource.secret for g in group))
            if not ok:
                for g in group:
                    g.status, g.error = "failed", error
                    _item_event(host, g, "apply")
                broken = item.resource.label
                continue
            for g in group:
                g.status = "changed"
                changed.append(g)
                _item_event(host, g, "apply")
                if g.resource.touches() is not None:
                    touched.add(g.resource.touches())
                for t in g.triggers:
                    if t not in pending:
                        pending.append(t)
        for t in sorted(pending, key=lambda t: t.order):
            ok, error = _exec(runner, [t.command], t.root, fix_timeout, host=host, phase="on_change")
            run.triggers.append(TriggerRun(t, ok, error))
            events.emit("trigger_fired", host, trigger=t.label, ok=ok, error=error)
            if not ok:
                break
```
(Keep the verify block that follows, unchanged. Remove the now-unused `host_broken`.)

Then add `slot = "..."` ClassVars to the resource classes as listed.

- [ ] **Step 4: Run to verify they pass.** `uv run pytest tests/engine -q` (the whole engine folder), then `uv run pytest tests/events tests/roles tests/cli/test_check_apply.py tests/cli/test_apply_parallel.py -q`. Expected: all green apart from the three tests named above, which you updated.
- [ ] **Step 5: Commit** (`engine: one run order across all roles by block; triggers once per host at the end`).

---

### Task 3: A health check after restarts

**Files:**
- Modify: `src/bastet/engine/model.py` (`Trigger`), `src/bastet/engine/systemd.py` (`restart`), `src/bastet/engine/run.py` (trigger loop)
- Test: `tests/engine/test_trigger_checks.py`

**Interfaces:** `Trigger` gains `check: str | None = None`, `check_tries: int = 5`, `check_wait: float = 1.0`. `restart(unit, check=True)` sets `check=f"systemctl is-active --quiet {unit}"`. `reload()` and every other trigger keep `check=None`.

**Behaviour:** after a trigger's command succeeds and it has a `check`, run the check up to `check_tries` times, waiting `check_wait` seconds between tries; pass on the first success. If every try fails the trigger is recorded as failed with the error `<label>: still not running after <n> checks`, and the remaining triggers are skipped (as for any failed trigger). Each check is a recorded command (phase `on_change`).

- [ ] **Step 1: Write the failing tests** in `tests/engine/test_trigger_checks.py` using `LocalRunner` and shell commands: a trigger whose check succeeds at once; one whose check fails twice then passes (use a counter file: `n=$(cat f 2>/dev/null || echo 0); echo $((n+1)) > f; [ $n -ge 2 ]`) with `check_wait=0.01`; one that never passes (`check="false"`, `check_tries=2`, `check_wait=0.01`) giving `ok=False` with the message above and no later trigger; and a unit test that `restart("x.service")` has a check and `reload("x.service")` does not.
- [ ] **Step 2: Run to verify they fail**, then **Step 3: implement** in the trigger loop of `run_host`:

```python
        for t in sorted(pending, key=lambda t: t.order):
            ok, error = _exec(runner, [t.command], t.root, fix_timeout, host=host, phase="on_change")
            if ok and t.check:
                for attempt in range(t.check_tries):
                    ok, _ = _exec(runner, [t.check], t.root, fix_timeout, host=host, phase="on_change")
                    if ok:
                        break
                    if attempt + 1 < t.check_tries:
                        time.sleep(t.check_wait)
                if not ok:
                    error = f"{t.label}: still not running after {t.check_tries} checks"
            run.triggers.append(TriggerRun(t, ok, error))
            events.emit("trigger_fired", host, trigger=t.label, ok=ok, error=error)
            if not ok:
                break
```
- [ ] **Step 4: Run** `uv run pytest tests/engine tests/roles tests/events -q`. **Step 5: Commit** (`engine: a restart trigger checks that the unit is running`).

---

### Task 4: The Markdown role loader and the draft contract

**Files:**
- Modify: `src/bastet/roles/contract.py`
- Test: `tests/roles/test_markdown_roles.py`

**Interfaces (produces):**
```python
API_VERSIONS = (0,)
# Option gains: key: str | None, section: str | None, as_: str | None, min: int | float | None, max: ..., single_line: bool
# RoleDef gains: api: int | None = None, version: str = "0.0.0", os: tuple[str, ...] = (), provides: tuple[str, ...] = (),
#                entries: list[dict] = [], markdown: bool = False, raw: dict = {}
def parse_role(path: Path) -> RoleDef      # one "<name> role.md"
def load_roles(directory=None)             # now: <name>/<name> role.md if present, else <name>/role.yml; both is an error
```

**Behaviour:**
- **Option keys** `key`, `section`, `as` (one of `flag`, `value`, `list`), `min`, `max` (only on `int`/`number`), `single_line` (only on `string`) join `OPTION_KEYS`. `check_value` enforces them with these messages: `{where}: must be {min} or more`, `{where}: must be {max} or less`, `{where}: needs a single non-empty line`.
- **`parse_role`** reads the note with `parse_document`. Required frontmatter: `bastet: role-definition`, `name` equal to the folder name, `version` (`X.Y.Z`), `api` in `API_VERSIONS`, `description`. Optional: `os`, `provides` (flat lists of text), `options`, `examples`, `files`. Reserved keys (`uses`, `needs`, `contributes`, `collects`, `requires`, `tags`, `cssclasses`, `types`, `not_types`, `os_min`, `data`, `vars`, `presets`, `packages`, `templates`, `units`, `hooks`, `source`, `source_hash`) are accepted, stored in `raw`, and do nothing. Any other top-level key is an error naming it. A `files` entry is a map with `path` and exactly one of `edit` (`ini`) or `render` (`apt`); optional `mode`, `owner`, `group`, `validate`, `before`, `after`; anything else is an error naming the key. Errors name the file and key like the existing parser.
- **`load_roles`** keeps returning the same shape; a folder with both formats is an error.

- [ ] **Step 1: Write the failing tests** in `tests/roles/test_markdown_roles.py`: write small role folders under `tmp_path` and assert: a minimal valid role parses (`markdown=True`, `api == 0`); each required-field error; `api: 1` refused; unknown top-level key; reserved keys accepted and ignored; `files` entry errors (neither `edit` nor `render`, both, unknown key); option keys `key`/`section`/`as`/`min`/`max`/`single_line` accepted on the right types and rejected on the wrong ones; `check_value` min/max/single_line messages; both formats in one folder is an error; option order is preserved; and `load_roles()` (the bundled set) still returns the same nine names.
- [ ] **Step 2: Run to verify they fail**, **Step 3: implement**, **Step 4:** `uv run pytest tests/roles tests/core/test_docs.py tests/cli/test_add_role.py -q`. **Step 5: Commit** (`roles: a Markdown role format (draft contract, api 0) next to role.yml`).

---

### Task 5: The generic builder

**Files:**
- Create: `src/bastet/roles/declarative.py`
- Modify: `src/bastet/roles/builtin.py` (`batches_for`)
- Test: `tests/roles/test_declarative_roles.py`

**Interfaces:** `build(role: RoleDef, values: dict, host) -> list[Batch]`.

**Behaviour:**
- **OS check:** if `role.os` is set and the host matches none of them, raise `BastetError(f"{role.name} role: {host.name} isn't {Label}-based ({host.data.get('os') or 'OS unknown'}); aim it at [[{family}]]")` for the first family. `arch` matches `host.os_id in ARCH_LIKE` (Label `Arch`); `debian` matches `host.debian_like` (Label `Debian`); any other name matches `host.os_id == name` (Label capitalised).
- **`edit: ini`** (in place): for each option with a `key` whose value is not `None`, in contract order, one `Line(path, line, match=rf"^#?\s*{re.escape(key)}\s*(=.*)?$", after=rf"^\[{re.escape(section)}\]\s*$" or None, unique=True)`. The kind is the option's `as`, else `flag` for `bool`, `list` for `list`, `value` otherwise: `flag` → `Key` or `#Key`; `list` → `Key = a b c` or `#Key =` when empty; `value` → `Key = v`.
- **`render: apt`** (whole file): one `File(path, content, mode, owner, group, validate)` whose content is `# Managed by Bastet (apt role). Edit the role file, not this file.` followed by one line per option with a `key` and a value, in contract order: a bool → `Key "true";`/`Key "false";`; a list → `Key { "a"; "b"; };` (`Key { };` when empty); anything else → `Key "value";`. Backslashes and double quotes in values are escaped.
- **Placement:** every resource gets `run_before`/`run_after` from the entry's `before`/`after`, and `provides` from the role.
- **`batches_for`:** a role with `markdown=True` is built by `declarative.build`; other roles use their old builder (unchanged, including `ORDER`).

- [ ] **Step 1: Write the failing tests** in `tests/roles/test_declarative_roles.py` with synthetic Markdown roles in `tmp_path`: the ini kinds (flag true and false, list, empty list, value, an option with no key skipped, `None` skipped), the section anchor and match regexes (compare against the exact strings in Task 1), an apt-style render of each value type including escaping and an empty list, `provides` and `before` reaching the resources, the OS error text for `arch` and `debian`, and that a Markdown role through `batches_for` returns one `Batch` named after the role.
- [ ] **Step 2: Run to verify they fail**, **Step 3: implement**, **Step 4:** `uv run pytest tests/roles tests/engine -q`. **Step 5: Commit** (`roles: one generic builder for Markdown roles (ini edits and whole-file rendering)`).

---

### Task 6: pacman becomes Markdown-only

**Files:**
- Create: `src/bastet/data/roles/pacman/pacman role.md`
- Delete: `src/bastet/data/roles/pacman/role.yml`
- Modify: `src/bastet/roles/system.py` (remove `pacman`, `PACMAN_SETTINGS`, `_directive`, and any constants that become unused), `src/bastet/roles/builtin.py` (`BUILDERS`, `ORDER`), `docs/roles.md` (regenerate with `scripts/gen_roles_doc.py`)
- Tests: the Task 1 file passes **unchanged**

**The role file** (`pacman role.md`): frontmatter with `bastet: role-definition`, `name: pacman`, `version: 1.0.0`, `api: 0`, the existing description, `os: [arch]`, `provides: [package-manager]`, the 27 options **in the same order as today's `role.yml`**, each with its existing `type`, `default` and `description` plus `key`, `section: options` and (for `bool` and `list` types) `as`; `parallel_downloads` gets `min: 1`; every `string` option that was a `value` kind gets `single_line: true`; the existing `examples`; and `files: [{path: /etc/pacman.conf, edit: ini}]`. The key for each option is the directive name in today's `PACMAN_SETTINGS` (for example `parallel_downloads` → `ParallelDownloads`, `candy` → `ILoveCandy`). The body is `# pacman role`, the description, and a `## Changes` list with `1.0.0: converted from role.yml`. Copy the descriptions from `role.yml` before deleting it.

- [ ] **Step 1:** write the role file; **Step 2:** run `uv run pytest tests/roles/test_pacman_role.py -q`: the Task 1 tests must pass unchanged against the Markdown role (while `system.pacman` still exists, route `BUILDERS` away from it first so the test really exercises the Markdown path). **Step 3:** delete the old builder, constants and `role.yml`; regenerate `docs/roles.md`. **Step 4:** `uv run pytest tests/roles tests/core tests/cli/test_add_role.py tests/test_cli.py -q` and `scripts/privacy-check`. **Step 5:** compare with the "before" snapshot from Task 1 Step 4: repeat the sandbox check and diff the two outputs; they must be identical apart from timing. **Step 6: Commit** (`pacman: straight Markdown, no Python`).

---

### Task 7: The apt role

**Files:**
- Create: `src/bastet/data/roles/apt/apt role.md`, `tests/roles/test_apt_role.py`
- Modify: `tests/roles/test_role_contract.py` (the expected role names gain `apt`), `tests/contract/test_contract.py` (one new contract test, not run by agents), `docs/roles.md` (regenerate)

**The role:** `name: apt`, `version: 1.0.0`, `api: 0`, `os: [debian]`, `provides: [package-manager]`, `files: [{path: /etc/apt/apt.conf.d/90-bastet, render: apt, mode: "0644", validate: "apt-config -c %s dump >/dev/null"}]`. Options (a curated, **incomplete** list; the body says so and that the full list will be generated later):

| Option | Key | Type |
|---|---|---|
| `install_recommends` | `APT::Install-Recommends` | bool |
| `install_suggests` | `APT::Install-Suggests` | bool |
| `default_release` | `APT::Default-Release` | string, single_line |
| `keep_downloaded_packages` | `APT::Keep-Downloaded-Packages` | bool |
| `autoremove_suggests_important` | `APT::AutoRemove::SuggestsImportant` | bool |
| `acquire_retries` | `Acquire::Retries` | int, min 0 |
| `acquire_http_timeout` | `Acquire::http::Timeout` | int, min 1 |
| `acquire_https_timeout` | `Acquire::https::Timeout` | int, min 1 |
| `acquire_http_proxy` | `Acquire::http::Proxy` | string, single_line |
| `acquire_https_proxy` | `Acquire::https::Proxy` | string, single_line |
| `acquire_languages` | `Acquire::Languages` | list of string |
| `dpkg_options` | `Dpkg::Options` | list of string |

No defaults (unset leaves apt alone). Include two `examples` (a proxy; no recommends).

- [ ] **Step 1: Write the failing tests** in `tests/roles/test_apt_role.py`: golden content for a few option sets (exact file text including the header and quoting), one `File` resource with the right path/mode/validate, `lines` for unset options absent, the Debian-only error (`aim it at [[debian]]`), min/single-line errors, and ordering: with `apt` and `packages` both applied on a Debian host, `apply_order` puts the apt `File` before every `Repository` and `Package`. Add `apt` to the expected set in `test_role_contract.py`.
- [ ] **Step 2: Run to verify they fail**, **Step 3: write the role**, **Step 4:** `uv run pytest tests/roles tests/core tests/engine -q`.
- [ ] **Step 5: Add a contract test** `test_debian_apt_role_contract` modelled on `test_arch_pacman_contract`: converge a Debian container with `{"install_recommends": False, "acquire_retries": 3}` and assert `apt-config dump` shows `APT::Install-Recommends "false"` and `Acquire::Retries "3"`, then that a second converge changes nothing. Do not run it.
- [ ] **Step 6: Commit** (`apt: a new Markdown-only role`).

---

### Task 8: Docs, roadmap, and the stop for hard testing

**Files:** `docs/specs/2026-10-10-bastet-roles-architecture-design.md` (add the field names `run_before`/`run_after`, and the failure rules), `docs/ROADMAP.md` (step 1 done, the roles table notes, the blocks table), `src/bastet/data/docs/writing_roles.md` (a short "Markdown roles (draft)" section: the format, `api: 0` is a draft, the two file modes, the entry knobs), `docs/roles.md`.

- [ ] **Step 1:** make the doc edits (plain text, example data only; `tests/core/test_docs.py` must stay green, every `[[link]]` must resolve). **Step 2:** `uv run pytest -q` (the full suite) and `scripts/privacy-check`. **Step 3: Commit** (`docs: roles architecture first slice`).

**STOP HERE. Hard testing, before any more roles are converted.** The controller reports and waits. The checklist the user (or the controller on request) works through:
1. The full suite, then the contract tests: `BASTET_CONTRACT=1 uv run pytest tests/contract -q` (needs podman; runs the Debian and Arch containers, including the new apt and the existing pacman, ssh, packages and harden contract tests).
2. A real `bastet run -c` against this Arch machine's inventory role files, comparing with the "before" snapshot: nothing may change apart from timing.
3. Every legacy role through the new order on a real host if one is available (the AUR excepted): an ssh change (include command, drop-in, reload at the end), a harden run, a systemd change that restarts a unit (health check), and a proxmox run.
4. Failure cases: a deliberately failing fix mid-run (later items skipped, earlier triggers still fire), a restart of a unit that fails to start (the health check reports it), and a one-shot unit.
5. Ctrl-C mid-apply, and `bastet run -c -vv` to read the new phase order in the live view.
6. Look for surprises in ordering: anything that used to work because a role ran as a whole before the next one.
