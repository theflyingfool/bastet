---
name: bastet-run-plan
description: Use when executing a Bastet implementation plan from docs/plans/ — sets up the branch (or the temporary worktree a background session needs) and the ledger, dispatches one implementer per task with Bastet's rules baked in, reviews each task, runs the final review and one fix wave, updates docs/ROADMAP.md, and asks before merging a plan. Use together with superpowers:subagent-driven-development (this skill supplies the Bastet-specific parts).
---

# Running a Bastet plan

Bastet-specific layer on top of `superpowers:subagent-driven-development` (load that too). It exists so dispatch
prompts and reviews don't get rewritten, and drift, every time.

## Setup

1. **Plan file:** `docs/plans/<date>-<name>.md`. Read it, plus the spec sections it names.
2. **Branch:** `git switch -c <plan-name-without-date>` from an up-to-date `main`. Never work on `main`.
   - **Background sessions** refuse edits in the main checkout ("call EnterWorktree first"). The owner allows a
     *temporary* worktree for that: `git worktree add .claude/worktrees/<name> -b <branch> main` (use an absolute
     path if you are already inside a worktree), then `EnterWorktree` with `path`. Never leave worktrees behind (see
     Finish). Never set `"worktree": {"bgIsolation": "none"}` in `.claude/settings.json` yourself; only the owner may.
3. **Workspace:** `bash <sdd-scripts>/sdd-workspace <plan>`, then `task-brief <plan> N` for each task (`4b` style ids
   work). Both land in `.superpowers/sdd/<plan>/`, which is git-ignored. Run these as plain commands (a compound
   `&&` chain with git in it can be refused inside a worktree session).
4. **Ledger:** create `progress.md` with this first line:
   `# SDD ledger — plan: <plan path>`.
   Add the code repo and branch, the BASE commit and the execution style, then the pre-flight table. The table has one row per pair of tasks that share a file or interface, and records any rulings.
5. **Baseline:** run `uv run pytest -q` once and record the count in the ledger (about 4 minutes).

## Dispatch (one implementer per task; sonnet by default, haiku for small mechanical tasks)

Use this prompt, filling in the `<…>` parts. Batch tiny tasks of the same shape into one dispatch.

```
You are implementing <task(s)> of "<plan title>" for Bastet, a Python homelab CLI (repo ~/Repos/bastet, working
directory <worktree or checkout path>, branch <branch> — already checked out; do not switch branches, do not push,
do not create or remove worktrees, do not touch any other worktree). Stay inside that directory for all commands.

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
- Run ONLY the test files/folders named in the brief (never the full suite, never BASTET_CONTRACT unless told), in the
  foreground. If `uv run pytest` cannot import bastet, use `PYTHONPATH=src .venv/bin/python -m pytest`.
- Match surrounding style; no "spec §"/"Task N" references in src/; bastet.core never imports typer; every message
  goes through bastet.ui.out.
- `ruff check src tests` must pass; fix only findings from your own changes. Regenerate docs/roles.md with
  scripts/gen_roles_doc.py when a role.yml or role note changes (a repo test checks it).
- Commit with `git add <files by name>` (never `git commit -a`; never stage AUDIT.md, refs/, .superpowers/,
  .privacy-patterns). First line ends with `(Task N, not reviewed yet)`. Messages end with:
  Co-Authored-By: <model> <noreply@anthropic.com>
  Claude-Session: <session url>
- Do not dispatch subagents. Do NOT start sleep/poll loops (`until … sleep`, `sleep 900` waits); run tests in the
  foreground and wait for them to return.

Write your full report to <workspace>/task-<N>-report.md.
Return only: status, commit hash(es), one-line test summary, concerns.
```

## Routine agreed with the user (2026-10-10, updated 2026-10-11)

- **One sonnet implementer per task, run one at a time**, never in parallel. In a worktree session the harness lets
  agents run git only in the worktree the session is in, so a second worktree needs the controller to switch with
  `EnterWorktree path` first. No per-task reviewer subagent.
- Each agent commits when it thinks it is done, with `(Task N, not reviewed yet)` on the first line of the message.
  A fix after a failed test run goes in a follow-up commit, never an amend.
- **After each task:** the controller reads the `src/` diff, checks `git status` and `ps`, writes the ledger line,
  **pushes the branch**, reports in plain words (what was built, what the agent changed from the brief and why, what
  to run), then waits for the user's go unless they said to keep going (they usually do after the first task).
- **The owner runs the full suite himself.** At the checkpoints give the exact command, for example
  `cd <worktree> && uv run pytest -q`, and wait for his "passed/failed" before merging. Run it yourself only when he
  says to. Say "go" only when no agent is running and the branch is committed and pushed.
