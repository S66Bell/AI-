# JARVIS — your own personal AI

A fully self-hosted, JARVIS-style AI assistant powered by Claude. It runs on
your machine, under your control, with a persistent personality, long-term
memory, real tools (shell, files, web), and optional voice — the closest thing
to Tony Stark's JARVIS you can stand up in an afternoon.

> "Sometimes you gotta run before you can walk." — and JARVIS is the one
> running things for you.

## What it can do

- **Hold a real conversation** with a consistent persona that calls you by
  name and remembers you across sessions.
- **Actually do things**, not just talk about them, through tools:
  - `run_shell` — run commands on your machine (with safety confirmation for
    anything destructive)
  - `read_file` / `write_file` / `list_directory` — work with your files
  - `web_search` / `web_fetch` — live web access (Anthropic-hosted tools)
  - `remember` / `recall_memories` / `forget` — durable long-term memory
  - `get_datetime` / `get_system_info` — situational awareness
- **Remember what matters.** Tell it "remember that I prefer dark roast" and it
  will, permanently, across restarts.
- **Talk, optionally.** Plug in voice for hands-free use.
- **Think hard.** Adaptive reasoning, with a configurable effort level.

## Quick start

```bash
# 1. Install
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
#    then edit .env and add your ANTHROPIC_API_KEY

# 3. Run
python run.py          # or:  python -m jarvis
```

You'll drop into an interactive session:

```
You  what's running on port 8080?
JARVIS  Let me take a look, Sir.
· running: lsof -i :8080
Nothing is listening on port 8080 at the moment.
```

## Configuration

Everything is set via environment variables (or `.env`). See `.env.example`
for the full list. Highlights:

| Variable | Default | Meaning |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | — | **Required.** Your Anthropic API key. |
| `JARVIS_MODEL` | `claude-opus-4-8` | Which Claude model drives it. Use `claude-fable-5` for the most capable model, or `claude-sonnet-4-6` for speed. |
| `JARVIS_EFFORT` | `high` | Reasoning depth: `low` → `max`. |
| `JARVIS_USER_NAME` | `Sir` | What it calls you. |
| `JARVIS_NAME` | `JARVIS` | What you call it. |
| `JARVIS_DATA_DIR` | `~/.jarvis` | Where memory + history live. |
| `JARVIS_SHOW_THINKING` | `0` | Stream a summary of its reasoning. |
| `JARVIS_CONFIRM_ALL_SHELL` | `0` | Confirm *every* shell command, not just risky ones. |
| `JARVIS_VOICE` | `0` | Start in voice mode. |

If you picked `claude-fable-5`, the assistant automatically opts into a
server-side fallback to `claude-opus-4-8` so a safety refusal is re-served
rather than failing the turn.

## In-session commands

```
/help            show help
/memory          list everything JARVIS remembers
/forget <text>   forget remembered facts matching <text>
/reset           clear the current conversation context
/clear-history   wipe saved conversation history on disk
/thinking        toggle showing JARVIS's reasoning
/voice           toggle voice mode
/exit            shut down
```

## Voice mode

```bash
pip install -r requirements-voice.txt
```

This needs system audio libraries:

- **macOS:** `brew install portaudio`
- **Debian/Ubuntu:** `sudo apt install portaudio19-dev espeak`

Then run with `JARVIS_VOICE=1` or toggle `/voice` mid-session.

## How it's built

```
jarvis/
  config.py        environment-driven configuration
  persona.py       the JARVIS personality (system prompt)
  memory.py        conversation transcript + long-term facts (on disk)
  assistant.py     the streaming, tool-using agent loop over Claude
  cli.py           the interactive terminal interface
  tools/           client-side tools (shell, files, system, memory)
  voice/           optional speech-to-text / text-to-speech
```

The agent loop streams responses token-by-token, lets Claude call tools, runs
them locally (gating destructive actions behind your confirmation), feeds the
results back, and repeats until the task is done. Web search and fetch run on
Anthropic's side; everything else runs on your machine.

## Safety

JARVIS runs with your authority on your machine, but it asks before doing
anything destructive — deleting data, overwriting files, `sudo`, force-pushing,
piping the internet into a shell, and so on. Set `JARVIS_CONFIRM_ALL_SHELL=1`
to be asked before *any* command runs. Your API key lives only in `.env` (which
is git-ignored), and memory/history stay on your disk.

## Make it yours

This is a starting point, not a cage. A few natural next steps:

- Add tools for the things *you* do: calendar, email, smart-home, your APIs.
  Drop a new module in `jarvis/tools/` and register it.
- Tune the personality in `jarvis/persona.py`.
- Swap the terminal UI for a web or mobile front-end — the `Assistant` class is
  interface-agnostic.
