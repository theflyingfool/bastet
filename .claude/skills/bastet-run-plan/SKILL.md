---
name: bastet-run-plan
description: Use when executing a Bastet implementation plan from docs/plans/ — sets up the branch and ledger, dispatches one implementer per task with Bastet's rules baked in, reviews each task, runs the final review, updates docs/ROADMAP.md, and asks before merging or pushing. Use together with superpowers:subagent-driven-development (this skill supplies the Bastet-specific parts).
---

# Running a Bastet plan

Bastet-specific layer on top of `superpowers:subagent-driven-development` (load that too). It exists so dispatch
prompts and reviews don't get rewritten, and drift, every time.

## Setup

1. **Plan file:** `docs/plans/<date>-<name>.md`. Read it, plus the spec sections it names.
2. **Branch:** `git switch -c <plan-name-without-date>` from an up-to-date `main`. Never work on `main`.
3. **Workspace:** `bash <sdd-scripts>/sdd-workspace <plan>`, then `task-brief <plan> N` for each task. Both land in `.superpowers/sdd/<plan>/`, which is git-ignored.
4. **Ledger:** create `progress.md` with this first line:
   `# SDD ledger — plan: <plan path>`.
   Add the code repo and branch, the BASE commit and the execution style, then the pre-flight table. The table has one row per pair of tasks that share a file or interface, and records any rulings.
5. **Baseline:** run `uv run pytest -q` once and record the count in the ledger.

## Dispatch (one implementer per task; sonnet by default, haiku for small mechanical tasks)

Use this prompt, filling in the `<…>` parts. Batch tiny tasks of the same shape into one dispatch.

```
You are implementing <task(s)> of "<plan title>" for Bastet, a Python homelab CLI (repo ~/Repos/bastet, branch
<branch> — already checked out; do not switch branches, do not push).

Read this first — it is your requirements, with exact names and values to use verbatim:
<brief path(s)>
Background (only the sections you need): <spec path §…>

Available from earlier tasks (read the code, keep their contracts): <interfaces>
Orientation (verify): <files and functions to start from>
Decisions already made: <rulings, user decisions>

Rules:
- TDD: failing tests first, see them fail for the right reason, then implement.
- Tests never touch the real inventory, ~/.config/bastet, ~/.local/share/bastet, ~/.ssh, real ~/.cache or
  $XDG_RUNTIME_DIR; no network; tmp_path only; placeholder data only (see "Example data" in docs/ROADMAP.md: 10.1.x.x addresses,
  host names like pve1/media01, user admin).
- Run ONLY the test files named in the brief (never the full suite, never BASTET_CONTRACT unless told); the controller or the user runs the wide suites at the checkpoints.
- Match surrounding style; no "spec §"/"Task N" references in src/; bastet.core never imports typer.
- Commit with `git add <files by name>` (never `git commit -a`; never stage AUDIT.md, refs/, .superpowers/,
  .privacy-patterns). Messages end with:
  Co-Authored-By: <model> <noreply@anthropic.com>
  Claude-Session: <session url>
- Do not dispatch subagents; don't leave background shell loops running.

Write your full report to <workspace>/task-<N>-report.md.
Return only: status, commit hash(es), one-line test summary, concerns.
```

## Routine agreed with the user (2026-10-10)

- **One sonnet implementer per task, run one at a time**, never in parallel. No per-task reviewer subagent.
- Each agent commits when it thinks it is done, with `(Task N, not reviewed yet)` on the first line of the message.
  A fix after a failed test run goes in a follow-up commit, never an amend.
- **After each task:** the controller reads the `src/` diff, checks `git status` and `ps`, writes the ledger line,
  **pushes the branch**, reports in plain words (what was built, what the agent changed from the brief and why, what
  to run), then waits for the user's go unless they said to keep going. Give the user the exact test command for the
  plan's checkpoints; **run it yourself** when they ask or are away from the computer.
- **Tell the agent to see its tests fail first** (one agent skipped the red step), and to keep test file basenames
  unique across `tests/` (there are no `__init__.py` files; two `test_run_events.py` broke collection).
- Agents' briefs sometimes contain bugs in tests or code; they fix them minimally and say so. Review those changes.
- Agents leave polling loops running after they finish (`until grep …; do sleep 3; done`); look for them with `ps`
  and kill only those.
- **When the user is on a phone,** ask with pick-able questions (`AskUserQuestion`); put the substance in the option
  descriptions, because the text before the tool call may not be shown.
- Final review (opus), then **one fix wave** (a sonnet agent, Critical and Important plus the cheap Minors), then you
  run the full suite, log the deferred items in `docs/ROADMAP.md`, and **ask** before merging, pushing and deleting
  the branch. When told: `git switch main && git merge --ff-only <branch> && git push origin main`, then delete the
  branch locally and on the remote.
- Edit scripts that change several files: chain the following `git add`/`commit` with `&&` (not `;`) and look at
  `git status` first, so a failed edit cannot be committed under a message that describes it.

## Per-task review (the controller does this itself, not a subagent)

- `git status --short`: nothing stray beyond `AUDIT.md`, and nothing left uncommitted.
- Read the `src/` diff for the task (`git diff <base>..<head> -- src/`).
- Check the brief's behaviour against that diff, especially the plan's Review Focus items.
- Check the tests prove the behaviour, not the mock.
- `ps -eo pid,etime,cmd | grep -E "until|sleep|pytest"`: no leftover loops from the agent.
- `scripts/privacy-check --staged` (or a full scan) shows nothing new.
- **Findings:**
  - **Important ones:** send back to the same agent (SendMessage) as a fix round, with the covering tests named.
  - **Minor ones:** ledger as `minor (deferred)`.
- **Ledger** `Task N: complete (commits a..b, <tests>)`.

## Final review (opus)

1. Build the package: `review-package <plan> <merge-base> HEAD`. If it lands under the repo's `.superpowers/` path, that's fine, it's ignored.
2. Dispatch it with `model: opus`, using `requesting-code-review/code-reviewer.md`, with:
   - the package;
   - the plan and spec paths;
   - the plan's Review Focus, verbatim;
   - the ledger's rulings and deferred minors to triage;
   - Bastet's constraints (above).

   The reviewer writes `final-review.md` and returns only counts and titles.
3. **One fix wave** (one agent, all Critical and Important findings), then a scoped re-review by the controller.

## Finish

- **Update `docs/ROADMAP.md`:**
  - the status marks (blocks, roles, milestones);
  - the "Now" section;
  - if it's a redesign subplan, `docs/plans/*-roadmap.md` too.

  Commit by name.
- **Tell the user** what changed, the rulings made for them (with the cost if wrong), and the deferred minors.
- **Ask before** merging into `main` and before pushing. When told: `git switch main && git merge --ff-only <branch> && git push origin main && git branch -d <branch>`.
- Leave the `.superpowers/sdd/<plan>/` workspace for the user to delete, or delete it if they ask.
