# JARVIS — your own independent AI

A fully self-hosted, JARVIS-style AI assistant. It runs a **free, local language
model on your own machine** — no API keys, no usage fees, no calls to Claude or
OpenAI — and once the model is downloaded it works **completely offline**. It
has a persistent personality, long-term memory, real tools (shell, files, web),
and optional voice.

It's also pluggable: if you ever want a more powerful brain, flip one setting to
use the Claude API instead. The default is local and free.

> "Sometimes you gotta run before you can walk." — JARVIS does the running.

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

## Quick start (free, local — recommended)

**1. Install [Ollama](https://ollama.com/download)** (the local model runtime),
then pull a model. The default is Google's **Gemma 3**, which runs comfortably
on modest hardware:

```bash
ollama pull gemma3:4b       # smaller: gemma3:1b · bigger: gemma3:12b / 27b
```

> **Heads-up on tools:** Gemma has no tool-calling support in Ollama, so JARVIS
> runs **chat-only** with it (no shell, file, or web actions — it'll say so once
> per session). If you want JARVIS to *do* things, pull a tool-capable model and
> set it via `JARVIS_OLLAMA_MODEL`, e.g. `ollama pull qwen2.5:7b`.

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

Set your choice in `.env` via `JARVIS_OLLAMA_MODEL`.

**Chat-only (default) — Gemma:** great conversation, no tools.

| Your RAM | Gemma model | Pull command |
| --- | --- | --- |
| ≤ 4 GB | `gemma3:1b` | `ollama pull gemma3:1b` |
| ~8 GB | `gemma3:4b` (default) | `ollama pull gemma3:4b` |
| 16 GB+ | `gemma3:12b` / `gemma3:27b` | `ollama pull gemma3:12b` |

**Full tool use — Qwen / Llama:** lets JARVIS run shell, edit files, search the
web. Pick one of these if you want it to *act*, not just chat.

| Your RAM | Suggested model | Pull command |
| --- | --- | --- |
| ≤ 8 GB | `qwen2.5:3b` / `llama3.2:3b` | `ollama pull qwen2.5:3b` |
| ~16 GB | `qwen2.5:7b` / `llama3.1:8b` | `ollama pull qwen2.5:7b` |
| 32 GB+ | `qwen2.5:14b` and up | `ollama pull qwen2.5:14b` |

JARVIS relies on tool calling to get things done, so the Qwen2.5 and Llama
3.1/3.2 families unlock its full capabilities. With a model that can't call
tools (like Gemma), JARVIS automatically falls back to chat-only and tells you.

## Using Claude instead (optional, paid)

If you want a more capable brain, set `JARVIS_PROVIDER=claude` and add your
`ANTHROPIC_API_KEY` in `.env`. Everything else — persona, memory, tools, UI —
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

## Web app (runs on your PC)

Prefer a chat window over the terminal? JARVIS ships with a small web app — the
same assistant, persona, memory, and tools, in your browser.

```bash
pip install -r requirements-web.txt
python serve.py
```

It starts a local server and **opens `http://localhost:8765` in your browser**
automatically. The window:

- Streams replies live and shows what JARVIS is doing.
- Pops a **Proceed / Decline** dialog before any destructive action runs.
- Has a `⋮` menu for reset, memory, reasoning toggle, clear-history, and settings.

By default it binds to localhost, so it's only reachable from this PC. It's also
an installable PWA — your browser can offer to install it as a desktop app.

### Reaching it from your phone (optional)

The same app works on a phone. Bind to your LAN and open the printed URL on the
phone (same Wi-Fi), then **Add to Home Screen**:

```bash
JARVIS_WEB_HOST=0.0.0.0 python serve.py
```

To reach it away from home, put it behind a tunnel (e.g.
[Tailscale](https://tailscale.com), `cloudflared`, or `ngrok`) and **set a
token first**, then enter the same token in the app's **Settings**:

```bash
JARVIS_WEB_HOST=0.0.0.0 JARVIS_WEB_TOKEN=your-long-secret python serve.py
```

Without a token the API is open to anyone who can reach the host, so only run
untokenised on a trusted, localhost-only or LAN setup.

| Variable | Default | Meaning |
| --- | --- | --- |
| `JARVIS_WEB_HOST` | `127.0.0.1` | Interface to bind. Use `0.0.0.0` to allow phones/LAN. |
| `JARVIS_WEB_PORT` | `8765` | Port to serve the app on. |
| `JARVIS_WEB_TOKEN` | — | If set, required to use the API (enter it in Settings). |

## How it's built

```
jarvis/
  config.py        environment-driven configuration
  persona.py       the JARVIS personality (system prompt)
  memory.py        conversation transcript + long-term facts (on disk)
  assistant.py     provider-agnostic orchestrator (persona + memory + tools)
  backends/
    base.py        the backend interface + agentic loop contract
    ollama.py      local LLM via Ollama  ← the independent, free brain
    claude.py      Claude API (optional)
  tools/           shell, files, system, memory, and (local) web tools
  voice/           optional speech-to-text / text-to-speech
  cli.py           the interactive terminal interface
  web/             FastAPI API + installable PWA (phone front-end)
    server.py      wraps the same Assistant in a streaming HTTP API
    static/        the Progressive Web App (HTML/CSS/JS, manifest, SW)
```

Both front-ends — the terminal `cli.py` and the phone `web/` PWA — drive the
**same** `Assistant` through the same four callbacks (stream text, status,
reasoning, and confirm-before-destructive-action). The web layer just routes
those over HTTP: events stream to the browser as newline-delimited JSON, and a
confirmation is answered by a second request from the phone.

The **backend** owns the conversation with the model and runs the agentic loop:
stream the reply, let the model call tools, run them locally (gating destructive
actions behind your confirmation), feed the results back, and repeat until the
task is done. The local Ollama backend and the Claude backend implement the same
interface, so the persona, memory, tools, and UI are written once and work with
either brain.

## Why it's "independent"

A frontier model like Claude or GPT can't be trained from scratch for free —
that takes millions of dollars of compute. But you don't need to: JARVIS runs an
**open-weight model** (Qwen, Llama, Mistral, …) locally via Ollama. The weights
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
- Use it from your phone with the built-in PWA (`python serve.py`), or build
  your own front-end — the `Assistant` and backend classes are interface-agnostic.
