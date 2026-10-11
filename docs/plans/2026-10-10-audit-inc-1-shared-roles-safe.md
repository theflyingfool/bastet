# Audit increment 1: make the shipped roles safe — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. In this repo, the `bastet-run-plan` skill supplies the Bastet-specific parts.

**Goal:** the `edit: ini` mode edits only the section it names, using one managed block per section; the pacman role uses it, so a global setting can never touch a repository's own settings. Plus the contract and value checks the audit asked for, and three quick fixes.

**Architecture:** a new `Settings` resource (in `engine/files.py`) owns a section's managed block. On each run it removes its old block, comments out (`#bastet: `) every active original of a key the role manages, inside that section only, and inserts the block right after the section header. A knob set to off or empty comments out the originals and adds nothing to the block. The generic builder turns an `edit: ini` entry into one `Settings` per section. The existing `Line` and `Block` resources are untouched.

**Tech Stack:** Python ≥3.12, pytest.

**Spec / source:** `docs/plans/2026-10-10-bastet-audit-correction-plan.md` (increment 1; combined findings C1, C13, C14, C19; audit 2 findings F03, F15, F13, F14, UX-13).

## Decisions behind this plan (spiked in the Arch container)

- `yq` and `configupdater` do not edit a `pacman.conf` faithfully (`yq` rejects bare keys such as `ILoveCandy` and drops comments and repeated keys; `configupdater` keeps layout but lacks the operations needed). No new dependency.
- Pacman uses the last value of a scalar and adds up repeated list entries, so a managed block can only be trusted if the original lines are commented out. That also makes "off" and "empty list" work.
- Replacing `/etc/pacman.conf` wholesale and appending an `Include` were both considered; the owner chose the in-place managed block. Repositories stay with the `packages` role (per-repository blocks), so nothing about them changes.
- Removal stays deferred: when a knob is later left unset, its line leaves the block and the commented original is not restored. The `#bastet: ` prefix makes restoring possible later.

## Global Constraints

- **Unit tests** never touch the real inventory, `~/.config/bastet`, `~/.local/share/bastet`, `~/.ssh`, the real `~/.cache` or `$XDG_RUNTIME_DIR`; no network; `tmp_path` only; placeholder data only (see "Example data" in `docs/ROADMAP.md`).
- **Test file basenames unique across `tests/`** (no `__init__.py`). New files named in each task.
- **Contract (container) tests** run only on request (`BASTET_CONTRACT=1`, podman, and a storage config that survives `tests/conftest.py` redirecting `XDG_DATA_HOME`). Agents write them but do not run them.
- **Existing behaviour is preserved** except where a task names the tests that change.
- **Import direction:** `bastet.engine` never imports `bastet.roles`; `bastet.core` never imports `bastet.events`; neither `engine` nor `events` imports `typer`. Messages from the CLI go through `bastet.ui.out`.
- **Commit trailer:**
  ```
  Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01SsS5x4A4m7xaQ5XconTBxo
  ```
  Stage by name, never `git commit -a`. The privacy pre-commit hook runs on every commit.
- **Each task:** failing tests first and seen failing, then implement, then the task's own test files green. The user runs the wider suite at checkpoints.

## Review Focus

1. **Section scoping is real.** A managed key is commented out only inside the named section; another section's key of the same name (a repository's `SigLevel`) is never touched.
2. **Idempotent and self-healing.** Running twice changes nothing; a line re-enabled by hand is commented out again; changing the set of values replaces the block without duplicates or extra comment prefixes.
3. **Off and empty work.** A flag set false or a list set empty comments out the original and writes nothing to the block; an unset knob leaves its original alone; stock `#Key` defaults and keys that merely start with a managed key (`ColorFoo`) are untouched.
4. **No directive injection and nothing silently ignored.** A line break in any value or list item is an error naming the option; `validate` reaches the resource; `mode`/`owner`/`group` on an `edit` entry and `before` together with `after` are contract errors; an `edit: ini` option without a `section` is an error.
5. **A broken block is not guessed at.** A begin marker without its end marker is a read error telling the user to fix the file by hand; a missing section is created at the end of the file.

## File structure

| File | Change |
|---|---|
| `src/bastet/engine/files.py` | new `Settings` resource |
| `src/bastet/roles/declarative.py` | `_ini` emits `Settings`; line-break check in `_keyed`; backup `Command` |
| `src/bastet/roles/contract.py` | `backup` key; the three rejections |
| `src/bastet/data/roles/pacman/pacman role.md` | files entry gains `validate` and `backup: true` |
| `src/bastet/cli/run.py` | `_node_of_map` stops shadowing `out` |
| `src/bastet/engine/packages.py` | dpkg options quoted as one argument (two places) |
| `src/bastet/cli/doctor.py` | `_check_role_dir` accepts a Markdown role folder |
| `src/bastet/roles/contract.py`, `declarative.py`, `apt role.md` | `commands:` entries in role files (with `when`), and the apt `modernize_sources` knob |
| `src/bastet/roles/contract.py`, `declarative.py`, `engine/packages.py`, `builtin.py`, the `apt` and `pacman` role files | `as: entries` with generic `deb822` and `ini_section` formats; the manager roles declare repositories as data and the files action (`File`, `Block`) writes them; `packages` refuses repositories on apt and pacman hosts |

---

### Task 1: The `Settings` resource

**Files:**
- Modify: `src/bastet/engine/files.py`
- Test: `tests/engine/test_settings_edit.py` (new)

**Interfaces:**
- Produces: `Settings(path, section, keys: tuple[str, ...], lines: tuple[str, ...], validate=None, ...)` with the fields `begin="### Bastet Managed ###"`, `end="### End Bastet Managed ###"`, `off_prefix="#bastet: "`. `keys` are all keys the role manages (set or off); `lines` are the finished lines for the block, in order.