- **Tell the agent to see its tests fail first** (some agents skip the red step) and to keep test file basenames
  unique across `tests/` (there are no `__init__.py` files; two `test_run_events.py` broke collection).
- Agents' briefs sometimes contain bugs in tests or code; they fix them minimally and say so. Review those changes.
- **Leftover loops:** agents leave polling loops running after they finish (`until grep …; do sleep 3; done`, long
  `sleep 880` waits); the symptom is the same agent reporting "done" again and again. Look with
  `ps -eo pid,etime,cmd | grep -E "until|sleep [0-9]{3}|pytest"` and kill only the old sleeps, never a test run that
  belongs to a live agent.
- **The owner adds design points mid-run.** Fold them into the plan file (commit it between tasks, never while an agent
  is committing), re-brief, and say what changed. Do not edit the plan while an agent is mid-commit in the same tree.
- **When the user is on a phone,** ask with pick-able questions (`AskUserQuestion`); put the substance in the option
  descriptions, because the text before the tool call may not be shown.
- Final review (opus), then **one fix wave** (a sonnet agent, Critical and Important plus the cheap Minors), then a
  scoped re-review by you, then the owner's full-suite run, then log the deferred items in `docs/ROADMAP.md`.
- Edit scripts that change several files: chain the following `git add`/`commit` with `&&` (not `;`) and look at
  `git status` first, so a failed edit cannot be committed under a message that describes it. Put long edit scripts
  in a file under `$CLAUDE_JOB_DIR/tmp` and run that, instead of a big heredoc.

## Per-task review (the controller does this itself, not a subagent)

- `git status --short`: nothing stray beyond `AUDIT.md`, and nothing left uncommitted.
- Read the `src/` diff for the task (`git diff <base>..<head> -- src/`).
- Check the brief's behaviour against that diff, especially the plan's Review Focus items.
- Check the tests prove the behaviour, not the mock, and that a new default has a test that can fail.
- **Anything applied to every host by default must be neutral:** with no options set it changes nothing (the Arch
  default `systemd` role once would have renamed every host and forced the RTC). Look at what the builder emits with
  empty values.
- `ps -eo pid,etime,cmd | grep -E "until|sleep|pytest"`: no leftover loops from the agent.
- `ruff check src tests` passes; `scripts/privacy-check` shows nothing new (a fresh worktree has no
  `.privacy-patterns`: copy it from the main checkout, run the check, delete the copy).
- **Findings:**
  - **Important ones:** send back to the same agent (SendMessage) as a fix round, with the covering tests named.
  - **Minor ones:** ledger as `minor (deferred)`.
- **Ledger** `Task N: complete (commit, <tests>)`.

## Final review (opus)

1. Build the package: `review-package <plan> <merge-base-or-plan-commit> HEAD`. If it lands under the repo's `.superpowers/` path, that's fine, it's ignored.
2. Dispatch it with `model: opus`, using `requesting-code-review/code-reviewer.md`, with:
   - the package;
   - the plan and spec paths;
   - the plan's Review Focus, verbatim;
   - the ledger's rulings and deferred minors to triage;
   - Bastet's constraints (above);
   - "read-only: do not edit, commit, or run the full suite; no background loops".

   The reviewer writes `final-review.md` and returns only counts and titles.
3. **One fix wave** (one agent, all Critical and Important findings plus the cheap Minors), then a scoped re-review by
   the controller.

## Finish

- **Update `docs/ROADMAP.md`:**
  - the status marks (blocks, roles, milestones);
  - the "Now" section;
  - the "Planned additions" table (add what the work revealed; remove what is built);
  - if it's a redesign subplan, `docs/plans/*-roadmap.md` too.

  Commit by name.
- **Tell the user** what changed, the rulings made for them (with the cost if wrong), and the deferred minors.
- **Plans:** ask before merging into `main` (a plan is a lot of change). **Small edits made in a temporary worktree**
  (skills, docs, one-file fixes): the owner said not to ask; commit, push, merge and clean up.
- **Merging from a worktree session** (the main checkout cannot be switched from there):
  `git fetch origin && git merge-base --is-ancestor origin/main HEAD` (it must succeed), then
  `git push origin <branch>:main`. Then `ExitWorktree` (keep), and from the main checkout: copy the ignored
  `.superpowers/sdd/<plan>/` out of the worktree if you want to keep it, `git worktree remove --force <path>`,
  `rmdir .claude/worktrees`, `git merge --ff-only origin/main`, `git branch -d <branch>`,
  `git push origin --delete <branch>`. Tell the owner to `git pull` if you could not update his checkout.
- **No worktree is left behind.** Leave the `.superpowers/sdd/<plan>/` workspace in the main checkout for the owner to
  delete, or delete it if he asks.
