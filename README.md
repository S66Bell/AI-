# Mira — your own independent AI

A fully self-hosted AI assistant. It runs a **free, local language
model on your own machine** — no API keys, no usage fees, no calls to Claude or
OpenAI — and once the model is downloaded it works **completely offline**. It
has a persistent personality, long-term memory, real tools (shell, files, web),
and optional voice.

It's also pluggable: if you ever want a more powerful brain, flip one setting to
use the Claude API instead. The default is local and free.

> Note: the Python package, env vars (`JARVIS_*`), and data files keep the
> `jarvis` name for compatibility — the assistant is **Mira**.

> "Sometimes you gotta run before you can walk." — Mira does the running.

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
then pull a model. The default is `qwen2.5:7b` — a strong **tool-using** model
for ~16GB RAM, so Mira can actually run shell, files, and web for you:

```bash
ollama pull qwen2.5:7b      # ~8GB RAM? use qwen2.5:3b or llama3.2:3b
```

> Prefer a different brain? Any Ollama model works. Note that **Gemma** has no
> tool-calling in Ollama, so Mira falls back to **chat-only** with it (no
> shell/file/web actions) — fine for conversation, see the model table below.

**2. Install Mira and configure:**

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
Mira  Let me take a look, Sir.
· using run_shell
Nothing is listening on port 8080 at the moment.
```

That's it — a private AI assistant running on your own machine, for free.

### Choosing a local model

Set your choice in `.env` via `JARVIS_OLLAMA_MODEL`.

**Full tool use (default) — Qwen / Llama:** lets Mira run shell, edit files,
and search the web. Mira relies on tool calling to get things done, so these
unlock its full capabilities.

| Your RAM | Suggested model | Pull command |
| --- | --- | --- |
| ≤ 8 GB | `qwen2.5:3b` / `llama3.2:3b` | `ollama pull qwen2.5:3b` |
| ~16 GB | `qwen2.5:7b` (default) / `llama3.1:8b` | `ollama pull qwen2.5:7b` |
| 32 GB+ | `qwen2.5:14b` and up | `ollama pull qwen2.5:14b` |

**Chat-only — Gemma:** great conversation, but no tools (no shell/file/web).
With a model that can't call tools, Mira automatically falls back to chat-only
and tells you once.

| Your RAM | Gemma model | Pull command |
| --- | --- | --- |
| ≤ 4 GB | `gemma3:1b` | `ollama pull gemma3:1b` |
| ~8 GB | `gemma3:4b` | `ollama pull gemma3:4b` |
| 16 GB+ | `gemma3:12b` / `gemma3:27b` | `ollama pull gemma3:12b` |

## Using Claude instead (optional, paid)

If you want a more capable brain, set `JARVIS_PROVIDER=claude` and add your
`ANTHROPIC_API_KEY` in `.env`. Everything else — persona, memory, tools, UI —
stays identical. On `claude-fable-5`, Mira automatically opts into a
server-side fallback so a safety refusal is re-served rather than failing.

## Run it on Hugging Face (no local GPU)

Prefer the cloud? Mira can use a model **served by Hugging Face** as its
brain, and the whole app can be **hosted on a Hugging Face Space** with an
always-on URL you open from your phone:

```bash
export HF_TOKEN=hf_your_token
JARVIS_PROVIDER=hf python serve.py
```

It calls HF's OpenAI-compatible router (default model
`Qwen/Qwen2.5-7B-Instruct`), so no Ollama or GPU is needed. A `Dockerfile` is
included for one-click Space hosting. Full walkthrough — brain-on-HF and
app-on-Spaces, secrets, and persistent memory — is in **[DEPLOY_HF.md](DEPLOY_HF.md)**.

> In the cloud, Mira's tools run in HF's sandbox, not on your computer — so a
> Space is ideal for chat/research/writing, while running the app on your own PC
> (optionally with the HF brain) is what lets it act on *your* machine.

### Free persistence (keep conversations across restarts)

A free Space has **no persistent disk** — its filesystem is wiped on every
restart, so conversations, threads, and long-term memory would be lost. To keep
them for free, Mira can snapshot its data to a **private HF Dataset** and
restore it on boot:

1. Create a **write** token at <https://huggingface.co/settings/tokens>.
2. Pick a dataset repo id you own, e.g. `your-name/jarvis-data` (it's created
   automatically and set private on first save — no need to make it yourself).
3. Add these as **Space secrets**:

   | Secret | Value |
   | --- | --- |
   | `HF_TOKEN` | your **write** token (also used for inference) |
   | `JARVIS_HF_DATASET` | `your-name/jarvis-data` |

That's it. On boot Mira restores the latest snapshot; after each turn (and on
shutdown) it saves back, debounced into at most one commit every few seconds.
Locally you can use the same vars to back up `~/.jarvis` to the Hub. If
`JARVIS_HF_DATASET` is unset, persistence is simply off and nothing changes.

## Google Calendar (secretary mode)

Mira can act as a secretary against your real Google Calendar: read today's
agenda (it shows up in the app-open greeting), create/change/delete events from
chat, and mirror **timed reminders** onto the calendar automatically. It uses a
**service account**, so there's no interactive login — ideal for a Space.

One-time setup:

1. In **Google Cloud**, create a project and enable the **Google Calendar API**.
2. Create a **service account**, then a **JSON key**, and download it.
3. In **Google Calendar → Settings → Share with specific people**, add the
   service account's email (`…@….iam.gserviceaccount.com`) with **"Make changes
   to events"**.
4. Copy that calendar's **ID** (Calendar settings → *Integrate calendar*).
5. Set two secrets/vars:

   | Variable | Value |
   | --- | --- |
   | `JARVIS_GCAL_CREDENTIALS` | the JSON key, pasted inline (or a path to the file) |
   | `JARVIS_GCAL_ID` | the calendar id from step 4 |

That's it — creating/changing/deleting events asks for confirmation first, since
they touch your real calendar. If `JARVIS_GCAL_CREDENTIALS` is unset (or the
Google libraries aren't installed), calendar features are simply off and nothing
changes. Note: sync is one-way (reminders → calendar) for now — editing an event
directly in Google won't update the matching reminder.

> The service account's own `primary` calendar is an empty mailbox, so leaving
> `JARVIS_GCAL_ID=primary` "works" but shows nothing — be sure to set it to the
> calendar you shared in step 3.

## Web search

`web_search` works out of the box with no key via DuckDuckGo's public endpoint —
fine on a home network. But **cloud hosts (a Hugging Face Space) are usually
blocked** (HTTP 403), so for reliable search there set one free API key:

- **Tavily** (made for AI, generous free tier): sign up at
  [tavily.com](https://tavily.com), then set `JARVIS_TAVILY_API_KEY`.
- **Brave Search** (free tier): get a key at
  [brave.com/search/api](https://brave.com/search/api/), set `JARVIS_BRAVE_API_KEY`.

Tavily is preferred when both are set. With neither, Mira falls back to keyless
DuckDuckGo and tells you to add a key if that host is blocked.

## Configuration

Everything is set via environment variables (or `.env`). See `.env.example` for
the full list. Highlights:

| Variable | Default | Meaning |
| --- | --- | --- |
| `JARVIS_PROVIDER` | `ollama` | `ollama` (local, free), `hf` (Hugging Face), or `claude` (paid). |
| `JARVIS_OLLAMA_MODEL` | `qwen2.5:7b` | Local model name (must be pulled in Ollama). |
| `HF_TOKEN` | — | Hugging Face token (required when `JARVIS_PROVIDER=hf`). |
| `JARVIS_HF_MODEL` | `Qwen/Qwen2.5-7B-Instruct` | Served model id for the `hf` provider. |
| `JARVIS_OLLAMA_HOST` | `http://localhost:11434` | Where Ollama is listening. |
| `ANTHROPIC_API_KEY` | — | Required only when `JARVIS_PROVIDER=claude`. |
| `JARVIS_MODEL` | `claude-opus-4-8` | Claude model (when using Claude). |
| `JARVIS_HF_MAX_TOKENS` | `4096` | Max tokens the HF model may generate per reply (prevents truncated answers). |
| `JARVIS_TEMPERATURE` | — | Sampling temperature for HF/Ollama; lower (e.g. `0.3`) = crisper. Empty = provider default. |
| `JARVIS_USER_NAME` | `Yukiさん` | What it calls you. |
| `JARVIS_NAME` | `Mira` | What you call it. |
| `JARVIS_TIMEZONE` | `Asia/Tokyo` | IANA timezone for every clock it shows (matters on UTC cloud hosts). |
| `JARVIS_DATA_DIR` | `~/.jarvis` | Where memory + history live. |
| `JARVIS_HF_DATASET` | — | Private HF Dataset repo id for free persistence (see below). |
| `JARVIS_GCAL_CREDENTIALS` | — | Google service-account key (inline JSON or path) to enable calendar. Empty = off. |
| `JARVIS_GCAL_ID` | `primary` | Calendar id Mira reads/writes (set to the calendar you shared — see below). |
| `JARVIS_TAVILY_API_KEY` | — | Tavily search key — reliable web search on a Space (free tier). Empty = keyless DuckDuckGo. |
| `JARVIS_BRAVE_API_KEY` | — | Brave Search key — alternative to Tavily (used only if Tavily is unset). |
| `JARVIS_VAPID_PUBLIC_KEY` | — | VAPID public key for Web Push briefings. Empty = push off. |
| `JARVIS_VAPID_PRIVATE_KEY` | — | VAPID private key (both keys required to enable push). |
| `JARVIS_SHOW_THINKING` | `0` | Stream a summary of its reasoning. |
| `JARVIS_CONFIRM_ALL_SHELL` | `0` | Confirm *every* shell command, not just risky ones. |
| `JARVIS_VOICE` | `0` | Start in voice mode. |