**Behaviour of `wanted(content)`** (`slot` is `files`, like `Line`; it derives from `_Edit`):
1. Find the first line that is the section header (`[name]`, surrounding spaces allowed). If absent: with no `lines`, return the text unchanged; otherwise return the text (ensured to end with a newline), a blank line if the text is not empty, `[name]`, the block.
2. The section is the lines after the header up to the next header (or end of file).
3. Remove an existing block from the section (begin line through end line). A begin without an end raises `ReadError(f"unterminated block: '{begin}' has no matching '{end}'; fix the file by hand")` (import from `bastet.engine.model`, as `Block` does).
4. Prefix with `off_prefix` every remaining section line that is active and starts with one of `keys` followed by optional spaces and then `=` or the end of the line (`^\s*(K1|K2|...)\s*(=|$)`, keys escaped).
5. If `lines` is not empty, insert the block (begin, the lines, end) immediately after the header.
- `identity` is `f"settings:{path}:{section}"`; `label` is `f"{path} [{section}]"`; `desired()` returns `{"keys": keys, "lines": lines}`. The block text never appears in a secret-hiding context beyond what `_Edit` already does.

- [ ] **Step 1: Write the failing tests.** Create `tests/engine/test_settings_edit.py`:

```python
import pytest

from bastet.engine.files import Settings
from bastet.engine.model import ReadError

CONF = """\
# header
[options]
#RootDir = /
HoldPkg = pacman glibc
CacheDir = /var/cache/pacman/pkg/
CacheDir = /mnt/cache/
SigLevel = Required DatabaseOptional
Color
ColorFoo = 1
#ParallelDownloads = 5

[custom]
SigLevel = Never
Server = https://example.com/$repo
"""

BEGIN, END = "### Bastet Managed ###", "### End Bastet Managed ###"


def settings(lines=("SigLevel = Required", "CacheDir = /x/"), keys=("SigLevel", "CacheDir", "Color")):
    return Settings(path="/etc/pacman.conf", section="options", keys=keys, lines=lines)


EXPECTED = f"""\
# header
[options]
{BEGIN}
SigLevel = Required
CacheDir = /x/
{END}
#RootDir = /
HoldPkg = pacman glibc
#bastet: CacheDir = /var/cache/pacman/pkg/
#bastet: CacheDir = /mnt/cache/
#bastet: SigLevel = Required DatabaseOptional
#bastet: Color
ColorFoo = 1
#ParallelDownloads = 5

[custom]
SigLevel = Never
Server = https://example.com/$repo
"""


def test_originals_are_commented_inside_the_section_and_the_block_goes_right_after_the_header():
    assert settings().wanted(CONF) == EXPECTED


def test_off_keys_are_commented_and_not_written_and_unmanaged_lines_are_left_alone():
    out = settings().wanted(CONF)
    assert "#bastet: Color\n" in out and "\nColor\n" not in out
    assert "ColorFoo = 1" in out and "#ParallelDownloads = 5" in out and "HoldPkg = pacman glibc" in out


def test_another_section_with_the_same_key_is_never_touched():
    assert "[custom]\nSigLevel = Never\n" in settings().wanted(CONF)


def test_running_twice_changes_nothing():
    once = settings().wanted(CONF)
    assert settings().wanted(once) == once
    assert settings().compare({"content": once}) == []


def test_changing_the_values_replaces_the_block_without_extra_prefixes():
    once = settings().wanted(CONF)
    twice = settings(lines=("SigLevel = Never",)).wanted(once)
    assert twice.count(BEGIN) == 1 and "CacheDir = /x/" not in twice and "SigLevel = Never" in twice
    assert twice.count("#bastet: #bastet:") == 0 and twice.count("#bastet: SigLevel") == 1


def test_a_line_enabled_again_by_hand_is_commented_out_again():
    once = settings().wanted(CONF)
    edited = once.replace("#bastet: SigLevel = Required DatabaseOptional", "SigLevel = Required DatabaseOptional")
    assert settings().wanted(edited) == once


def test_no_lines_means_no_block_but_originals_are_still_commented():
    out = settings(lines=()).wanted(CONF)
    assert BEGIN not in out and "#bastet: SigLevel = Required DatabaseOptional" in out


def test_a_missing_section_is_created_at_the_end():
    out = settings().wanted("[core]\nInclude = /x\n")
    assert out == f"[core]\nInclude = /x\n\n[options]\n{BEGIN}\nSigLevel = Required\nCacheDir = /x/\n{END}\n"
    assert settings(lines=()).wanted("[core]\nInclude = /x\n") == "[core]\nInclude = /x\n"


def test_empty_file_and_no_trailing_newline():
    assert settings().wanted("") == f"[options]\n{BEGIN}\nSigLevel = Required\nCacheDir = /x/\n{END}\n"
    assert settings().wanted("[options]\nColor").endswith("#bastet: Color\n") or "#bastet: Color" in settings().wanted("[options]\nColor")


def test_an_unterminated_block_is_a_read_error():
    with pytest.raises(ReadError, match="unterminated block"):
        settings().wanted(f"[options]\n{BEGIN}\nA = 1\n")


def test_identity_is_per_path_and_section():
    other = Settings(path="/etc/pacman.conf", section="core", keys=("X",), lines=("X = 1",))
    assert settings().identity != other.identity


def test_the_files_owner_group_and_mode_are_left_alone(tmp_path):
    import stat

    from bastet.core.remote import LocalRunner
    from bastet.engine.run import Batch, run_host

    path = tmp_path / "pacman.conf"
    path.write_text(CONF)
    path.chmod(0o640)
    before = path.stat()
    edit = Settings(path=str(path), section="options", keys=("SigLevel", "CacheDir", "Color"),
                    lines=("SigLevel = Required",), root=False)
    run = run_host(LocalRunner(), "h", [Batch("x", [edit])], apply=True)
    after = path.stat()
    assert run.ok and BEGIN in path.read_text()
    assert stat.S_IMODE(after.st_mode) == 0o640 and (after.st_uid, after.st_gid) == (before.st_uid, before.st_gid)
```
(`tests/engine/test_files.py` shows how the other tests run edits with `LocalRunner`; follow its use of `root=False` and adjust only if it differs.)

