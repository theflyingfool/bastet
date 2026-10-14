---
name: bastet-end-session
description: Use at the end of a Bastet working session (the owner says they are wrapping up, ending the session, or asks for the end-of-session routine) — records the session's decisions, proposes new or updated skills, updates the roadmap and its "next session starts here" line, updates memory, cleans up working files, gets the checkout clean and merged (asking first), and reports.
---

# Ending a Bastet session

Run this when the owner is wrapping up. Work through the steps in order, say what you did after each, and **ask before any push, merge, or deletion**. Nothing in `refs/` is deleted. The owner usually wants the directory clean and everything merged back by the end.

## 1. Decisions

- Go through the session for decisions the owner made (rules, scope cuts, naming, deferrals, reversals).
- Add each to `docs/decisions.md`: next free ID (they only go up), date, one-line table row, short entry with the reason. A reversed decision stays and is marked **superseded by D-xxx**; mark a deferred one **deferred** and make sure its work is in `docs/ROADMAP.md`.
- Items discussed but not decided go under "Parked" in the same file.
- Specs and plans cite the IDs; add the citation where a spec or plan states the decision.

## 2. Skills

- Look back over the session for work that was done by hand more than once, rules the owner had to repeat, or mistakes that a skill would have prevented.
- List the candidates as: **new skill** (name, what it would do, why), or **update to `<skill>`** (what is outdated or missing). Include the existing skills (`bastet-new-role`, `bastet-run-plan`, `run-bastet`, this one) when a decision changed what they say.
- Propose them in the report. **Edit a skill only after the owner says yes.**

## 3. Roadmap and the handoff line

- Update `docs/ROADMAP.md`: tick what landed, add what the session revealed to "Planned additions" (one row per item, with who needs it), move deferred work out of "Now", and record cleanup debt (code left alone on purpose).
- Write or replace the handoff line at the top of the "Now" section: `**Next session starts here (<date>):** <what is done, what is next, the branch or worktree, and the first command to run>`. A reader with no memory of the session must be able to continue from it.

## 4. CLAUDE.md

- Check `CLAUDE.md` against what was decided: rules that are now wrong, links that moved, a new file that needs a pointer. Fix small drift; ask before rewriting a rule.

## 5. Memory

- Update the memory files in the project's memory directory (the path is in the session's memory instructions): project state (what is merged, what is next, dates in absolute form), feedback the owner gave about how to work, and delete or correct any memory that turned out wrong. Update the `MEMORY.md` index lines. Do not save what the repo already records.

## 6. Clean up working files

- Scratch files in `$CLAUDE_JOB_DIR/tmp` (or wherever this session put temporary scripts): delete them once they are not needed.
- Leftover loops and test runs: `ps -eo pid,etime,cmd | grep -E "until|sleep [0-9]{3}|pytest"`. Kill only your own old sleeps and loops, never a run that belongs to a live agent.
- `git status` in every checkout and worktree this session used: no untracked or modified files left behind except git-ignored ones (`refs/`, `.superpowers/`, `.privacy-patterns`). Remove a copied `.privacy-patterns` from a worktree.
- Plan ledgers in `.superpowers/` are git-ignored; leave them unless the plan is merged and the owner says to clear them.
- Temporary worktrees: the branch must be pushed (after asking) and merged, then remove the worktree (`git worktree remove`). Never leave a lasting worktree (see CLAUDE.md).

## 7. Clean and merged (ask first)

1. Only when `src/` or `tests/` changed: `ruff check src tests`, and `scripts/privacy-check` (copy `.privacy-patterns` from the main checkout first, then delete the copy).
2. Commit everything that belongs; no work is left uncommitted.
3. Ask to push. After the owner's "passed" for the full test suite (give the exact command; the owner runs it), follow the Finish section of the `bastet-run-plan` skill to merge into `main`, asking first. Never push to `main` directly, force-push, or merge without the owner's go.
4. After the merge: confirm `git status` is clean on `main`, the branch is merged, and no worktree is left.

## 8. Report

Short, for a phone: what was decided (IDs), what changed (branch, commits, merged or not), the skill proposals waiting for a yes, anything not done and why, and the first command for next time. End with a `result:` line.
