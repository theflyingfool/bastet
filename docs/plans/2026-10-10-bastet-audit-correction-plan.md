# Audit correction plan

Two outside audits of the code, reconciled by root cause. This is a plan of small repair increments, not a design: each
increment gets its own spec or plan before code changes. Nothing here is implemented yet.

- **Audit 1** (`audit_bundle_1`): pinned to an old commit (`1b96abf`), before the host-note split follow-ups, the roles
  slice and the new run order. Several findings were already gone by the time it was read.
- **Audit 2** (`audit_bundle_2`): pinned to `5a2c36f`, the current `main`. Findings F01-F16, UX-01-UX-18 (aliases kept below).
- Where I checked a claim against the current code, the table says so. "Not checked" means plausible from the report's
  own reproduction, but I did not re-read the code.

## 0. State when this plan was written

- `main` is at `5a2c36f`: the roles first slice (phase engine, Markdown loader and generic builder, pacman and apt as
  Markdown) is merged and pushed. The full unit suite passes.
- Container contract tests were run on this machine: 28 of 31 pass. The three failures are the AUR (a regression from
  the new run order; the AUR is now being cut, C22), `arch_updates_reported` (network, fails before our changes too) and
  one intermittent `systemd_contract` run (C21). They only start under pytest with a temporary podman storage config,
  because `tests/conftest.py` redirects `XDG_DATA_HOME` (C21).
- The roles hard-testing checklist (real `bastet run -c` against the Arch inventory, legacy roles in the new order,
  failure cases, Ctrl-C and `-vv`) is **not done**; it is the owner's, on real hosts. The final whole-branch review of the
  slice was skipped on request. Increment 8 re-runs the checklist after increments 1 to 3.
- Until increment 1 lands, do not run `bastet run` in apply mode against a real `pacman.conf` (check mode is fine).
- Both `audit_bundle_*` directories are untracked and will be deleted by the owner; this plan is committed only after the
  owner has read it.
- Rulings already taken during the slice: the pacman role keeps `provides: [package-manager]` (otherwise its edits run
  after packages), so the Task 1 golden helper expects it; commit trailers use the current session URL.

## 1. Where I disagree, and why

| Claim | Verdict | Reason |
|---|---|---|
| A1-1: dry-run `run -c` mutates the repo and commits (Critical) | Agree it should not, disagree it is a defect-by-accident | Check writes security notes and run notes and makes one commit **by design** (`cli/run.py` phase 7), and the help says "Changes nothing". Owner decision (section 4): check writes nothing to the vault or git by default. |
| A1-7: dead `bastet gather`/`apply` guidance in `src/` | Already fixed | No such strings remain in `src/` outside docs. |
| A1-9: failing test `test_doctor_clean_inventory_reports_nothing` | Already fixed | Full suite is green on `main` apart from a guard we fixed in the roles slice. |
| A1-6: `init` leaves no git identity and `add host` crashes | Mostly fixed | `gitrepo.py` now raises a friendly message with the `git config` lines. Whether `init` should set a local identity is a design choice, not a crash. |
| A1-2 and the AUR sudoers: "dormant prototype" | Disagree on "dormant"; moot now | `_aur_bootstrap` is live code with a contract test, not dormant. The owner has decided to cut the AUR (C22), which removes the sudoers risk. |
| A1-3: symlink on `.bastet-tmp` can chown `/etc/shadow` | Agree on the bug, disagree on the scenario | Needs a user-writable parent directory (for example `~/.ssh`). A2-F01 states the real boundary correctly. |
| A1-5: non-interactive `secret unlock` is a High finding | Partly | It is documented behaviour ("run `secret lock` when done"). The real defects are the file mode (A2-F10), the misleading summary text (A2-UX-15) and missing SIGTERM/SIGHUP relock. |
| A1-13: one thread per host | Agree, low | Threads wait on events; harmless at homelab scale. Cleanup only. |
| A1-14: monochrome diffs | Folded into A2-UX-12 | Layout and colour policy, handled once. |
| A1-15 (prelude monkeypatching in tests), A1-16/17 (audit tooling scripts) | Not our defects | Tests: hygiene, low. The audit scripts live in the bundle, not in this repo. |
| A1-8 hardware facts missing in `show`; dead `file_versions`/`file_log`/`file_at` | Confirmed, minor | Both still present (`show.py`, `gitrepo.py`). |
| A2-F12 reload after unit ops | Agree, and partly ours | The new "triggers once at the end" rule moved `daemon-reload` after the systemd slot. Old per-batch triggers ran it earlier for ssh. We introduced this regression. |
| A2-F03 INI edits cross sections | Agree, **most urgent** | Confirmed by reading the builder. It affects the pacman role we just shipped, on a real `pacman.conf` that has repository sections with their own `SigLevel`. |
| A2 "31 contract tests skipped" | Superseded | I ran them: 28 pass; 3 fail (AUR, which is our known regression; `arch_updates_reported`, which fails the same way before our changes; one flaky systemd test). |