- [ ] **Step 2: Run to see them fail.** `uv run pytest tests/engine/test_settings_edit.py -q` (no `Settings`).
- [ ] **Step 3: Implement** `Settings` in `engine/files.py` following the behaviour above. Reuse `_Edit.compare`, `fix` and `diff_text` by implementing only `wanted`, `identity`, `label` and `desired`; add `slot: ClassVar[str] = "files"` inherited from `_Edit` (already set). If the last test in the file (the no-trailing-newline one) is awkward to satisfy as written, simplify its assertion to `"#bastet: Color" in settings().wanted("[options]\nColor")` and say so in the report.
- [ ] **Step 4: Run** `uv run pytest tests/engine/test_settings_edit.py tests/engine/test_files.py tests/engine/test_phases.py -q`. **Step 5: Commit** (`files: Settings, a section-scoped managed block that comments out the originals`).

---

### Task 2: `edit: ini` uses `Settings`; contract and value checks; the pacman role

**Files:**
- Modify: `src/bastet/roles/declarative.py`, `src/bastet/roles/contract.py`, `src/bastet/data/roles/pacman/pacman role.md`, `tests/roles/test_pacman_role.py`, `tests/roles/test_declarative_roles.py`, `docs/roles.md` (regenerate)
- Test: `tests/roles/test_ini_settings.py` (new), `tests/contract/test_contract.py` (one new test, not run)

**Behaviour:**
- `_ini(role, values, entry)` returns one `Settings(path=entry["path"], section=name, keys=(...), lines=(...), validate=entry.get("validate"))` per distinct `section`, in the order sections first appear in the contract. An option with a `key` but no `section` under `edit: ini` raises `BastetError(f"{role.name}.{name}: edit: ini needs a section")`. For each option with a `key` and a value that is not `None`: its key joins `keys`; its line joins `lines` unless it is off: a flag whose value is false, or a list that is empty. Line text as before: flag → `Key`; list → `Key = a b c`; value → `Key = v`.
- `_keyed` (all renderers) raises `BastetError(f"{role.name}.{name}: a value can't contain a line break")` when a string value or any list item contains `\n` or `\r`.
- `_file_entry` accepts `backup` (boolean, render or edit) and rejects: `mode`, `owner` or `group` together with `edit` (`files entry: mode, owner and group don't apply to edit (the file keeps its own); use render for a whole file`); `before` together with `after` (`files entry: use before or after, not both`).
- `build` prepends, for `backup: true`, `Command(name=f"back up {path}", run=f"cp -p {path} {path}.bastet-orig", unless=f"test -e '{path}.bastet-orig' || ! test -f '{path}' || grep -q -e 'Bastet Managed' -e 'Managed by Bastet' '{path}'", run_before="files")`; the `Command` is not passed through the per-entry placement helper.
- The pacman role's files entry becomes `{path: /etc/pacman.conf, edit: ini, backup: true, validate: "pacman-conf --config %s >/dev/null"}`. Nothing else in the role changes except the description sentence "Unset = leave pacman's setting as it is", which gains: "Settings you give are written in a Bastet block right after [options], and the original lines are commented out with `#bastet: `."
- Tests that change (they pin the old `Line` objects): `tests/roles/test_pacman_role.py` and the INI cases in `tests/roles/test_declarative_roles.py` now expect one `Settings` (path `/etc/pacman.conf`, section `options`, `provides=("package-manager",)`, the `validate` string) with `keys` and `lines`. Keep every case: defaults (`keys` and `lines` both `("Color", "ILoveCandy")`), a value option (`ParallelDownloads = 8` first, in option order), a flag false (key stays in `keys`, line absent), list join and empty list (key present, line absent), the full option-to-directive mapping, the Arch-only error, the `parallel_downloads` minimum, the single-line errors, and `test_pacman_lines_run_before_the_packages_slot` (the `Settings` ranks before the packages slot). The expected `keys`/`lines` are in contract order.

- [ ] **Step 1: Write the failing tests.** Create `tests/roles/test_ini_settings.py`. Build small Markdown roles under `tmp_path` the way `tests/roles/test_declarative_roles.py` does (reuse its helper if it has one): a role with a `color` flag (`key: Color`, `section: options`, `as: flag`), a `cache_dir` list (`key: CacheDir`, `section: options`, `as: list`), a `sig_level` string (`key: SigLevel`, `section: options`, `single_line: true`) and an `other` string (`key: Other`, `section: extra`).

