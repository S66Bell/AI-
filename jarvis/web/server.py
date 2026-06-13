"""HTTP API + PWA host for JARVIS.

The terminal CLI talks to the `Assistant` through four callbacks — `emit`
(stream reply text), `notify` (status lines), `on_thinking` (reasoning), and
`confirm` (gate destructive actions). This server wires those same callbacks to
a per-turn *channel* whose events are streamed to the browser as newline-
delimited JSON, and whose confirmations are answered by a second request from
the phone. The `Assistant`, backends, memory, and tools are reused unchanged.

It is a single-user server by design (it's *your* JARVIS, with your shell on
your machine): one assistant, one turn at a time, guarded by a lock. Put it
behind a token (`JARVIS_WEB_TOKEN`) before exposing it beyond your LAN.
"""

from __future__ import annotations

import json
import queue
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ..assistant import Assistant
from ..config import Config
from ..memory import Memory

STATIC_DIR = Path(__file__).parent / "static"

# Sentinel pushed onto a channel's queue to end its event stream.
_END = object()


class Channel:
    """One live turn's bridge between the (blocking) assistant thread and the
    (streaming) HTTP response. Assistant callbacks run on the worker thread and
    push events here; the response generator drains them in order."""

    def __init__(self) -> None:
        self.q: "queue.Queue" = queue.Queue()
        self._confirm_event = threading.Event()
        self._confirm_answer = False
        self._confirm_id: str | None = None

    # ── assistant-facing callbacks (worker thread) ─────────────────────
    def emit(self, text: str) -> None:
        if text:
            self.q.put({"type": "text", "data": text})

    def status(self, msg: str) -> None:
        self.q.put({"type": "status", "data": msg})

    def thinking(self, chunk: str) -> None:
        if chunk:
            self.q.put({"type": "thinking", "data": chunk})

    def confirm(self, question: str) -> bool:
        """Ask the phone to approve a destructive action and block until it
        answers (or the connection is torn down)."""
        cid = uuid.uuid4().hex
        self._confirm_id = cid
        self._confirm_answer = False
        self._confirm_event.clear()
        self.q.put({"type": "confirm", "id": cid, "data": question})
        self._confirm_event.wait()
        return self._confirm_answer

    def error(self, msg: str) -> None:
        self.q.put({"type": "error", "data": msg})

    def finish(self) -> None:
        self.q.put({"type": "done"})
        self.q.put(_END)

    # ── client-facing (other request threads) ─────────────────────────
    def resolve_confirm(self, cid: str, approved: bool) -> bool:
        if cid and cid == self._confirm_id and not self._confirm_event.is_set():
            self._confirm_answer = approved
            self._confirm_event.set()
            return True
        return False

    def abort(self) -> None:
        """Unblock a pending confirmation (treated as a decline) on shutdown."""
        if not self._confirm_event.is_set():
            self._confirm_answer = False
            self._confirm_event.set()


class _NullChannel(Channel):
    """No-op stand-in so a stray callback outside a turn can never crash."""

    def confirm(self, question: str) -> bool:  # pragma: no cover - defensive
        return False


