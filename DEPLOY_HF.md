# Running JARVIS on Hugging Face

There are two independent ways to put JARVIS on Hugging Face. You can use
either on its own, or both together for a fully cloud-hosted assistant.

- **A — Brain on HF (Inference):** keep running the app on your own machine,
  but let a model *served by Hugging Face* be the brain. No local GPU/Ollama.
- **B — App on HF (Spaces):** host the whole web app on a Hugging Face Space
  so it has an always-on public URL you can open from any phone.

> **What you give up in the cloud:** JARVIS's tools (`run_shell`, file edits)
> run **wherever the app process runs**. On a Space that's HF's sandbox, not
> your computer — great for "look things up / reason / write", but it can't
> touch your home machine. For that, keep the app on your PC (A only).

---

## A — Use a Hugging Face model as the brain

1. Create a token at <https://huggingface.co/settings/tokens> (a free "Read"
   token works for the serverless Inference API).
2. Point JARVIS at HF:

   ```bash
   pip install -r requirements-web.txt
   export HF_TOKEN=hf_your_token
   export JARVIS_PROVIDER=hf
   export JARVIS_HF_MODEL=Qwen/Qwen2.5-7B-Instruct   # any served, tool-capable model
   python serve.py        # or: python -m jarvis    (terminal)
   ```

JARVIS now calls HF's OpenAI-compatible router instead of Ollama. Tools work
with tool-capable models (Qwen, Llama, …); with a model that can't call tools
it falls back to chat-only and says so once.

| Variable | Default | Meaning |
| --- | --- | --- |
| `JARVIS_PROVIDER` | `ollama` | Set to `hf` to use Hugging Face. |
| `HF_TOKEN` | — | Your HF access token (`JARVIS_HF_TOKEN` also works). |
| `JARVIS_HF_MODEL` | `Qwen/Qwen2.5-7B-Instruct` | Model repo id to run. |
| `JARVIS_HF_BASE_URL` | `https://router.huggingface.co/v1` | OpenAI-compatible endpoint. |

---

## B — Host the app on a Hugging Face Space

The repo ships a `Dockerfile` that serves the web app on port `7860` with the
HF backend already selected.

1. **Create a Space:** <https://huggingface.co/new-space> → SDK **Docker** →
   *Blank*. 
2. **Add this repo's files** to the Space (push to the Space's git remote, or
   upload). Make sure `Dockerfile`, `jarvis/`, `requirements.txt`, and
   `requirements-web.txt` are present.
3. **Give the Space front matter.** A Space's `README.md` must start with a
   YAML block. Prepend this (adjust the title/emoji as you like):

   ```yaml
   ---
   title: JARVIS
   emoji: 🤖
   colorFrom: blue
   colorTo: indigo
   sdk: docker
   app_port: 7860
   pinned: false
   ---
   ```

4. **Set secrets** (Space → *Settings* → *Variables and secrets*):
   - `HF_TOKEN` — **secret**, your HF token (the brain).
   - `JARVIS_WEB_TOKEN` — **secret**, a long random string. The Space is public,
     so this gates the API; you'll enter the same value in the app's **Settings**.
   - Optional: `JARVIS_HF_MODEL`, `JARVIS_USER_NAME`, `JARVIS_NAME`.
5. **Persist memory (optional but recommended):** Space → *Settings* → enable
   **Persistent storage**, then set variable `JARVIS_DATA_DIR=/data/.jarvis`.
   Without it, conversation history and long-term memory reset whenever the
   Space restarts.

When the Space finishes building, open its URL, go to **Settings** in the app,
paste your `JARVIS_WEB_TOKEN`, and you're talking to JARVIS from anywhere —
**Add to Home Screen** to use it like a native app.

### Security notes

- A public Space with no `JARVIS_WEB_TOKEN` is open to anyone who finds the URL.
  Always set the token (or make the Space private).
- Keep `HF_TOKEN` as a **secret**, never a plain variable, so it isn't exposed.
