---
name: run-bastet
description: Run, try out, smoke-test or drive the bastet CLI (init, add host, add role, run -c/-g, show, doctor, refresh) end to end in a throwaway sandbox inventory, or call its Python internals directly. Use when asked to run bastet, start it, try a command, reproduce a CLI bug, check output, or test a change against a real inventory without touching the user's own.
---

# Running Bastet

Bastet is a Python CLI (Typer) that keeps a homelab inventory as Markdown notes in a git repo, an Obsidian
vault. Agents drive it with **`.claude/skills/run-bastet/smoke.sh`**. It runs the real CLI against a fresh
sandbox (its own config, data dir and inventory) and checks each step's exit code and output. For code-level
changes, call the internals directly (below). All paths here are relative to the repo root (`~/Repos/bastet`).

## Prerequisites

`uv`, `git` and `ssh-keygen` on PATH (`bastet init` generates Bastet's SSH key with `ssh-keygen`). Python
comes through uv (`requires-python >=3.12`); the first `uv run` builds the venv.

## Run (agent path): the smoke driver

```bash
export TMPDIR=$(mktemp -d)        # any writable folder; the sandbox is $TMPDIR/bastet-sandbox.XXXX
.claude/skills/run-bastet/smoke.sh
```

**What the flow does:**
1. `init -y`;
2. `add host` for an `other` device and a VPS;
3. `show`, `show vps1`, `show @other`;
4. `add role packages --to lab`;
5. `run -c` (the `other` host is skipped; the VPS has no host key yet);
6. `run -g` against an address nothing answers on;
7. `doctor`;
8. selector errors (`@nope`, `"zz-*"`);
9. `refresh`, then checks generated notes exist (`_bastet/docs/`, `_bastet/groups/`, `_templates/`, facts notes);
10. prints the git log (one commit per command).

It ends with `SMOKE OK (sandbox kept at …)` and exits non-zero on the first step that misbehaves.

**Run your own commands in that sandbox.** `shell` prints the environment for it:

```bash
S=$(ls -d $TMPDIR/bastet-sandbox.*)
eval "$(SANDBOX=$S .claude/skills/run-bastet/smoke.sh shell)"
cd $S/lab && uv run --quiet --project ~/Repos/bastet bastet show
```

## Direct invocation (most code changes need only this)

Import the core and call it against an inventory folder; no CLI and no git writes:

```bash
uv run --quiet python - /path/to/sandbox/lab <<'EOF'
import sys
from pathlib import Path
from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from bastet.core.selectors import select_hosts
from bastet.core.hostview import host_data
types = load_host_types()
inv = load_inventory(Path(sys.argv[1]), types)
for d in select_hosts(inv, types, ["@lab"], exclude=[]):
    print(d.name, host_data(inv, d, types).get("type"), inv.facts_for(d.name) or "(no facts yet)")
EOF
```

## Test

Run only the files you touched (the user runs the full suite):

```bash
uv run pytest -q tests/core/test_inventory.py
```

The full suite is `uv run pytest -q` (about 1,250 tests, about 5 minutes). Container contract tests are opt-in
(`BASTET_CONTRACT=1`, need podman); don't run them unless asked.

## Run (human path)

`bastet <command>` from anywhere uses `~/.config/bastet/bastet.yml` and **the user's real inventory**. Every
command commits to it, and pushes when it has a remote. Never use it for experiments.

## Gotchas

- **Always sandbox.** Without `BASTET_CONFIG`, `XDG_DATA_HOME` and `XDG_RUNTIME_DIR`, the CLI works on the user's real
  config and inventory (wherever `~/.config/bastet/bastet.yml` points) and commits to them. The driver sets all three.
- **No real hosts are reachable from an agent session.** Anything that connects ends in a per-host message, not
  a run:
  - `run -c` on a never-gathered host says "no confirmed host key yet";
  - `run -g` on a dead address says "nothing answered on port 22 within 10s" **and still exits 0**. A failed
    host doesn't fail a gather.
- **Some messages still name removed commands:** "run `bastet gather`", "`bastet apply` runs an audit…", and the
  `cli/run.py` docstring. They're in `cli/init.py`, `cli/run.py`, `roles/system.py` and `engine/security.py`. The
  real commands are `bastet run -g` and `bastet run`. To find them:
  `grep -rn 'bastet gather\|bastet apply\|bastet check' src/bastet`.
- **`init` makes two commits** (`bastet init`, then `refresh: N generated notes`). Every other command makes one
  (`add host vps1 (+4 generated)`).
- **"Refreshed N generated notes" can print twice for one command.** The second pass folds the dashboard's
  "recent changes" into the same commit, so it's not a second commit.
- **Not a terminal** (the driver, a pipe): `init` skips the wizard and the recovery-key/recipients step, and
  `next:` hints aren't printed. Use `-y` to skip questions everywhere.
- **Selectors:** `@other`, `@vps` and `@lab` work. A bare `proxmox` (no `@`) is looked up as a host name and errors.
  Groups and types listed by `show` include Bastet's generated type and OS groups.
- **On this machine, `grep` is `ugrep`:** `--include=*.py` fails with "no matches found" (zsh globbing).
  Pipe through `grep '\.py:'` instead.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `FAIL: bastet run -g vps1 -y exited 0 (wanted 1)` | Expected; a gather doesn't fail on one unreachable host. The driver now expects 0 |
| `run -c` → "no confirmed host key yet; run `bastet gather`…" | Use `bastet run -g <host>` (the message's command name is stale) |
| `rm -rf` on the sandbox is refused by the agent permission settings | Don't delete; make a new sandbox (`mktemp -d`) each run |