Confirmed by me against current code: F03, F07, F08, F10, F11 (by ordering), F12, F13, F14, UX-13, A1 hardware `show`,
A1 dead git methods. Not re-checked: F02, F04, F05, F06, F09, F16, UX-01 to UX-12, UX-14 to UX-18.

## 2. Combined findings (root cause, aliases)

| Combined ID | Aliases | Root cause | Priority |
|---|---|---|---|
| C1 | A2-F03, A2-F15 | The INI editor treats a section as an insertion hint, not a boundary; accepted metadata (`validate`, `mode`, `owner`) is silently dropped; list/value text can carry newlines past validation (pacman) | P1 |
| C2 | A2-F01, A1-3 | Remote writes use a predictable temp name, follow symlinks, and expose content at the wrong mode before the final chmod (File and AuthorizedKey) | P1 |
| C3 | A2-F02 | Apply can report success while a resource that started compliant was invalidated by another | P1 |
| C4 | A2-F04, A1-11 | Inventory errors print but do not gate apply; a broken host is silently skipped or applied wrongly | P1 |
| C5 | A2-F05 | A selected node that fails drops out of the dependency graph, so its guest still applies | P1 |
| C6 | A2-F06 | Source-note writes use a stale "before" snapshot after a later pull or human edit | P1 |
| C7 | A2-F09, A1-4 | Literal values of `secret` options are not marked sensitive, so they reach command records | P1 |
| C8 | A2-F07 | Pre-commit guard matches substrings, not a whole sealed note | P1 |
| C9 | A2-F08 | Sync safety check is a substring match; unreadable config counts as safe | P1 |
| C10 | A2-F10, A2-UX-15, A1-5, A1-12 | Unlock leaves public file modes, headless wording is wrong, no relock on SIGTERM/SIGHUP | P2 |
| C11 | A2-F11 | Group membership reconciled before new users exist | P2 |
| C12 | A2-F12 | `daemon-reload` runs after unit operations and commands (partly caused by the end-of-run trigger rule) | P2 |
| C13 | A2-F13 | `_node_of_map` shadows `out`; cycle warning raises AttributeError | P2, quick |
| C14 | A2-F14 | Package option strings reach the shell unquoted | P2, quick |
| C15 | A2-F16, A2-UX-01, A2-UX-10, A2-UX-16 | No single outcome model: terminal, JSON, run note, replay and exit code disagree | P2, large |
| C16 | A2-UX-02, UX-08, UX-06, A1-1 | Scope and mode contract: check must write nothing to the vault or git; broad selectors must keep `gather: false`; false "No hosts yet"; help text | P2 |
| C17 | A2-UX-03, UX-04, UX-05 | Input validation: bad IP accepted, invalid host names accepted and failing later (names must be valid hostnames), invalid apply answers silently decline | P2 |
| C18 | A2-UX-07, UX-09, UX-11, UX-12, UX-14, UX-17, UX-18 | Readiness summary, progress, run-ordering/provenance, narrow layout, clipboard honesty, dashboard classification, CSS scoping | P2/P3 |
| C19 | A2-UX-13 | `doctor` rejects Markdown roles (`no role.yml`) | P2, quick |
| C20 | A1-8, dead git methods, A1-13, README/doc drift (nine roles, links), `cssclasses`; from the slice: `as: value` on a list option writes a Python list; the roles-table line about `role.yml` and Python builders omits pacman and apt | Small cleanups | P3 |
| C21 | `arch_updates_reported` needs mirror access the throwaway container does not have (fails the same way before our changes); `systemd_contract` failed once in a full run and passed on three reruns (failure text not captured yet); `conftest` sets `XDG_DATA_HOME` so podman cannot start under pytest; UI tests depend on `NO_COLOR`/`TERM` | Test and release hygiene | P2 |
| C22 | AUR (owner decision: cut) | Remove the `aur` package option, `_aur_bootstrap`, its sudoers file, the contract test, docs and roadmap item 8. This also ends the regression and the root-equivalent sudoers rule | P2 |
| C23 | New (owner request) | No way to persist an exclusion in the host note (the host.md counterpart of `--exclude`, used to mark a host as temporarily known offline). Today only `gather: false` (gather only, and a named host overrides it), `managed: false` (type level only) and `--exclude` (per invocation) exist | P2, small feature |

