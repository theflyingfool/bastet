# Host types: merge UniFi, rename laptop and unknown, set the add-host order — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. In this repo, the `bastet-run-plan` skill supplies the Bastet-specific parts.

**Goal:** the host types match how the owner thinks about them, and `bastet add host` offers them in a fixed order.

**Architecture:** host types are data (`src/bastet/data/types/*.yml`). Three UniFi types become one, `laptop` becomes `computer`, `unknown` becomes `undefined`, descriptions are reworded, and a new `order` field in each type file sets the menu order.

**Tech Stack:** Python ≥3.12, pytest.

## The types (owner's wording and order)

| order | name | description |
|---|---|---|
| 1 | `computer` | A user's workstation |
| 2 | `server` | Physical Linux server |
| 3 | `proxmox` | Proxmox node |
| 4 | `unifi` | UniFi branded hardware |
| 5 | `vm` | Virtual machine |
| 6 | `lxc` | LXC container |
| 7 | `vps` | Virtual private server |
| 8 | `undefined` | Type not decided yet; gather will propose one |
| 9 | `other` | Anything on the network Bastet doesn't manage |

`vm` and `lxc` no longer say "on a Proxmox node" (a VM can run on a computer). All other fields of each type stay as they are (`physical`, `gather`, `managed`, `managed_by`, `minimal`, `fields`), with these facts checked on the existing files: `unifi-ap`, `unifi-switch` and `unifi-gateway` are identical except that the gateway also has `networks: fact`; the merged `unifi` type keeps `networks: fact`. No Python code mentions the three UniFi names.

## Global Constraints

- **Unit tests** never touch the real inventory, `~/.config/bastet`, `~/.local/share/bastet`, `~/.ssh`, the real `~/.cache` or `$XDG_RUNTIME_DIR`; no network; `tmp_path` only; placeholder data only (see "Example data" in `docs/ROADMAP.md`).
- **Test file basenames unique across `tests/`** (no `__init__.py`).
- **Import direction:** `bastet.engine` never imports `bastet.roles`; `bastet.core` never imports `bastet.events`; neither `engine` nor `events` imports `typer`. Messages go through `bastet.ui.out`.
- **Commit trailer:**
  ```
  Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01SsS5x4A4m7xaQ5XconTBxo
  ```
  Stage by name and commit with explicit paths (`git commit -m ... -- <paths>`); never `git commit -a`.

## Review Focus

1. **Every old name is gone from data and code.** `laptop`, `unknown` and the three `unifi-*` names appear nowhere in `src`, tests or docs except in historical plans. No migration (the owner is starting a fresh vault): an old name is just an unknown type.
2. **Gather's proposals use the new names.** The chassis-to-type guess (laptop, convertible, tablet) proposes `computer`; the fallback for a host with no usable type is `undefined`; UniFi devices are proposed as `unifi`.
3. **The menu order is data.** `add host` sorts by the type's `order`; a type without `order` sorts last, alphabetically.
4. **The local-machine question still fires** for `computer` (it fired for `laptop`).
5. **Nothing else about types changes**: `proxmox` stays, `other` stays unmanaged, the `managed_by` text for UniFi stays.

---

### Task 1: Rename, merge and order the host types

**Files:**
- Delete: `src/bastet/data/types/unifi-ap.yml`, `unifi-gateway.yml`, `unifi-switch.yml`
- Rename: `laptop.yml` → `computer.yml`, `unknown.yml` → `undefined.yml` (`git mv`)
- Create: `src/bastet/data/types/unifi.yml`
- Modify: the other type files (description, `order`), `src/bastet/core/hosttypes.py` (`order` field and loading), `src/bastet/cli/add.py` (menu order, the `laptop` check and help text), `src/bastet/core/inventory.py` (rename hints), `src/bastet/core/facts.py` (type proposal), `src/bastet/core/hostview.py`, `src/bastet/core/gatherplan.py`, `src/bastet/cli/gather.py` (the `unknown` fallback type), every other `src` file the greps below find, the tests and docs
- Test: `tests/core/test_host_types_order.py` (new), plus the renames in existing tests

**Behaviour:**
- Type files as in the table above; each gets `order: N`. `HostType` gains `order: int = 100`.
- `add host`'s menu is sorted by `(order, name)`; each line shows `name` and the description above.
- `facts.py`: the chassis guess returns `computer` where it returned `laptop`. Keep chassis category names such as the `laptop` category in `hardware.py` as they are (they describe hardware, not host types) unless they feed the host type, in which case use `computer`. Anything in the UniFi gather code that picks `unifi-ap`/`unifi-gateway`/`unifi-switch` picks `unifi`.
- Find every use with: `grep -rIn "laptop\|unifi-ap\|unifi-gateway\|unifi-switch\|\"unknown\"\|'unknown'" src tests docs README.md .claude`; the word "unknown" is also used as plain English, and "laptop" appears in example text and in host examples such as `alice@laptop`: change only host-type uses, and example prose where it names the type.

- [ ] **Step 1: Write the failing tests.** `tests/core/test_host_types_order.py`:

```python
from bastet.core.hosttypes import load_host_types

ORDER = ["computer", "server", "proxmox", "unifi", "vm", "lxc", "vps", "undefined", "other"]


def test_the_shipped_types_are_these_nine_in_this_order():
    types = load_host_types()
    assert sorted(types, key=lambda n: (types[n].order, n)) == ORDER


def test_unifi_is_one_type_and_keeps_the_gateway_networks_fact():
    types = load_host_types()
    assert not {"unifi-ap", "unifi-gateway", "unifi-switch", "laptop", "unknown"} & set(types)
    assert types["unifi"].managed is False and types["unifi"].gather is True
    assert "networks" in types["unifi"].fields
```

Add to the `add host` tests (`tests/cli/test_add.py`, follow its style) one case that the menu lists the types in the order above (the interactive prompt text or the helper that builds it).
- [ ] **Step 2: Run to see them fail.** `uv run pytest tests/core/test_host_types_order.py -q`.
- [ ] **Step 3: Implement** the data, loader, menu, rename map, facts and fallback changes. Rename the type in every test fixture (`type: laptop` → `type: computer` and so on) with a careful search-and-replace limited to host-type uses; update docs and the generated-docs sources (`src/bastet/data/docs/*.md`, `docs/ROADMAP.md`, `docs/specs`, `README.md`, `.claude/skills/run-bastet/SKILL.md`) the same way, leaving historical plans in `docs/plans` untouched.
- [ ] **Step 4: Run** `uv run pytest tests/core tests/cli tests/roles tests/engine -q`, then `scripts/privacy-check`. **Step 5: Commit** with explicit paths (`host types: computer, unifi, undefined; add host order`).
- [ ] **Step 6: Full suite** `uv run pytest -q`.
