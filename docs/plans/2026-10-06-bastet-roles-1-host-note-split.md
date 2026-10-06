# Roles Redesign 1: Host-Note Split — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- Gathered facts move out of `hosts/<host>.md` into `_bastet/facts/<host>.md`, a note only Bastet writes.
- No automatic command writes a host note again.
- Fact keys left on old host notes are ignored and reported.
- Everything that reads facts goes through one host view.
- The security note moves to `_bastet/reports/<host>.md`.

**Architecture:**
- **A new `bastet.core.factsnote` module** owns the facts note: path, render, parse.
- **The inventory loads facts notes** and exposes `facts_for(name)`.
- **A new `bastet.core.hostview.host_data(inv, doc)` returns the one dict everyone reads:**
  - the facts note's values;
  - overlaid with the host note's *declared* keys (those whose nature in the host type is `desired` or `yours`, plus identity keys like `type`, `groups`, `runs_on`, `location`, `connection`, `gather`, `address`, `ip`, `state`).

  Fact-nature keys on the host note are ignored.
- **Gather builds a facts-note change** in place of a host-note change.
- **Readers switch from `doc.data` to `host_data`:** OS detection, roles' `HostInfo`, cabling, summaries and the dashboard, `show`, connect and host-key pinning.

**Tech Stack:** as before (Python ≥3.12, uv, Typer, pytest).

**Spec:** `docs/specs/2026-10-06-bastet-roles-design.md` §2, §2.1; reports-note location from §8.3. Main spec §5.3 and §7 for today's behaviour.

**Roadmap:** `docs/plans/2026-10-06-bastet-roles-roadmap.md`, subplan 1.

## Global Constraints

- **Unit tests:**
  - never touch your inventory, `~/.config/bastet`, `~/.local/share/bastet`, `~/.ssh`, the real `~/.cache` or `$XDG_RUNTIME_DIR`;
  - no network;
  - `tmp_path` only;
  - placeholder data only.
- **Automatic commands never write `hosts/*.md`:** `gather`, `refresh`, `check`, `apply`, `map`, `secret`, and `init`'s host-key pin. Commands where you explicitly create or edit your own notes may still write them, always showing a diff first: `add host`, and `add role` / `add secret` inserting their page section.
- **No migration tool.** Old fact keys on host notes are reported as problems and ignored; you remove them by hand.
- **Hardware notes are out of scope.** They keep today's behaviour, including attribution and `--take`.
- **Folder names never start with a dot.**
- **Commit trailer:**
  ```
  Co-Authored-By: <model> <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01SgYSJBjMmf52EmoGk4d4zN
  ```
  Stage by name, never `git commit -a`.
- **Each task:** failing tests first and seen failing, then implement, then the full `uv run pytest -q` green.

## Review Focus

1. **A stale fact on a host note overriding a fresh one.** An old `os: Debian 12` left on `hosts/x.md` must not beat the facts note's `Debian 13`. `host_data` ignores fact-nature keys from the host note, and the problem line says to remove them.
2. **Host keys.** `ssh_host_key` now lives in the facts note. Every path must read and write it there:
   - first contact in gather;
   - `--accept-new-hostkey`;
   - connect in check and apply;
   - `init`'s local pin.

   A key recorded only on an old host note must still be honoured during the transition, read as a fallback and reported, never silently re-trusted.
3. **A host with no facts note yet** (never gathered) must behave as today's never-gathered host. That covers OS detection returning None, roles that need facts, summaries, the dashboard, and `show`.
4. **Gather never writes the host note,** not even the summary embed, the hardware section, `gather: true`, `hostname` or a type proposal. Those become notes (info lines) or move to `add host`.
5. **UniFi hosts and guests** get facts notes too. Their extra keys (`mac`, `vmid`, `bridges`…) follow the same nature rules.

---

### Task 1: The facts note and the host view

**Files:**
- Create `src/bastet/core/factsnote.py`, `src/bastet/core/hostview.py`.
- Modify `src/bastet/core/inventory.py` (recognise `bastet: facts`; `facts_for(name) -> dict`).
- Test: `tests/core/test_factsnote.py`, `tests/core/test_hostview.py`, `tests/core/test_inventory.py`.