## 3. Increments (in order)

Each increment ends green on the unit suite and on the contract tests where it touches hosts. Do not convert more roles
until increments 1 to 3 are done.

1. **Make the shipped roles safe (C1, C13, C14, C19).** Detailed plan:
   `docs/plans/2026-10-10-audit-inc-1-shared-roles-safe.md`. `edit: ini` becomes one section-scoped `Settings` resource
   per section: a Bastet-managed block right after the section header, with the originals of every managed key commented
   out (`#bastet: `) so off and empty values work and no repository section is ever touched (F03). The pacman role uses
   it, with an optional one-time backup of the original. Also: contract checks (`validate` honoured, `mode`/`owner`/`group`
   on edits and `before` with `after` refused, `edit: ini` options need a section), line breaks in any value refused,
   cycle-warning crash and package-option quoting fixed, `doctor` lints Markdown roles. *Proof:* unit tests for the
   resource, an Arch contract test, and the owner's `run -c` diff on a real host. **Until the owner has read that diff,
   do not run `bastet run` in apply mode against a real `pacman.conf`.**
2. **Safe mutation (C2, C3, C6, C10 file modes).** One safe remote-write primitive (unpredictable, exclusive, private
   temp file in the target directory; validate before replace; shared with authorized keys). Detect overlapping
   whole-file and edit intents at plan time and re-verify affected resources after any mutation. Compare the note
   bytes to the change's "before" immediately before writing. Unlock writes private files. *Proof:* planted-symlink,
   transient-mode, stale-write and "apply then check is clean" regressions.
3. **Gate execution on a trustworthy plan (C4, C5, C15 core, C23).** Selected hosts with fatal inventory errors never
   connect; selected failed nodes block their guests with a named reason; one outcome model feeds exit code, terminal,
   JSON, run note and replay. Add a host-note property equivalent to `--exclude` (name and an optional reason or date to be settled in a short
   spec first) so the exclusion lives in the host's own note, and `--exclude` stays as the per-invocation form of the
   same thing. Gather, check and run all skip such a host with a visible reason, so an expected-down host is neither
   contacted nor counted as a failure. *Proof:* a scenario matrix (invalid inventory, node plan failure, node connection
   failure, all-unreachable gather, failed trigger) agrees across surfaces.
4. **Secrets lifecycle (C7, C8, C9, C10 rest).** Literal secret values marked sensitive and redacted in every sink;
   `User` hides password-hash commands by itself; strict sealed-note hook (whole body, fail closed); Sync check reads
   the real exclusion field and refuses when unsure; relock on SIGTERM/SIGHUP; honest unlock wording. *Proof:*
   literal and referenced values absent from all sinks; hook rejects extra plaintext next to an armor marker.
5. **Fresh-host mechanics (C11, C12, C21, C22).** Cut the AUR first (it is the one failing contract test we caused). Groups, then users, then membership; one deduplicated reload barrier before
   dependent unit operations and commands; fix the test harness so contract tests run under pytest, make the flaky
   and network-bound ones deterministic or marked, make the UI tests hermetic. *Proof:* fresh and pre-existing Debian
   and Arch contract runs, both root and `bastet` user.