```python
import pytest

from bastet.core.errors import BastetError
from bastet.engine.command import Command
from bastet.engine.files import Settings

# helpers (write them in this file): ini_role(tmp_path, entry=None, options=None) -> RoleDef with the options above and
# the given file entry (default {"path": "/etc/x.conf", "edit": "ini"}); built(role, values) -> the resources of the
# single batch from declarative.build(role, values, host)


def test_one_settings_per_section_with_keys_and_lines(tmp_path):
    options, extra = built(ini_role(tmp_path), {"color": True, "cache_dir": ["/a/", "/b/"], "sig_level": "Required", "other": "x"})
    assert isinstance(options, Settings) and options.section == "options"
    assert options.keys == ("Color", "CacheDir", "SigLevel")
    assert options.lines == ("Color", "CacheDir = /a/ /b/", "SigLevel = Required")
    assert extra.section == "extra" and extra.lines == ("Other = x",)


def test_off_and_empty_values_keep_the_key_but_write_no_line(tmp_path):
    [options] = built(ini_role(tmp_path), {"color": False, "cache_dir": []})
    assert options.keys == ("Color", "CacheDir") and options.lines == ()


def test_unset_options_are_not_managed(tmp_path):
    assert built(ini_role(tmp_path), {}) == []


def test_validate_reaches_the_resource(tmp_path):
    role = ini_role(tmp_path, entry={"path": "/etc/x.conf", "edit": "ini", "validate": "check %s"})
    [options] = built(role, {"color": True})
    assert options.validate == "check %s"


def test_an_option_without_a_section_is_refused(tmp_path):
    role = ini_role(tmp_path, options={"loose": {"type": "string", "key": "Loose"}})
    with pytest.raises(BastetError, match="edit: ini needs a section"):
        built(role, {"loose": "x"})


@pytest.mark.parametrize("values", [{"sig_level": "a\nSigLevel = Never"}, {"cache_dir": ["/a/", "/b/\nSigLevel = Never"]}])
def test_a_line_break_in_a_value_or_list_item_is_refused(tmp_path, values):
    with pytest.raises(BastetError, match="can't contain a line break"):
        built(ini_role(tmp_path), values)


def test_the_apt_renderer_refuses_line_breaks_too(tmp_path):
    # use an apt-style role (render: apt) with a list option, as tests/roles/test_declarative_roles.py does
    with pytest.raises(BastetError, match="can't contain a line break"):
        built(apt_role(tmp_path), {"acquire_languages": ["en\nAcquire::x \"y\";"]})


@pytest.mark.parametrize("entry, message", [
    ({"edit": "ini", "mode": "0600"}, "don't apply to edit"),
    ({"edit": "ini", "owner": "root"}, "don't apply to edit"),
    ({"edit": "ini", "group": "root"}, "don't apply to edit"),
    ({"edit": "ini", "before": "packages", "after": "files"}, "before or after, not both"),
])
def test_unusable_file_entry_combinations_are_refused(tmp_path, entry, message):
    with pytest.raises(BastetError, match=message):
        ini_role(tmp_path, entry={"path": "/etc/x.conf", **entry})


def test_backup_command_runs_before_the_files_slot_once(tmp_path):
    role = ini_role(tmp_path, entry={"path": "/etc/x.conf", "edit": "ini", "backup": True})
    command, options = built(role, {"color": True})
    assert isinstance(command, Command) and command.run_before == "files"
    assert command.run == "cp -p /etc/x.conf /etc/x.conf.bastet-orig"
    for part in ("test -e '/etc/x.conf.bastet-orig'", "! test -f '/etc/x.conf'", "-e 'Bastet Managed'", "-e 'Managed by Bastet'"):
        assert part in command.unless
    assert isinstance(options, Settings)
```

- [ ] **Step 2: Run to see them fail.** `uv run pytest tests/roles/test_ini_settings.py -q`.
- [ ] **Step 3: Implement** as described under Behaviour, then update the role file and the two golden test files named above. Regenerate `docs/roles.md` with `scripts/gen_roles_doc.py`.
- [ ] **Step 4: Contract test (written, not run).** Add `test_arch_pacman_managed_block_contract` to `tests/contract/test_contract.py`, modelled on `test_arch_pacman_contract`: write a `pacman.conf` with an `[options]` section that has an active `ParallelDownloads = 5` and `Color`, plus a `[custom]` section with its own `SigLevel = Never`; converge `{"parallel_downloads": 7, "color": False}`; assert `pacman-conf ParallelDownloads` is `7`, `Color` is no longer reported, the `[custom]` repository's `SigLevel` is still `Never`, `/etc/pacman.conf.bastet-orig` holds the original text, and a second converge changes nothing.
- [ ] **Step 5: Run** `uv run pytest tests/roles tests/engine tests/core -q` and `scripts/privacy-check`. **Step 6: Commit** (`roles: edit: ini writes a managed block per section; contract and value checks`).

---

### Task 3: Three quick fixes

**Files:**
- Modify: `src/bastet/cli/run.py` (`_node_of_map`), `src/bastet/engine/packages.py` (two lines), `src/bastet/cli/doctor.py` (`_check_role_dir`)
- Test: `tests/cli/test_node_map_cycle.py` (new), additions to `tests/engine/test_packages.py`, `tests/engine/test_updates.py`, `tests/cli/test_doctor_cli.py`

**Behaviour:**
- `_node_of_map`: rename the local dictionary from `out` to `node_of`, so `out.secho` reaches the console helper. A self-cycle and a two-host cycle each print `runs_on loop: ...; ignoring it for ordering` and do not raise.
- `packages.py`: both `-o Dpkg::Options::={o}` pieces become one quoted argument, `shlex.quote(f"Dpkg::Options::={o}")` (the module already imports `shlex`). Safe characters stay unquoted, so existing expectations such as `-o Dpkg::Options::=--force-confnew` do not change.
- `doctor <folder>`: a folder is a role if it holds `role.yml` or `<name> role.md`; otherwise the error is `no role definition (role.yml or "<name> role.md") in <path>`. The success message names the format found.

- [ ] **Step 1: Write the failing tests.**

`tests/cli/test_node_map_cycle.py`:

```python
from types import SimpleNamespace

from bastet.cli import run as run_cli


def _ready(name, runs_on):
    return SimpleNamespace(doc=SimpleNamespace(name=name, data={"runs_on": runs_on}))


class Inv:
    def get(self, name):
        return SimpleNamespace(name=name)


def _run(monkeypatch, by_name, names):
    printed = []
    monkeypatch.setattr(run_cli.out, "secho", lambda text, **kw: printed.append(text))
    result = run_cli._node_of_map(by_name, names, Inv())
    return result, printed


def test_a_two_host_cycle_is_reported_not_crashed(monkeypatch):
    by_name = {"a": _ready("a", "[[b]]"), "b": _ready("b", "[[a]]")}
    result, printed = _run(monkeypatch, by_name, ["a", "b"])
    assert isinstance(result, dict) and any("runs_on loop" in p for p in printed)


def test_a_host_that_runs_on_itself_is_reported(monkeypatch):
    result, printed = _run(monkeypatch, {"a": _ready("a", "[[a]]")}, ["a"])
    assert result == {} and any("runs_on loop" in p for p in printed)
```

If the `Inv` stand-in does not match what `_node_of_map` needs (`inv.get`), adjust the fake, not the code.

