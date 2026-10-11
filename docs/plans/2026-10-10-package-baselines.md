# Provider image package baselines — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. In this repo, the `bastet-run-plan` skill supplies the Bastet-specific parts.

**Goal:** the packages a provider's stock image installs get a pass in the unaccounted-packages report: not managed, not installed, never counted as unaccounted or as drift. The lists belong to the program (shipped data), not to a vault.

**Architecture:** one text file per provider image in `src/bastet/data/baselines/<provider>-<os>.txt` (one package name per line). The packages role's builder adds the matching file's names to the `allowed` set of the `Unaccounted` report.

**Tech Stack:** Python ≥3.12, pytest.

## Global Constraints

- **Unit tests** never touch the real inventory, `~/.config/bastet`, `~/.local/share/bastet`, `~/.ssh`, the real `~/.cache` or `$XDG_RUNTIME_DIR`; no network; `tmp_path` only; placeholder data only (see "Example data" in `docs/ROADMAP.md`).
- **Test file basenames unique across `tests/`** (no `__init__.py`).
- **Commit trailer:**
  ```
  Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01SsS5x4A4m7xaQ5XconTBxo
  ```
  Stage by name and commit with explicit paths (`git commit -m ... -- <paths>`); never `git commit -a`.

## Review Focus

1. **Only a matching host gets the pass.** A host with `provider: linode` on an Arch-based OS gets `linode-arch`; another provider, another OS, or no provider gets nothing extra; matching is case-insensitive on the provider and the file name is the only lookup (a provider value cannot reach outside the baselines folder).
2. **The pass is just an allowance.** Nothing is installed or managed; a baseline package still counts in `tracked` terms for nothing; a package not in the baseline is still reported; the user's own `allowed:` still works and is merged with the baseline.
3. **No real lab data.** The shipped list is the stock Linode Arch image's explicitly installed packages only.

---

### Task 1: Linode Arch baseline

**Files:**
- Create: `src/bastet/data/baselines/linode-arch.txt`, `src/bastet/roles/baselines.py`
- Modify: `src/bastet/roles/builtin.py` (`_packages`), `src/bastet/data/roles/packages/role.yml` (the `allowed` and `report_unaccounted` descriptions), `docs/ROADMAP.md` (reports row), `src/bastet/data/docs/` page that describes unaccounted packages if one exists (`grep -rn "unaccounted" src/bastet/data/docs`)
- Test: `tests/roles/test_package_baselines.py` (new)

**`linode-arch.txt`** (exactly these lines, from `pacman -Qqe` on a fresh Linode Arch image):

```
base
cloud-init
grub
haveged
inetutils
iotop
linux
linux-firmware
lsof
man-db
man-pages
mtr
nano
net-tools
openbsd-netcat
openssh
sudo
sysstat
vim
whois
```

**Interfaces:**
- Produces: `baseline_for(host) -> tuple[str, ...]` in `src/bastet/roles/baselines.py`: reads `host.data.get("provider")`; returns the names in `data/baselines/<provider lower-cased>-<os>.txt` where `<os>` is `arch` when `host.os_id in ARCH_LIKE` and `debian` when `host.debian_like`, else no baseline. The provider must match `^[a-z0-9][a-z0-9-]*$` after lower-casing, otherwise return `()`. A missing file returns `()`. Blank lines and lines starting with `#` in a baseline file are ignored.
- `_packages` passes `allowed=tuple(v.get("allowed") or ()) + baseline_for(host)` to `Unaccounted` (a name in both appears once).

- [ ] **Step 1: Write the failing tests** in `tests/roles/test_package_baselines.py`. Build hosts as `tests/roles/test_pacman_role.py` does (`HostInfo` with `data={"os": "Arch Linux", "provider": "linode"}` and so on):

```python
from pathlib import Path

from bastet.engine.packages import Unaccounted
from bastet.roles.baselines import baseline_for
from bastet.roles.builtin import HostInfo, batches_for
# plus the Applied helper used in the other role tests to apply the "packages" role


def host(os="Arch Linux", **data):
    return HostInfo(name="vps1", type="vps", data={"os": os, **data}, root=Path("/nonexistent"), lab={})


def test_a_linode_arch_host_gets_the_shipped_baseline():
    names = baseline_for(host(provider="linode"))
    assert {"base", "cloud-init", "grub", "linux", "openssh", "sudo", "vim"} <= set(names) and len(names) == 20


def test_provider_matching_is_case_insensitive():
    assert baseline_for(host(provider="Linode")) == baseline_for(host(provider="linode"))


def test_other_providers_other_oses_and_no_provider_get_nothing():
    assert baseline_for(host(provider="hetzner")) == ()
    assert baseline_for(host(os="Debian GNU/Linux 13 (trixie)", provider="linode")) == ()
    assert baseline_for(host()) == ()


def test_a_provider_value_cannot_escape_the_baselines_folder():
    assert baseline_for(host(provider="../roles/packages/role")) == ()
    assert baseline_for(host(provider="a/b")) == ()


def test_the_unaccounted_report_allows_the_baseline_and_the_users_own_allowed_list():
    # apply the packages role with {"allowed": ["htop"]} to host(provider="linode") through batches_for
    report = [r for b in batches for r in b.resources if isinstance(r, Unaccounted)][0]
    assert {"cloud-init", "grub", "htop"} <= set(report.allowed)
    assert report.allowed.count("htop") == 1


def test_a_baseline_package_is_not_reported_but_others_are():
    unaccounted = Unaccounted(tracked=(), allowed=baseline_for(host(provider="linode")))
    # feed Unaccounted.current() the explicit/system read results the way tests/engine/test_updates.py does (pacman manager)
    # with explicit "cloud-init\nhtop\nvim" and system "base\nbase-devel": only "htop" is unaccounted
```

(For the last test, copy how `tests/engine/test_updates.py` fabricates `results` for `Unaccounted.current`.)
- [ ] **Step 2: Run to see them fail.** `uv run pytest tests/roles/test_package_baselines.py -q`.
- [ ] **Step 3: Implement** `baselines.py` (load with `importlib.resources`, as `contract._shipped_dir` does for roles), the data file, and the `_packages` change. Update the two option descriptions in `role.yml` to mention that a provider's stock-image packages are allowed automatically. Add a line to the roadmap reports row. Make sure the wheel includes `data/baselines/*.txt` (check how `pyproject.toml` includes `data/`; add the pattern only if needed and say so).
- [ ] **Step 4: Run** `uv run pytest tests/roles tests/engine tests/core -q`, regenerate `docs/roles.md` with `uv run python scripts/gen_roles_doc.py`, run `scripts/privacy-check`. **Step 5: Commit** with explicit paths (`packages: provider image baselines get a pass in the unaccounted report`).