## In-session commands

```
/help            show help
/memory          list everything Mira remembers
/forget <text>   forget remembered facts matching <text>
/reset           clear the current conversation context
/clear-history   wipe saved conversation history on disk
/thinking        toggle showing Mira's reasoning
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

Prefer a chat window over the terminal? Mira ships with a small web app — the
same assistant, persona, memory, and tools, in your browser.

```bash
pip install -r requirements-web.txt
python serve.py
```

It starts a local server and **opens `http://localhost:8765` in your browser**
automatically. The window:

- Streams replies live and shows what Mira is doing.
- Pops a **Proceed / Decline** dialog before any destructive action runs.
- **Voice, in the browser:** tap 🎤 to turn on **always-on listening** — Mira
  hears you, replies aloud, and keeps listening for a hands-free conversation;
  tap 🎤 again to return to normal chat. Read-aloud can also be toggled on its
  own from the `⋮` menu. Uses the device's own Web Speech engine, so it works on
  the phone with nothing to install. (Mic needs a supporting browser, e.g.
  Chrome/Android; read-aloud is broader.)
- Has a `⋮` menu for read-aloud, reset, memory, reasoning toggle, clear-history,
  and settings.
- **Conversation threads:** the `☰` drawer lists your separate conversations —
  start a new one, switch between them, search across them, or delete.

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
  persona.py       the Mira personality (system prompt)
  memory.py        conversation transcript + long-term facts (on disk)
  store.py         SQLite store: conversation threads + reminders
  assistant.py     provider-agnostic orchestrator (persona + memory + tools)
  backends/
    base.py        the backend interface + agentic loop contract
    ollama.py      local LLM via Ollama  ← the independent, free brain
    hf.py          Hugging Face Inference (cloud brain, no local GPU)
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
that takes millions of dollars of compute. But you don't need to: Mira runs an
**open-weight model** (Qwen, Llama, Mistral, …) locally via Ollama. The weights
live on your disk, the conversation never leaves your machine, and after the
one-time model download it needs no internet and no third-party service. That's
a genuinely independent, private, zero-cost AI you fully own.

## Safety

Mira runs with your authority on your machine, but it asks before doing
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