Append to `tests/engine/test_packages.py` (it already has the `cmds` helper):

```python
def test_dpkg_options_stay_one_argument():
    last = cmds(Package(name="tree", dpkg_options=("--x; echo hi",)))[-1]
    assert "'Dpkg::Options::=--x; echo hi'" in last
    assert "-o Dpkg::Options::=--force-confnew" in cmds(Package(name="tree", dpkg_options=("--force-confnew",)))[-1]
```

In `tests/engine/test_updates.py`, add the equivalent for an `Updates` resource with `dpkg_options`, using that file's own helper for building the commands (read the file first and follow its pattern).

In `tests/cli/test_doctor_cli.py`, add: the bundled `pacman` folder (`src/bastet/data/roles/pacman`) and the bundled `ssh` folder both lint successfully; an empty folder fails with the new message. Use the file's existing way of invoking `bastet doctor <dir>`.

- [ ] **Step 2: Run to see them fail.** `uv run pytest tests/cli/test_node_map_cycle.py tests/engine/test_packages.py tests/engine/test_updates.py tests/cli/test_doctor_cli.py -q`.
- [ ] **Step 3: Implement** the three edits. For `_check_role_dir` use:

```python
def _check_role_dir(path: Path) -> None:
    from bastet.roles.contract import load_roles

    name = path.resolve().name
    found = "role.yml" if (path / "role.yml").is_file() else f"{name} role.md" if (path / f"{name} role.md").is_file() else None
    if found is None:
        raise BastetError(f'no role definition (role.yml or "{name} role.md") in {path}')
    if name not in load_roles(path.parent):
        raise BastetError(f"{path}: not loaded as a role")
    out.echo(f"{path}: parses as a role definition ({found}).")
```

- [ ] **Step 4: Run** the same files, then `uv run pytest tests/roles tests/engine tests/cli -q`. **Step 5: Commit** (`fixes: cycle warning, dpkg option quoting, doctor on Markdown roles`).

---

### Task 4: Repositories move to the manager roles (pacman, apt), as data

**Principle (owner):** only the building blocks have real code. A role is data that the blocks act on. The generic builder therefore knows generic file formats only (`deb822`, `ini_section`), never "apt" or "pacman"; the apt and pacman roles describe their repository files in their own role files.

**Files:**
- Modify: `src/bastet/roles/contract.py` (`OPTION_AS`, `OPTION_KEYS`, `Option`, option checks), `src/bastet/roles/declarative.py`, `src/bastet/data/roles/pacman/pacman role.md`, `src/bastet/data/roles/apt/apt role.md`, `src/bastet/engine/packages.py` (remove the pacman branch of `Repository`), `src/bastet/roles/builtin.py` (`_packages`), `src/bastet/data/roles/packages/role.yml` (description of `repositories`), the user docs that mention `packages` repositories (find them with `grep -rn "repositories" src/bastet/data/docs docs/*.md`), `docs/roles.md` (regenerate), and the existing tests named below
- Test: `tests/roles/test_repository_entries.py` (new)