class JarvisServer:
    """Holds the single shared assistant and serializes turns."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.memory = Memory(config.data_dir)
        self.show_thinking = config.show_thinking
        self._turn_lock = threading.Lock()
        self._current: Channel = _NullChannel()

        self.assistant = Assistant(
            config,
            self.memory,
            emit=lambda t: self._current.emit(t),
            confirm=lambda q: self._current.confirm(q),
            notify=lambda m: self._current.status(m),
            on_thinking=lambda c: self._current.thinking(c) if self.show_thinking else None,
        )

    # ── info / banner ──────────────────────────────────────────────────
    def info(self) -> dict:
        c = self.config
        if c.is_local:
            backend = f"local · {c.active_model} (offline-capable)"
        elif c.is_hf:
            backend = f"Hugging Face · {c.active_model}"
        else:
            backend = f"Claude · {c.active_model} · effort: {c.effort}"
        return {
            "assistant_name": c.assistant_name,
            "user_name": c.user_name,
            "backend": backend,
            "show_thinking": self.show_thinking,
        }

    # ── one streamed turn ──────────────────────────────────────────────
    def run_turn(self, message: str):
        """Generator yielding NDJSON event lines for a single user turn."""
        channel = Channel()
        # One turn at a time; the lock is held for the whole stream so an
        # in-flight confirmation can't be interleaved with a new request.
        self._turn_lock.acquire()
        self._current = channel

        def worker() -> None:
            try:
                self.assistant.chat(message)
            except Exception as exc:  # surface, don't crash the stream
                channel.error(f"{type(exc).__name__}: {exc}")
            finally:
                channel.finish()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        try:
            while True:
                item = channel.q.get()
                if item is _END:
                    break
                yield json.dumps(item, ensure_ascii=False) + "\n"
        finally:
            # If the client vanished mid-confirmation, release the worker.
            channel.abort()
            thread.join(timeout=1.0)
            self._current = _NullChannel()
            self._turn_lock.release()

    def resolve_confirm(self, cid: str, approved: bool) -> bool:
        return self._current.resolve_confirm(cid, approved)


def create_app(config: Config) -> FastAPI:
    server = JarvisServer(config)
    app = FastAPI(title="JARVIS", docs_url=None, redoc_url=None)

    def _check_token(token: str | None) -> None:
        if config.web_token and token != config.web_token:
            raise HTTPException(status_code=401, detail="Invalid or missing token.")

    # ── API ────────────────────────────────────────────────────────────
    @app.get("/api/info")
    def api_info(x_jarvis_token: str | None = Header(default=None)):
        _check_token(x_jarvis_token)
        return server.info()

    @app.post("/api/chat")
    async def api_chat(
        request: Request, x_jarvis_token: str | None = Header(default=None)
    ):
        _check_token(x_jarvis_token)
        body = await request.json()
        message = (body.get("message") or "").strip()
        if not message:
            raise HTTPException(status_code=400, detail="Empty message.")
        return StreamingResponse(
            server.run_turn(message),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/confirm")
    async def api_confirm(
        request: Request, x_jarvis_token: str | None = Header(default=None)
    ):
        _check_token(x_jarvis_token)
        body = await request.json()
        ok = server.resolve_confirm(
            body.get("id", ""), bool(body.get("approved", False))
        )
        return {"resolved": ok}

    @app.post("/api/reset")
    def api_reset(x_jarvis_token: str | None = Header(default=None)):
        _check_token(x_jarvis_token)
        server.assistant.reset()
        return {"ok": True}

    @app.get("/api/memory")
    def api_memory(x_jarvis_token: str | None = Header(default=None)):
        _check_token(x_jarvis_token)
        return {"facts": server.memory.load_facts()}

    @app.get("/api/history")
    def api_history(x_jarvis_token: str | None = Header(default=None)):
        _check_token(x_jarvis_token)
        return {"messages": server.memory.transcript()}

    @app.post("/api/forget")
    async def api_forget(
        request: Request, x_jarvis_token: str | None = Header(default=None)
    ):
        _check_token(x_jarvis_token)
        body = await request.json()
        text = (body.get("text") or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="Nothing to forget.")
        return {"message": server.memory.forget(text)}

    @app.post("/api/clear-history")
    def api_clear_history(x_jarvis_token: str | None = Header(default=None)):
        _check_token(x_jarvis_token)
        msg = server.memory.clear_history()
        server.assistant.reset()
        return {"message": msg}

    @app.post("/api/thinking")
    def api_thinking(x_jarvis_token: str | None = Header(default=None)):
        _check_token(x_jarvis_token)
        server.show_thinking = not server.show_thinking
        return {"show_thinking": server.show_thinking}

    # ── PWA shell ──────────────────────────────────────────────────────
    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/manifest.webmanifest")
    def manifest():
        return FileResponse(
            STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json"
        )

    @app.get("/service-worker.js")
    def service_worker():
        # Served from the root so its scope covers the whole app.
        return FileResponse(
            STATIC_DIR / "service-worker.js", media_type="text/javascript"
        )

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