6. **Contract and UX (C16, C17, C18, rest of C15).** Write the mode contract once and generate help and docs from it
   (check writes nothing to the vault or git; the local run record stays; `log note RUN` keeps a chosen check);
   broad selectors keep `gather: false`; host names must be valid hostnames, with `doctor` flagging existing ones that
   are not;
   scope summary and truthful empty states; shared field validation in the wizard; clearer apply prompt; readiness
   summary; run ordering and recorded options; layout for narrow terminals; clipboard honesty; dashboard classification.
   Split into several small changes by area; native Obsidian and accessibility checks stay a separate, manual item.
7. **Cleanup and docs (C20).** Dead git methods, hardware facts in `show`, README and doc drift, the as-built versus
   prospective wording in the roles spec (including its section 5 and roadmap step 2, which list `users`, `files`,
   `packages` and `systemd` as roles to convert although they stay Python), thread pool.
8. **Resume role conversion.** Roles still to convert, one at a time and each as straight Markdown: ssh, base, harden,
   proxmox. `users`, `files`, `packages` and `systemd` are special roles: they expose the building blocks that nearly
   every other role uses, so they stay Python (with their `role.yml` contracts and `BUILDERS` entries). `ORDER` is
   transitional: slots already order the blocks, and what remains of it (order within a slot) goes once the four
   convertible roles are Markdown. Nothing in this plan polishes it. After 1 to 3, re-run the roles hard-testing
   checklist, then convert one role (ssh is the natural next one) on the hardened blocks.

## 4. Owner decisions

All six are answered.

1. **Check mode:** writes nothing to the vault or git by default. The local run record (outside the vault) stays, and
   a check can be kept on request. The security-report note moves to gather and apply.
2. **Selectors versus `gather: false`:** broad selectors (`@lab`, types, globs) respect the opt-out; only an exact name
   overrides it, and the output says so before connecting.
3. **Host names:** must be valid hostnames. Existing names that are not get a `doctor` warning and an explicit
   migration, not a silent rename.
4. **Non-interactive unlock:** better wording. File modes and relock-on-signal are still fixed (they are not wording).
5. **Contract failures:** the AUR is cut (C22). `arch_updates_reported` is made independent of the network (as the AUR
   test already does) or skipped without it. The systemd test is looped to capture the failure, then fixed or marked.

6. **All-unreachable gather exit policy:** exit nonzero when every attempted host failed (partial stays 0), plus a strict
   flag for any failure; the recorded status is always `ok`, `partial` or `failed`. The host-note exclusion (C23) keeps
   expected-down hosts out of the count.

## 5. Deferred or needs evidence we do not have

- Native Obsidian, keyboard, screen-reader, theme and mobile checks (A2 section 11.5).
- The intermittent "unfinished" run record (A2 11.7): root cause unknown, not counted as a defect.
- Real-host runs: ssh, harden, systemd restart, proxmox, Ctrl-C and `-vv` (our hard-testing checklist items 2 to 6).
- CI, a license file and branch protection (A2 section 6): decide after increment 5.
- Non-systemd and Alpine support (A1-8): outside the declared support matrix.
- Two building blocks that are ideas only, not started: power control (design still open) and a possible `fetch` block
  (curl/wget/git/send from the command host; audit 2 suggests pinned identities and checksums, and safe extraction, when
  a concrete role first needs it). Neither is in the roadmap's blocks table beyond power control.
- Open design question (owner's view, not decided): repositories may belong to the package manager's own role rather than
  the cross-distro `packages` block, since a repository is manager-specific data and the manager roles are already aimed
  per distro. That would give `pacman.conf` a single owning role and move the `repositories` option from the `packages`
  role to the manager roles (the `Repository` resource stays a block). Needs its own design: option shape, key handling
  for third-party repositories, migration of existing host notes. Decide with the `packages` role conversion or after
  increment 2 (overlap detection).
