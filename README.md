# MIRA — your own independent AI

*(The project and its `JARVIS_*` settings keep the original JARVIS name; the
assistant herself is MIRA: a casual, best-friend-style persona that speaks
Japanese by default. Rename her with `JARVIS_NAME`.)*

A fully self-hosted personal AI assistant. It runs a **free, local language
model on your own device** — a PC, or an Android phone — with no API keys, no
usage fees, and no calls to Claude or OpenAI. Once the model is downloaded it
works **completely offline**. It has a persistent personality, long-term memory,
real tools (shell, files, web), autonomous background tasks, scheduled jobs,
a phone-friendly web app, and optional voice.

It's also pluggable: if you ever want a more powerful brain, flip one setting to
use the Claude API instead. The default is local and free.

> "Sometimes you gotta run before you can walk." — JARVIS does the running.

## Run it on your phone (Android)

JARVIS runs entirely on an Android phone inside [Termux](https://f-droid.org/packages/com.termux/),
using llama.cpp for the model and a small web app as the interface:

```bash
pkg install -y git && git clone https://github.com/s66bell/AI-.git jarvis && cd jarvis
bash scripts/termux/setup.sh     # installs llama.cpp, downloads a ~2GB model
bash scripts/termux/start.sh     # then open http://localhost:8765 in Chrome
```

Add the page to your home screen and it behaves like an app. Full guide (in
Japanese): [docs/ANDROID.md](docs/ANDROID.md).

## Agent mode

Beyond chat, JARVIS can work on its own:

- **Background tasks** — hand it a goal ("find this week's top AI papers and
  summarise them"). It plans, uses tools as many times as needed, runs a
  self-check against the goal, and files a report. From chat, JARVIS can
  delegate to itself with `start_background_task`.
- **Schedules** — run a goal daily at a set time or every N minutes. Runs
  missed while the device slept happen once on wake-up.
- **Live progress** — the web UI streams each step; tasks can be cancelled.

Risky actions (destructive shell commands) are confirmed with you in chat and
declined automatically in background tasks unless `JARVIS_AGENT_ALLOW_DANGEROUS=1`.

## What it can do

- **Hold a real conversation** with a consistent persona that calls you by name
  and remembers you across sessions.
- **Actually do things**, not just talk, through tools:
  - `run_shell` — run commands on your machine (destructive ones are confirmed)
  - `read_file` / `write_file` / `list_directory` — work with your files
  - `web_search` / `web_fetch` — look things up online (needs internet)
  - `remember` / `recall_memories` / `forget` — durable long-term memory
  - `get_datetime` / `get_system_info` — situational awareness
- **Remember what matters**, permanently, across restarts.
- **Run entirely on your hardware** with an open model — independent and private.
- **Talk, optionally**, with voice in and out.

## Quick start on a PC (free, local)

**1. Install [Ollama](https://ollama.com/download)** (the local model runtime),
then pull a model. For ~16GB RAM, `qwen2.5:7b` is a great tool-using model:

```bash
ollama pull qwen2.5:7b      # ~8GB RAM? use qwen2.5:3b or llama3.2:3b
```

**2. Install JARVIS and configure:**

```bash
pip install -r requirements.txt
cp .env.example .env        # defaults to the local Ollama model — no key needed
```

**3. Run:**

```bash
python run.py               # or:  python -m jarvis
```

```
You  what's running on port 8080?
JARVIS  Let me take a look, Sir.
· using run_shell
Nothing is listening on port 8080 at the moment.
```

That's it — a private AI assistant running on your own machine, for free.

### Choosing a local model

| Your RAM | Suggested model | Pull command |
| --- | --- | --- |
| ≤ 8 GB | `qwen2.5:3b` / `llama3.2:3b` | `ollama pull qwen2.5:3b` |
| ~16 GB | `qwen2.5:7b` / `llama3.1:8b` | `ollama pull qwen2.5:7b` |
| 32 GB+ | `qwen2.5:14b` and up | `ollama pull qwen2.5:14b` |

Set your choice in `.env` via `JARVIS_OLLAMA_MODEL`. Models that support tool
calling (the Qwen2.5 and Llama 3.1/3.2 families) work best, since JARVIS relies
on tools to get things done.

## Web UI on a PC

```bash
python -m jarvis web          # http://localhost:8765
```

Set `JARVIS_WEB_HOST=0.0.0.0` and `JARVIS_WEB_TOKEN=<secret>` to reach it from
other devices on your network.

## Other model servers

`JARVIS_PROVIDER=llamacpp` talks to any OpenAI-compatible endpoint, so the same
setup works with llama.cpp's `llama-server`, LM Studio, vLLM, or Hugging Face
TGI — point `JARVIS_OPENAI_BASE_URL` at it.

## Using Claude instead (optional, paid)

If you want a more capable brain, set `JARVIS_PROVIDER=claude`, run
`pip install -r requirements-claude.txt`, and add your `ANTHROPIC_API_KEY` in `.env`. Everything else — persona, memory, tools, UI —
stays identical. On `claude-fable-5`, JARVIS automatically opts into a
server-side fallback so a safety refusal is re-served rather than failing.

## Configuration

Everything is set via environment variables (or `.env`). See `.env.example` for
the full list. Highlights:

| Variable | Default | Meaning |
| --- | --- | --- |
| `JARVIS_PROVIDER` | `ollama` | `ollama` (local, free) or `claude` (API, paid). |
| `JARVIS_OLLAMA_MODEL` | `qwen2.5:7b` | Local model name (must be pulled in Ollama). |
| `JARVIS_OLLAMA_HOST` | `http://localhost:11434` | Where Ollama is listening. |
| `ANTHROPIC_API_KEY` | — | Required only when `JARVIS_PROVIDER=claude`. |
| `JARVIS_MODEL` | `claude-opus-4-8` | Claude model (when using Claude). |
| `JARVIS_USER_NAME` | `Sir` | What it calls you. |
| `JARVIS_NAME` | `JARVIS` | What you call it. |
| `JARVIS_DATA_DIR` | `~/.jarvis` | Where memory + history live. |
| `JARVIS_SHOW_THINKING` | `0` | Stream a summary of its reasoning. |
| `JARVIS_CONFIRM_ALL_SHELL` | `0` | Confirm *every* shell command, not just risky ones. |
| `JARVIS_VOICE` | `0` | Start in voice mode. |

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

System audio libraries are needed:

- **macOS:** `brew install portaudio`
- **Debian/Ubuntu:** `sudo apt install portaudio19-dev espeak`

Then run with `JARVIS_VOICE=1` or toggle `/voice` mid-session.

## How it's built

```
jarvis/
  config.py        environment-driven configuration
  persona.py       the JARVIS personality (system prompt)
  memory.py        conversation transcript + long-term facts (on disk)
  assistant.py     provider-agnostic orchestrator (persona + memory + tools)
  agent.py         background task runner: plan → act → self-check → report
  scheduler.py     recurring tasks (daily at HH:MM / every N minutes)
  backends/
    base.py        the backend interface + agentic loop contract
    openai_compat.py  llama.cpp / any OpenAI-compatible server  ← phone brain
    ollama.py      local LLM via Ollama
    claude.py      Claude API (optional)
    tool_calls.py  repairs the tool calls small models emit (JSON / text)
  tools/           shell, files, system, memory, and (local) web tools
  web/             dependency-free HTTP server + the PWA (static/)
  voice/           optional speech-to-text / text-to-speech
  cli.py           the interactive terminal interface
scripts/termux/    Android setup / start / stop
docs/ANDROID.md    phone guide (Japanese)
tests/             pytest suite with a fake OpenAI-compatible model server
```

The **backend** owns the conversation with the model and runs the agentic loop:
stream the reply, let the model call tools, run them locally (gating destructive
actions behind your confirmation), feed the results back, and repeat until the
task is done. The llama.cpp, Ollama and Claude backends implement the same
interface, so the persona, memory, tools, agent runner and UIs are written once
and work with any brain.

## Why it's "independent"

A frontier model like Claude or GPT can't be trained from scratch for free —
that takes millions of dollars of compute. But you don't need to: JARVIS runs an
**open-weight model** (Qwen, Llama, Mistral, …) locally via llama.cpp or Ollama. The weights
live on your disk, the conversation never leaves your machine, and after the
one-time model download it needs no internet and no third-party service. That's
a genuinely independent, private, zero-cost AI you fully own.

## Safety

JARVIS runs with your authority on your machine, but it asks before doing
anything destructive — deleting data, overwriting files, `sudo`, force-pushing,
piping the internet into a shell, and so on. Set `JARVIS_CONFIRM_ALL_SHELL=1` to
be asked before *any* command runs. Memory and history stay on your local disk.

## Make it yours

This is a starting point, not a cage:

- Add tools for the things *you* do — calendar, email, smart-home, your APIs.
  Drop a module in `jarvis/tools/` and register it.
- Tune the personality in `jarvis/persona.py`.
- Try different local models in Ollama to trade speed for capability.
- Swap the terminal UI for a web or mobile front-end — the `Assistant` and
  backend classes are interface-agnostic.