**Behaviour:**
- Contract. A new option kind `as: entries` (allowed only on an option of type `list` whose items are objects; otherwise `{where}: as: entries needs a list of objects`) turns every list item into a file entry. It needs `format` (`deb822` or `ini_section`), `path` (a path that may contain `{name}`), and may have `marker` (ini_section only; may contain `{name}`; default `"{name}"`) and `before`/`after` (same meaning as on a file entry). `format`, `path`, `marker`, `before`, `after` on an option that is not `as: entries` is an error (`{where}: format only applies to as: entries`, and so on). `Option` gains `format`, `path`, `marker`, `before`, `after` (add to `OPTION_KEYS`). Fields of an item may use `key` (the field's name in the file) and a new `as` value `lines` (one `Key = v` line per list element) or `text` (a multi-line value) next to `list`; `as` accepts `flag, value, list, lines, text, entries`.
- Builder, generic. For each item (apply each field's `default` when the item leaves it out; validate the item's `name` against `^[A-Za-z0-9][A-Za-z0-9._+-]*$`, otherwise `BastetError(f"{role.name}.{option}: {name!r} isn't a usable name")`; refuse line breaks in every value except fields declared `as: text`):
  - `deb822` → `File(path=path.format(name=name), content=..., mode="0644")`. The content has one `Key: value` line per field that has a `key` and a value, in contract order. A list is joined with spaces; a bool is `yes` or `no`; an empty list or unset field is left out; a `text` value with line breaks is written as `Key:` followed by each line indented by one space, with blank lines as ` .`.
  - `ini_section` → `Block(path=path, block=..., marker=marker.format(name=name))`. The block is `[name]` followed by one `Key = value` line per field with a `key`: `lines` gives one line per element, a list joins with spaces, anything else is `Key = value`. If the item has a field named `enabled` set to false, every line of the block, including the header, is prefixed with `#`.
  - Each resulting resource gets `run_before`/`run_after` from the option's `before`/`after`. The builder contains no apt or pacman names.
- The roles. `apt role.md` gets a `repositories` option: `as: entries`, `format: deb822`, `path: /etc/apt/sources.list.d/{name}.sources`, `before: packages`, items with fields `name` (required), `types` (list, `key: Types`, default `[deb]`), `uris` (list, required, `key: URIs`), `suites` (list, `key: Suites`), `components` (list, `key: Components`), `architectures` (list, `key: Architectures`), `enabled` (bool, `key: Enabled`), `trusted` (bool, `key: Trusted`), `signed_by` (string, `as: text`, `key: Signed-By`; a path, or the armored key text). `pacman role.md` gets one: `as: entries`, `format: ini_section`, `path: /etc/pacman.conf`, `marker: "bastet repo {name}"` (the marker the old resource used, so blocks already written are recognised), `before: packages`, items with `name` (required), `servers` (list, `as: lines`, `key: Server`), `include` (string, `key: Include`), `sig_level` (string, `key: SigLevel`), `usage` (string, `key: Usage`), `enabled` (bool). Descriptions say the repository is written in the host's own format; add one example each.
- `Repository` loses its pacman branch (`parts`, `_check`, `_pacman`); the apt, rpm and apk behaviour and the proxmox role's repositories are untouched. The pacman cases of `tests/engine/test_repositories.py` are removed with it (keep every other test in that file).
- The `packages` role keeps `repositories` for the managers that have no role yet (dnf, zypper, apk). On an Arch-based or Debian-based host, `_packages` raises `BastetError("packages.repositories: set repositories in the pacman role on Arch-based hosts and in the apt role on Debian-based hosts")` when the option is non-empty.
- Existing host notes that give `repositories:` to the `packages` role on Arch or Debian hosts must move that block to the matching manager role; the error says so. The old `packages` fields `key`, `options` and `trusted` for pacman and apt are not carried over (`options` become explicit fields; pacman's `trusted: true` is `sig_level: Never`).

- [ ] **Step 1: Write the failing tests.** Create `tests/roles/test_repository_entries.py` (use the temporary-role helpers from `tests/roles/test_ini_settings.py`; hosts are built as in `tests/roles/test_pacman_role.py` and `test_apt_role.py`):

```python
import pytest

from bastet.core.errors import BastetError
from bastet.engine.files import Block, File

# helpers: built(role_name, values, host) -> resources of every batch from batches_for with that role applied;
# debian_host(), arch_host(), fedora_host() -> HostInfo; bad_role(tmp_path, option_dict) -> writes a one-option
# Markdown role the way the other role tests do


def apt_file(out, name):
    [file] = [r for r in out if isinstance(r, File) and r.path == f"/etc/apt/sources.list.d/{name}.sources"]
    return file


def test_apt_repository_is_a_sources_file_before_packages():
    out = built("apt", {"repositories": [{"name": "backports", "uris": ["http://deb.example.net/debian"],
                                          "suites": ["trixie-backports"], "components": ["main"]}]}, debian_host())
    file = apt_file(out, "backports")
    assert file.mode == "0644" and file.run_before == "packages"
    assert file.content == ("Types: deb\nURIs: http://deb.example.net/debian\nSuites: trixie-backports\nComponents: main\n")


def test_apt_flags_and_multiline_keys_are_written_in_deb822_style():
    key = "-----BEGIN PGP PUBLIC KEY BLOCK-----\n\nAAAA\n-----END PGP PUBLIC KEY BLOCK-----"
    out = built("apt", {"repositories": [{"name": "k", "uris": ["http://x.example.net/"], "suites": ["s"],
                                          "enabled": False, "trusted": True, "signed_by": key}]}, debian_host())
    assert apt_file(out, "k").content == (
        "Types: deb\nURIs: http://x.example.net/\nSuites: s\nEnabled: no\nTrusted: yes\n"
        "Signed-By:\n -----BEGIN PGP PUBLIC KEY BLOCK-----\n .\n AAAA\n -----END PGP PUBLIC KEY BLOCK-----\n")
    path_form = built("apt", {"repositories": [{"name": "p", "uris": ["http://x/"], "suites": ["s"], "signed_by": "/usr/share/keyrings/x.gpg"}]}, debian_host())
    assert "Signed-By: /usr/share/keyrings/x.gpg\n" in apt_file(path_form, "p").content


def test_pacman_repository_is_a_marked_block_before_packages():
    out = built("pacman", {"repositories": [{"name": "custom", "servers": ["https://example.net/$repo/os/$arch"], "sig_level": "Optional"}]}, arch_host())
    [block] = [r for r in out if isinstance(r, Block)]
    assert block.path == "/etc/pacman.conf" and block.marker == "bastet repo custom" and block.run_before == "packages"
    assert block.block == "[custom]\nServer = https://example.net/$repo/os/$arch\nSigLevel = Optional"


def test_pacman_repository_with_several_servers_and_an_include():
    out = built("pacman", {"repositories": [{"name": "r", "servers": ["https://a/", "https://b/"], "include": "/etc/pacman.d/mirrorlist"}]}, arch_host())
    [block] = [r for r in out if isinstance(r, Block)]
    assert block.block == "[r]\nServer = https://a/\nServer = https://b/\nInclude = /etc/pacman.d/mirrorlist"


def test_a_disabled_pacman_repository_is_commented_out():
    out = built("pacman", {"repositories": [{"name": "off", "servers": ["https://x.example.net/"], "enabled": False}]}, arch_host())
    [block] = [r for r in out if isinstance(r, Block)]
    assert block.block == "#[off]\n#Server = https://x.example.net/"


@pytest.mark.parametrize("role_name, host_kind", [("apt", "debian"), ("pacman", "arch")])
def test_bad_names_and_line_breaks_are_refused(role_name, host_kind):
    host = debian_host() if host_kind == "debian" else arch_host()
    with pytest.raises(BastetError, match="isn't a usable name"):
        built(role_name, {"repositories": [{"name": "a b", "uris": ["http://x/"], "servers": ["http://x/"]}]}, host)
    field = "suites" if role_name == "apt" else "servers"
    with pytest.raises(BastetError, match="can't contain a line break"):
        built(role_name, {"repositories": [{"name": "ok", "uris": ["http://x/"], field: ["a\nUsage = All"]}]}, host)


def test_no_repositories_means_no_extra_resources():
    assert not [r for r in built("apt", {}, debian_host()) if isinstance(r, File) and "sources.list.d" in r.path]


@pytest.mark.parametrize("host_kind", ["arch", "debian"])
def test_the_packages_role_refuses_repositories_on_apt_and_pacman_hosts(host_kind):
    host = arch_host() if host_kind == "arch" else debian_host()
    with pytest.raises(BastetError, match="set repositories in the pacman role"):
        built("packages", {"repositories": [{"name": "x", "uris": ["http://x"]}]}, host)


def test_the_packages_role_still_takes_repositories_for_other_managers():
    from bastet.engine.packages import Repository
    out = built("packages", {"repositories": [{"name": "x", "uris": ["http://x"]}]}, fedora_host())
    assert any(isinstance(r, Repository) for r in out)


_ITEMS = {"type": "object", "fields": {"name": {"type": "string"}}}


@pytest.mark.parametrize("option, message", [
    ({"type": "string", "as": "entries", "format": "ini_section", "path": "/x", "key": "X"}, "as: entries needs a list of objects"),
    ({"type": "list", "items": _ITEMS, "as": "entries", "path": "/x"}, "needs format"),
    ({"type": "list", "items": _ITEMS, "as": "entries", "format": "zzz", "path": "/x"}, "needs format"),
    ({"type": "list", "items": _ITEMS, "as": "entries", "format": "deb822"}, "needs a path"),
    ({"type": "string", "format": "deb822"}, "format only applies to as: entries"),
    ({"type": "list", "items": _ITEMS, "as": "entries", "format": "deb822", "path": "/x/{name}", "marker": "m"}, "marker only applies to ini_section"),
])
def test_entries_option_contract(tmp_path, option, message):
    with pytest.raises(BastetError, match=message):
        bad_role(tmp_path, option)
```

- [ ] **Step 2: Run to see them fail.** `uv run pytest tests/roles/test_repository_entries.py -q`.
- [ ] **Step 3: Implement** as described under Behaviour. Existing tests to update (say which in your report): the pacman cases of `tests/engine/test_repositories.py` go with the pacman branch; tests that gave `repositories` to the `packages` role on a Debian or Arch host (look in `tests/roles/test_builtin.py` and `tests/roles/test_system_roles.py`) move to the `apt` or `pacman` role, or switch to a Fedora-like host if the case is really about the `packages` role itself; `tests/roles/test_role_contract.py` and the role-listing tests may need the new option kinds. The proxmox role's repositories must be unchanged (its tests pass untouched).
- [ ] **Step 4: Contract test (written, not run).** In `tests/contract/test_contract.py`, if a test builds repositories through the `packages` role on the Debian or Arch container, switch it to the `apt` or `pacman` role.
- [ ] **Step 5: Run** `uv run pytest tests/roles tests/engine tests/core tests/cli/test_add_role.py tests/test_cli.py -q`, regenerate `docs/roles.md` with `scripts/gen_roles_doc.py`, run `scripts/privacy-check`. **Step 6: Commit** (`roles: apt and pacman declare their repositories as data; generic deb822 and ini_section entries`).

---

### Task 5: `commands:` entries in role files, and the apt `modernize_sources` knob

**Principle (owner):** roles are data; the `commands` block does the running. A role file may list commands for the block to run, optionally switched by one of the role's own options. The apt role uses it for a true/false `modernize_sources` knob (default false) that runs `apt modernize-sources`, which rewrites any leftover legacy `.list` file as a `.sources` file and does nothing when there is nothing to rewrite.

**Files:**
- Modify: `src/bastet/roles/contract.py` (`ROLE_NOTE_KEYS`, a `commands` parser, `RoleDef.commands`), `src/bastet/roles/declarative.py` (`build`), `src/bastet/data/roles/apt/apt role.md`, `docs/roles.md` (regenerate)
- Test: `tests/roles/test_role_commands.py` (new), one case in `tests/roles/test_apt_role.py`

**Behaviour:**
- A role note may have a top-level `commands` list. Each entry is a map with `name` (text, required), `run` (text, required), `unless` (text, required: the command is skipped when it succeeds, as for the `Command` resource), and optional `when` (the name of one of the role's options; the entry applies only when that option's value is true), `before` and `after` (block names, not both). Any other key is an error naming it; a `when` that names no option is an error (`commands entry: when names no option: <x>`). Add `commands` to `ROLE_NOTE_KEYS` and store the parsed list on `RoleDef` (field `commands`, default empty).
- `build` appends, after the file entries and the option entries, one `Command(name=..., run=..., unless=..., run_before=..., run_after=...)` for each command whose `when` is absent or whose option is true in `values`. The builder contains no apt names.
- `apt role.md` gets an option `modernize_sources` (`type: bool`, `default: false`, description: "Run `apt modernize-sources` to convert leftover legacy .list files to .sources; does nothing when there is nothing to convert") and this command: name `modernize apt sources`; run `apt modernize-sources -y`; unless `! apt --help 2>/dev/null | grep -q modernize-sources || ! grep -qsE '^[[:space:]]*(deb|deb-src)[[:space:]]' /etc/apt/sources.list /etc/apt/sources.list.d/*.list` (skips on apt versions that lack the subcommand, and when no active legacy line is left, which also makes `check` quiet once it has run); `when: modernize_sources`; `before: packages`. Verified in a Debian 13 container: with a legacy `.list` file the command rewrites it and leaves `<file>.list.bak`, and a second run prints "All sources are modern." and exits 0. Add the caveat to the option description: where apt cannot work out `Signed-By` it prints a warning and the new file has none.

- [ ] **Step 1: Write the failing tests.** Create `tests/roles/test_role_commands.py` (use the temporary-role helpers from `tests/roles/test_ini_settings.py`):

```python
import pytest

from bastet.core.errors import BastetError
from bastet.engine.command import Command

# helpers: cmd_role(tmp_path, commands, options=None) -> RoleDef with a bool option "on" and the given commands list;
# built(role, values) -> the resources of the single batch from declarative.build(role, values, host)

ENTRY = {"name": "say hi", "run": "echo hi", "unless": "test -e /tmp/x"}


def test_a_command_entry_becomes_a_command_resource(tmp_path):
    [command] = built(cmd_role(tmp_path, [{**ENTRY, "before": "packages"}]), {})
    assert isinstance(command, Command)
    assert (command.name, command.run, command.unless, command.run_before) == ("say hi", "echo hi", "test -e /tmp/x", "packages")


def test_when_switches_the_command_on_the_option(tmp_path):
    role = cmd_role(tmp_path, [{**ENTRY, "when": "on"}])
    assert built(role, {"on": True}) and not built(role, {"on": False}) and not built(role, {})


@pytest.mark.parametrize("entry, message", [
    ({"run": "x", "unless": "y"}, "name"),
    ({"name": "n", "unless": "y"}, "run"),
    ({"name": "n", "run": "x"}, "unless"),
    ({**ENTRY, "when": "nope"}, "when names no option: nope"),
    ({**ENTRY, "before": "packages", "after": "files"}, "before or after, not both"),
    ({**ENTRY, "zzz": 1}, "zzz"),
])
def test_command_entry_errors(tmp_path, entry, message):
    with pytest.raises(BastetError, match=message):
        cmd_role(tmp_path, [entry])
```

Add to `tests/roles/test_apt_role.py`: with `modernize_sources` false or unset the apt role builds no `Command`; with `{"modernize_sources": True}` it builds one `Command` named `modernize apt sources` whose `run` is `apt modernize-sources -y`, whose `run_before` is `packages`, and whose `unless` contains `modernize-sources` and `deb-src`.

- [ ] **Step 2: Run to see them fail.** `uv run pytest tests/roles/test_role_commands.py tests/roles/test_apt_role.py -q`.
- [ ] **Step 3: Implement** as described under Behaviour. Regenerate `docs/roles.md` with `scripts/gen_roles_doc.py`.
- [ ] **Step 4: Contract test (written, not run).** Add `test_debian_apt_modernize_sources_contract` to `tests/contract/test_contract.py`, modelled on `test_debian_apt_role_contract`: write a legacy `/etc/apt/sources.list.d/legacy.list` in the container, converge `{"modernize_sources": True}`, assert `legacy.sources` exists and `legacy.list.bak` exists, then that a second converge changes nothing.
- [ ] **Step 5: Run** `uv run pytest tests/roles tests/core tests/engine -q` and `scripts/privacy-check`. **Step 6: Commit** (`roles: commands entries in role files; apt modernize_sources knob`).

---

### Task 6: Strip the repository support nobody uses

**Decision (owner):** after repositories moved into the `apt` and `pacman` roles, the `packages` role's `repositories` option and the dnf, zypper and apk parts of `Repository` have no user. Remove them. The proxmox role's apt repositories (which use `Repository`) stay.

**Files:**
- Modify: `src/bastet/data/roles/packages/role.yml` (remove the `repositories` option, its example, and the repository mention in the description), `src/bastet/roles/builtin.py` (`_packages`: remove the repository handling and the refusal added in Task 4; remove imports that become unused), `src/bastet/engine/packages.py` (`Repository`: remove the rpm (dnf, zypper) and apk branches and what only they use: `_ini`, `_rpm_key_path`, `_apk_key_path`, the key-file handling for those managers, the `trusted`/`options` checks that only applied to them, and `KEY_NAME`/`key_name` if nothing else uses them; keep the apt branch, the pacman `Unsupported` guard from Task 4 can also go because pacman and the others now fall under "not supported"), `docs/roles.md` (regenerate), user docs that mention `packages` repositories (`grep -rn "repositories" src/bastet/data/docs docs/*.md`)
- Tests: `tests/engine/test_repositories.py` (remove the rpm, zypper and apk cases and any test that only exercises removed fields; keep every apt and proxmox test), `tests/roles/test_repository_entries.py` (remove the two tests about the `packages` role refusing or accepting repositories), and any test that passes `repositories` to the `packages` role

**Behaviour:**
- A host note that still gives `repositories:` to the `packages` role now gets the normal unknown-option error from the contract (with its "did you mean" hint); add one test for that in `tests/roles/test_repository_entries.py`.
- `Repository.current` on a manager other than apt raises `Unsupported(f"repositories are only written for apt here; this host uses {manager}")`.
- Nothing about `Package`, `Updates` or the other managers' package installs changes.

- [ ] **Step 1: Write the failing tests** (the unknown-option test; a `Repository` on a pacman, dnf and apk manager raises the `Unsupported` message above; `rg "dnf|zypper|apk" src/bastet/engine/packages.py` shows no repository code left in `Repository`, but package-install code for those managers remains).
- [ ] **Step 2: Run to see them fail.** `uv run pytest tests/roles/test_repository_entries.py tests/engine/test_repositories.py -q`.
- [ ] **Step 3: Implement** the removals. Do not touch the proxmox role, `Package` or `Updates`.
- [ ] **Step 4: Run** `uv run pytest tests/roles tests/engine tests/core tests/cli/test_add_role.py tests/test_cli.py -q`, regenerate `docs/roles.md` with `scripts/gen_roles_doc.py`, run `scripts/privacy-check`. **Step 5: Commit** (`packages: remove repository support for managers without a role`).

---

### Task 7: Docs and the checkpoint

**Files:** `docs/specs/2026-10-10-bastet-roles-architecture-design.md`, `docs/ROADMAP.md`, `docs/plans/2026-10-10-bastet-audit-correction-plan.md`, `src/bastet/data/docs/writing_roles.md`.

- [ ] **Step 1: Docs.** Record `Settings` (managed block per section, originals commented with `#bastet: `, off and empty supported, removal deferred) and the `backup` key in the roles spec, the roadmap blocks table and `writing_roles.md`. In the correction plan: mark increment 1 done and drop the "do not apply to a real `pacman.conf`" warning only after the owner's check below. Example data only; every `[[link]]` must resolve.
- [ ] **Step 2: Full suite** `uv run pytest -q` and `scripts/privacy-check`. **Step 3: Commit** (`docs: audit increment 1`).
- [ ] **Checkpoint (controller and owner).**
  - With the podman storage workaround from the correction plan: `BASTET_CONTRACT=1 uv run pytest tests/contract/test_contract.py -k "pacman or apt or ssh" -q`.
  - Owner: `bastet run -c` against a real Arch host whose `pacman.conf` has repository sections. The plan must show only `[options]` changes: a managed block after the header and `#bastet: ` comments on the originals; no repository section changes. Then apply.