**Interfaces (produces):**
```python
FACTS_DIR = "_bastet/facts"
def facts_path(root: Path, host: str) -> Path                      # root / FACTS_DIR / f"{host}.md"
def render_facts(host: str, facts: dict, gathered: str) -> str     # full note text
# frontmatter: bastet: facts, host: "[[<host>]]", gathered: <ISO time>, cssclasses: [bastet-facts], then the facts
# keys in a stable order (the order extract() yields, then alphabetical for the rest);
# body: "# <host> facts", a line "Written by Bastet on every gather; don't edit. Your settings live in [[<host>]].",
# then the summary embed.
def facts_change(root: Path, host: str, facts: dict, gathered: str) -> Change | None
# None when only `gathered` would differ (no commit on every gather when nothing changed)

class Inventory: ...
    def facts_for(self, name: str) -> dict        # {} when the host has no facts note

IDENTITY_KEYS = ("type", "groups", "runs_on", "location", "connection", "gather", "address", "ip", "state", "hostname")
def host_data(inv: Inventory, doc: Document, types: dict[str, HostType]) -> dict
def stale_fact_keys(doc: Document, types: dict[str, HostType]) -> list[str]
```

**Behaviour:**
- **The facts note is a normal inventory note** of kind `facts`. The inventory indexes it by its `host:` link target. A facts note whose host doesn't exist is an inventory warning ("_bastet/facts/x.md: no host named x").
- **`host_data` starts from `facts_for(doc.name)`,** then overlays every host-note key that isn't fact-nature for that host's type. Identity keys are never fact-nature.
- **Unknown types** use the `unknown` type's fields.
- **A host-note key the type calls `fact`** is never overlaid; `stale_fact_keys` lists them.
- **`ssh_host_key` transition:** if the facts note has none but the host note has one, `host_data` includes the host note's value, and `stale_fact_keys` still lists it.

**Tests:**
- render/parse round-trip;
- `facts_change` returns None when only `gathered` changed;
- the inventory indexes facts by host;
- an orphan facts note gives a warning;
- `host_data`:
  - facts plus declared, declared winning for desired/yours keys;
  - a stale `os` on the host note ignored, with the facts note's `os` winning;
  - the `ssh_host_key` fallback;
  - no facts note → only declared keys.

### Task 2: Stale fact keys are reported

**Files:** `src/bastet/core/inventory.py` (or wherever problems are assembled for `print_problems`), `tests/core/test_inventory.py`, `tests/cli/test_show.py`.

**Behaviour:**
- **Each host note with stale fact keys** produces one warning, listed with the existing problems by `print_problems` and `show`'s Problems section:
  `hosts/x.md: os, kernel, cpu are gathered facts; they now live in _bastet/facts/x.md (remove them from this note)`.
- **Warning, not error:** the keys are ignored, so nothing breaks.

**Tests:**
- the warning text and line;
- no warning for declared keys;
- one line per host, listing all its stale keys.

### Task 3: Gather writes facts notes, never host notes

**Files:**
- `src/bastet/core/gatherplan.py`: replace the host-note path of `plan_update` with `plan_facts`. Keep `merge_facts` for hardware.
- `src/bastet/cli/gather.py`.
- Tests: `tests/core/test_gatherplan.py`, `tests/cli/test_gather.py`, `tests/cli/test_gather_parallel.py`.

**Interfaces (produces):**
```python
def plan_facts(doc: Document, ex: Extracted, host_type: HostType, inv: Inventory, *,
               hostkey: str | None, gathered: str, types: dict[str, HostType]) -> HostUpdate
# HostUpdate.change targets the facts note (or None); notes as before
```

