# Secrets, Part 2: Rotation and Rekey — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Provisional.** Written before part 1 (`2026-10-03-bastet-secrets-1-core.md`) was built. When part 1 is done, re-read this plan against the real code (module names, the `SecretsContext`, `health.findings`, the note model) and the then-current roles, and update it before executing. No shipped role has a secret option yet, so this plan carries its own test roles. The first real secret-using roles (gitea, postgres, caddy) may change the hook shapes below.

**Goal:**
- **The contract:** every role with a secret defines how it rotates, and a role that doesn't won't load.
- **`bastet secret rotate`** runs a two-step rotation (set "next", verify, promote, or roll back), a direct rotation, or explains a manual one. Across hosts, Bastet carries the stop, change, reconfigure, start and verify sequence between provider and consumers.
- **`bastet secret rekey`** re-encrypts for the current recipients.
- **Keypair generation** (`ssh-keypair`, `wireguard-keypair`).

**Architecture:**
- The role contract gains `rotation:` on secret options and `consumes:` hooks.
- A new `bastet.core.secrets.rotate` builds a rotation plan: an ordered list of steps per host, each a list of engine resources (`Command`s rendered from the contract's templates with `{{ current }}` and `{{ next }}`). `cli/secret.rotate` runs those steps over the same connections `check` and `apply` use.
- The note's state machine is `rotation: ""` → `"in-progress"` (payload has `next`) → `""` (promoted, `rotated` set) or rolled back.

**Tech Stack:** as part 1.

**Spec:** `docs/specs/2026-09-30-bastet-design.md` §15.5–15.7 (rotation, ownership, policy) and §9 (the role contract).

## Global Constraints

- Everything in part 1's constraints.
- A rotation never leaves a service without a working credential and no record of it. At every step, the note holds the value the service currently accepts (current, or next once verified), and a failure rolls back to current.
- `rotate` changes hosts, so it shows its plan and asks like `apply` (not under `-y` when a cross-host outage is involved: it always asks).

## Review Focus

1. **A crash between "provider changed" and "note promoted":** the note holds both values (`next` is in the payload), so a re-run must detect `rotation: in-progress`, check which value the provider accepts, and finish or roll back.
2. **A consumer that fails to verify after the provider changed:** roll back the provider to `current`, restore and restart the consumer, and report both.
3. **Rekey of a secret mid-rotation:** keeps both `value` and `next`.
4. **Template injection:** values are passed to commands on stdin or in the environment, never interpolated into a shell string unquoted. `{{ next }}` renders through `shlex.quote`.

---

### Task 1: The contract: `rotation:` and `consumes:`

**Files:**
- Modify: `src/bastet/roles/contract.py` (`OPTION_KEYS` gains `rotation`, `rotate_every`; role-level `consumes`), `src/bastet/roles/pages.py` (show rotation on role pages and the index)
- Test: `tests/roles/test_role_contract.py`

**Interfaces:**
- **`rotation`:**
  ```yaml
  rotation:
    method: two-step | direct | manual
    set: <template>          # two-step/direct: makes the service accept `next`
    verify: <template>       # two-step: exits 0 when `next` works
    rollback: <template>     # two-step: makes the service accept `current` again (default: set with current)
    instructions: <text>     # manual: what to do by hand
  ```
- **`consumes`** (role level): `{<need>: {stop: [units], configure: <option or template>, start: [units], verify: <template>}}`.
- **Loading rule:** a role whose option has `secret: true` and no `rotation` → `BastetError("role gitea: admin_password is secret but has no rotation (spec 15.6)")`. A role with `needs:` on a credential-providing role and no `consumes:` entry → the same kind of error.

- [ ] Failing tests (missing rotation refuses; each method validates its required keys; pages render rotation) → implement → `uv run pytest -q` → commit `Role contract: rotation and consumes for secret options`.

### Task 2: The rotation plan and the note state machine

**Files:**
- Create: `src/bastet/core/secrets/rotate.py`
- Test: `tests/core/secrets/test_rotate.py`

**Interfaces:**
- **`plan_rotation(ctx, sp) -> RotationPlan(steps: list[Step(host, label, resources)], method)`.** For a provider secret with consumers, the step order is:
  1. each consumer's `stop`;
  2. the provider's `set` (with `next`);
  3. each consumer's `configure` (with `next`) and `start`;
  4. each consumer's `verify`;
  5. the provider's `verify`.

  Rollback steps are the mirror image with `current`.
- **`begin(note, next_value)`** re-seals with `next_value` and sets `rotation: in-progress`. **`promote(note)`** seals `next` as the value, clears `rotation` and sets `rotated` to now. **`abandon(note)`** drops `next` and clears `rotation`. Each commits.
- **Recovery:** `resume(ctx, sp)` handles a note found `in-progress`. It verifies `next` against the provider; if that works it finishes the remaining consumer steps, otherwise it rolls back.

- [ ] Failing tests:
  - plan order for a bundled secret, a same-host provider, and a cross-host provider with two consumers;
  - the state machine round trip;
  - `resume` when the provider has next, and when it still has current (both with fake runners);
  - template values are quoted.

  → implement → run → commit `Secrets: rotation plans and the in-progress state`.

### Task 3: `bastet secret rotate`

**Files:**
- Modify: `src/bastet/cli/secret.py`
- Test: `tests/cli/test_secret_rotate.py`

**Behaviour:**
- **`bastet secret rotate <host> <role> <option>`.** Shows the plan (hosts, steps, "gitea on git1 will be stopped for the change"), then asks.
  - **two-step:** `begin`, run the steps, `promote`. On a failure, run the rollback steps, `abandon`, and report.
  - **direct:** run `set`, then promote straight away.
  - **manual:** print the instructions; `bastet secret set` records the new value and fills `rotated`.
- **`bastet secret rotate`** with no words: a numbered list of secrets that are due (from part 1's policy findings).
- **Generated next values** use the contract's `generate`; chosen and issued secrets prompt for the new value.

- [ ] Failing tests with the `box` local host and test roles (a direct one whose `set` writes a file; a two-step one whose `verify` reads it back; a failing verify that must roll back; a cross-host pair with fake runners recording the step order) → implement → run → commit `bastet secret rotate`.

### Task 4: `bastet secret rekey` and keypairs

**Files:**
- Modify: `src/bastet/cli/secret.py`, `src/bastet/core/secrets/store.py`
- Test: `tests/cli/test_secret_rekey.py`, `tests/core/secrets/test_crypto.py`

**Behaviour:**
- **`rekey`** re-seals every note reported `needs_reencryption` (or all, if asked), keeping `value` and `next`. One commit.
- **`generate.kind`:**
  - `ssh-keypair` (ed25519, via `ssh-keygen` to a temp dir): the private half is the secret, and the public half is published as a fact on the host note (`<option>_public`);
  - `wireguard-keypair` (`wg genkey`/`wg pubkey` when `wg` exists, else a pure-Python X25519 key via `cryptography`, if it's added): the same.
- **Keypair rotation** uses the two-step overlap: deploy the new public key alongside the old, verify, remove the old one.

- [ ] Failing tests → implement → run → commit `bastet secret rekey; ssh and wireguard keypairs`.

---

## Open before execution (decide when part 1 is done)

- Whether hook templates run as `Command` resources or as a new `RotationStep` resource with its own read/verify.
- How a consumer's `configure` maps onto its role's own builder (re-render its config file with `next`), rather than a free template.
- Whether `rotate` should also run during `apply` when a secret is due and the role's method is `direct` (spec says rotation is explicit; keep it explicit unless that changes).
