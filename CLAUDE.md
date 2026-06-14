# JARVIS — project guide for Claude Code

A personal AI assistant with a persistent personality, long-term memory, real
tools, and a phone-friendly web app. This file orients you and defines how to
**orchestrate** work on it. Keep edits idiomatic to the surrounding code.

## Architecture

- `jarvis/config.py` — all settings from env vars (`Config.load()`). Add new
  config as a dataclass field **and** wire it in `load()`.
- `jarvis/assistant.py` — the agent loop; ties backend + memory + tools.
- `jarvis/persona.py` — system prompt / personality.
- `jarvis/backends/` — `base.py` (shared loop), `ollama.py` (local), `hf.py`
  (Hugging Face Inference), `claude.py`. Providers: `ollama` | `hf` | `claude`.
- `jarvis/memory.py` — long-term **facts** (`memory.json`) + per-thread
  transcript. Facts are global; transcript is scoped to the current thread.
- `jarvis/store.py` — SQLite (`jarvis.db`): conversation **threads**,
  **messages**, **reminders**. One connection guarded by a lock.
- `jarvis/persistence.py` — optional free persistence: snapshot `jarvis.db` +
  `memory.json` to a private HF Dataset, restore on boot.
- `jarvis/tools/` — `filesystem`, `shell`, `web`, `system_info`, `memory_tool`,
  `reminders`. Registered in `tools/__init__.py:build_registry`.
- `jarvis/web/server.py` — FastAPI host + JSON streaming; single-user, one turn
  at a time behind `_turn_lock`. Static PWA in `jarvis/web/static/`.
- `jarvis/cli.py` — terminal app. Entrypoints: `serve.py` (web), `run.py` (CLI).

## Conventions

- Match the existing comment density and the explanatory, first-person-plural
  voice already in the files. Don't add boilerplate or restate the obvious.
- Single-user web server by design. Mutations that change persisted data should
  trigger `server._save()` (debounced HF-Dataset snapshot).
- Keep features optional/degradable: if a token/env is missing, the feature is
  silently off and the app behaves as before (see `persistence.py`).
- Front-end is vanilla JS/CSS in `static/` — no build step, no frameworks.

## Testing (no framework)

This repo has no pytest suite. Verify changes with:

- `python -m py_compile <files>` for every changed `.py`.
- `node --check jarvis/web/static/app.js` for JS.
- Small **inline scripts with stubs** for logic (e.g. a fake `huggingface_hub`,
  a fake assistant, an in-process `uvicorn` server hit with `requests`). Prefer
  these over adding a test dependency. Mirror the data layer / HTTP tests used
  in this project's history.

## Git / shipping

- Develop on the feature branch you were given; never push to `main` directly.
- `python -m py_compile` (and `node --check` if JS changed) must pass first.
- Commit with a clear message, push with `git push -u origin <branch>`, then
  open a **draft** PR if none exists.

## Orchestration policy

For non-trivial work, **delegate** to the project subagents instead of doing
everything inline. The default pipeline (also available as `/orchestrate`):

1. **planner** — produce a concrete, codebase-grounded step plan. Read-only.
2. **builder** — implement the plan, matching conventions; compile as you go.
3. **reviewer** — review the working diff for correctness + conventions.
4. **tester** — write/run stub-based checks and report results.

Then the main session integrates, commits, pushes, and opens the PR.

Guidelines:
- Run **independent** investigations in parallel (one message, multiple Agent
  calls) — e.g. planner researching while reviewer studies a related area.
- Keep each subagent's scope tight; pass it only the context it needs.
- Loop builder↔reviewer↔tester until clean; don't ship on the first pass.
- You (the coordinator) own the final decision, the commit, and the PR.
- For a quick single-fact lookup you already know how to do, skip the pipeline.