**Behaviour:**
- **The observed facts all go to the facts note,** including:
  - `ssh_host_key`;
  - observed values of *desired* fields (e.g. a guest's `cores`, kept as the observed value);
  - `hostname`;
  - `bastet_tools`.

  The `dhcp` filtering of `gateway` and `addresses` stays.
- **No attribution or `--take` for host facts:** the facts note is Bastet's, so it's simply replaced with what was observed. `--take` keeps working for hardware. Passing a key that is only a host fact prints `--take <key>: host facts are always taken now; nothing to do`.
- **Drift notes stay:** a desired or yours field declared on the host note that differs from the observed value is an info note, as today.
- **A type proposal** becomes a note only ("this host looks like a proxmox-node; set type: proxmox-node"), never a write.
- **Removed:** `gather: true` and `hostname` defaults, the summary-embed insert, and the hardware-section insert into host notes. A host page missing the summary embed gets an info note: `hosts/x.md has no summary embed; add ![[x summary]] (bastet add host does this for new hosts)`.
- **Host keys:**
  - `_pin` reads the recorded key through `host_data` (facts note first, the host-note fallback second);
  - a changed key still needs `--accept-new-hostkey`;
  - the accepted key goes into the facts note.
- **`bastet_tools`** comes from `host_data` and is written to the facts note.
- **One commit** holds the facts notes, hardware changes, links and guests, as today.

**Tests:**
- **The guard:** after a gather of a fixture inventory with two hosts, every `hosts/*.md` file is byte-identical and `_bastet/facts/<h>.md` exists with the expected keys.
- A second identical gather produces no change.
- First contact writes the key into the facts note.
- A changed key without the flag is refused; with the flag it's written to the facts note.
- A drift note for a desired field.
- The type-proposal note.
- The missing-summary-embed note.
- UniFi and guest fixtures produce facts notes.
- Existing gather tests adapt from host-note assertions to facts-note assertions; list them in the report.

### Task 4: Readers use the host view

**Files:**
- `src/bastet/core/osinfo.py` (callers pass `host_data`).
- `src/bastet/roles/builtin.py` (`HostInfo.data` = `host_data`), `src/bastet/roles/system.py`, `src/bastet/roles/resolve.py` (group `match:` reads OS and type through `host_data`).
- `src/bastet/core/cabling.py`, `src/bastet/core/render.py` (summaries, dashboard tables, maps).
- `src/bastet/cli/show.py`, `src/bastet/cli/run.py` (`connect`), `src/bastet/cli/init.py` (`_confirm_local_hostkey` reads the facts note and writes the pin with `facts_change`, committed as `init: pin <host>'s host key`).
- Tests across `tests/core`, `tests/roles`, `tests/cli`.

**Behaviour:**
- Every read of a gathered key goes through `host_data`. Afterwards, `grep -rn 'data.get("\(os\|kernel\|cpu\|ram\|interfaces\|ssh_host_key\|bastet_tools\|pools\|virtualization\|chassis\|storage\|mac\)"' src/` lists no direct host-note reads outside `hostview.py` and the hardware code.
- **A host with no facts note** behaves like today's never-gathered host.

**Tests:**
- Microcode and the Debian-like choice, from facts-note fixtures with the host note carrying a stale wrong `os`. The facts note must win.
- Cabling ports from facts.
- The dashboard OS column from facts.
- `show` lists OS from facts.
- `connect` uses the facts-note key, plus the fallback.
- `init` pins into the facts note and leaves the host note unchanged.
- A group `match: {os: debian}` matching from facts.

### Task 5: Reports note location and new host pages

**Files:**
- `src/bastet/core/security_note.py` (`SECURITY_DIR` → `_bastet/reports`, file `<host>.md`).
- `src/bastet/core/scaffold.py` and `src/bastet/cli/add.py` (`add host` writes the page with the summary embed, the hardware section for physical types, and a "Reports" embed `![[_bastet/reports/<host>]]`).
- `src/bastet/core/render.py` (summary links to the facts note).
- The guide note in `src/bastet/data/guide/`.
- Tests: `tests/cli/test_check_apply.py`, `tests/cli/test_add.py`, `tests/core/test_scaffold.py`.

**Behaviour:**
- **The security note moves** to `_bastet/reports/<host>.md`, with the same content and the same "no commit when only the time changed" rule. An old note at `_bastet/security/<host> security.md` is left alone and isn't read.
- **New host pages from `add host`** carry the embeds gather used to add, so gather never needs to.
- **Each generated summary** ends with `Facts: [[_bastet/facts/<host>|gathered facts]]`.
- **The guide note** explains the split in two sentences: your notes hold what you decide; `_bastet/facts/` holds what Bastet saw.

**Tests:**
- The reports-note path and content.
- No commit on a time-only change.
- `add host` page text for a physical and a virtual type.
- The summary's facts link.

### Task 6: README and spec cross-check

**Files:**
- `README.md` (bastet repo): where facts live; old host notes get a "remove these keys" warning; `--take` is for hardware only.
- Vault: `docs/plans/2026-10-06-bastet-roles-roadmap.md` (mark subplan 1 ☑ when merged). Stage by name, **never `git commit -a`**.

**Behaviour:** the docs only; no code. The README "gather" row and its notes match the new behaviour.

---

## After this plan

Subplan 2 (role format and library) is written in full against the code as it stands after this plan merges.
