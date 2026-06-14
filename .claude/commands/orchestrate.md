---
description: >
  Run the full plan → build → review → test pipeline for a JARVIS feature,
  delegating to the project subagents, then commit and open a draft PR.
argument-hint: "<feature or change to build>"
---

You are the **coordinator**. Orchestrate the project subagents to deliver this
change end to end. Read CLAUDE.md first if you haven't this session.

Request: **$ARGUMENTS**

Current state for context:

- Branch: !`git rev-parse --abbrev-ref HEAD`
- Status: !`git status --short`

Pipeline:

1. **Plan.** Delegate to the `planner` subagent with the request above. If the
   plan surfaces a genuine decision that's the user's to make (not a default you
   can pick), ask via AskUserQuestion before building.
2. **Build.** Delegate the approved plan to the `builder` subagent.
3. **Review + test in parallel.** In one message, spawn the `reviewer` (on the
   working diff) and the `tester` (stub-based checks). Wait for both.
4. **Iterate.** If the reviewer says "needs work" or the tester reports a
   failure, loop back to `builder` with the specific findings. Repeat until the
   review verdict is **ship** and tests pass. Don't ship on the first pass.
5. **Integrate & ship.** Ensure `python -m py_compile` (and `node --check` for
   JS) pass. Commit with a clear message, `git push -u origin <branch>`, and
   open a **draft** PR if none exists (per CLAUDE.md git rules).

Keep the user informed with a short status between phases, not a play-by-play.
Relay each subagent's key conclusions — the user doesn't see subagent output.
You own the final decision, the commit, and the PR.
