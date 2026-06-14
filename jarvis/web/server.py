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
from ..persistence import HFDatasetPersistence
from ..persona import build_briefing, build_greeting
from ..push import PushClient

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
        # Free persistence: restore the snapshot before opening the database so
        # Memory/Store pick up the previous session's data.
        self.persistence = HFDatasetPersistence.from_config(config)
        if self.persistence is not None:
            self.persistence.restore()
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

        # Optional Web Push for proactive briefings; None when unconfigured.
        self.push = PushClient.from_config(config)

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
            "speech_lang": c.speech_lang,
        }

    # ── proactive opening message ──────────────────────────────────────
    def greeting(self) -> dict:
        """A templated opening line for the browser to show once per session.

        Display-only: we don't record it as a turn. The only durable change is
        marking surfaced reminders so they aren't announced again — which we
        persist via `_save()`."""
        if not self.config.greeting:
            return {"message": None, "surfaced": []}
        with self._turn_lock:
            due = self.memory.store.due()
            # Fold today's calendar agenda into the greeting when calendar is
            # configured. Reuse the assistant's client; today_events() already
            # swallows any error and returns [] so the greeting never breaks.
            events = []
            gcal = getattr(self.assistant, "gcal", None)
            if gcal is not None:
                events = gcal.today_events()
            text = build_greeting(self.config, due, events=events)
            ids = [r["id"] for r in due]
            if ids:
                self.memory.store.mark_surfaced(ids)
        if ids:
            self._save()
        return {"message": text, "surfaced": ids}

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
            self._save()  # persist the turn (and any memory/reminder changes)

    def resolve_confirm(self, cid: str, approved: bool) -> bool:
        return self._current.resolve_confirm(cid, approved)

    def _save(self) -> None:
        """Persist changed data to the HF Dataset snapshot (debounced, no-op if
        persistence isn't configured)."""
        if self.persistence is not None:
            self.persistence.request_save()

    # ── conversation threads ───────────────────────────────────────────
    # Mutations take the turn lock so a thread can't change mid-reply.
    def list_threads(self) -> list[dict]:
        return self.memory.list_threads()

    def current_thread(self) -> int:
        return self.memory.thread_id

    def new_thread(self) -> int:
        with self._turn_lock:
            tid = self.memory.new_thread()
            self.assistant.load_context()
        self._save()
        return tid

    def switch_thread(self, thread_id: int):
        with self._turn_lock:
            if not self.memory.switch_thread(thread_id):
                return None
            self.assistant.load_context()
            return self.memory.transcript()

    def delete_thread(self, thread_id: int) -> int:
        with self._turn_lock:
            self.memory.delete_thread(thread_id)
            self.assistant.load_context()
            current = self.memory.thread_id
        self._save()
        return current

    def rename_thread(self, thread_id: int, title: str) -> None:
        self.memory.rename_thread(thread_id, title)
        self._save()

    def search(self, query: str) -> list[dict]:
        return self.memory.search(query)

    # ── proactive briefing via Web Push ────────────────────────────────
    def add_push_subscription(self, sub: dict) -> None:
        """Register a browser's push subscription so we can reach it later."""
        keys = sub.get("keys") or {}
        self.memory.store.add_subscription(
            sub["endpoint"], keys["p256dh"], keys["auth"]
        )
        self._save()

    def remove_push_subscription(self, endpoint: str) -> None:
        if not endpoint:
            return
        self.memory.store.remove_subscription(endpoint)
        self._save()

    def send_briefing(self) -> dict:
        """Compose today's briefing and push it to every registered device.

        A no-op (disabled) when push isn't configured. Dead subscriptions are
        pruned, and due reminders are marked surfaced only if the briefing was
        actually delivered to at least one device — so a total delivery failure
        doesn't silently swallow them."""
        if self.push is None:
            return {"sent": 0, "pruned": 0, "disabled": True}
        with self._turn_lock:
            due = self.memory.store.due()
            gcal = getattr(self.assistant, "gcal", None)
            events = gcal.today_events() if gcal else []
            title, body = build_briefing(self.config, due, events)
            ids = [r["id"] for r in due]
            subs = self.memory.store.list_subscriptions()
        payload = json.dumps({"title": title, "body": body})
        sent = pruned = 0
        for s in subs:
            info = {
                "endpoint": s["endpoint"],
                "keys": {"p256dh": s["p256dh"], "auth": s["auth"]},
            }
            r = self.push.send(info, payload)
            if r == "gone":
                self.memory.store.remove_subscription(s["endpoint"])
                pruned += 1
            elif r is True:
                sent += 1
        if ids and sent:
            self.memory.store.mark_surfaced(ids)
        self._save()
        return {"sent": sent, "pruned": pruned, "due": len(ids), "events": len(events)}


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

    @app.get("/api/greeting")
    def api_greeting(x_jarvis_token: str | None = Header(default=None)):
        _check_token(x_jarvis_token)
        return server.greeting()

    # ── proactive briefing via Web Push ──────────────────────────────────
    @app.get("/api/push/key")
    def api_push_key(x_jarvis_token: str | None = Header(default=None)):
        _check_token(x_jarvis_token)
        return {"key": config.vapid_public_key, "enabled": server.push is not None}

    @app.post("/api/push/subscribe")
    async def api_push_subscribe(
        request: Request, x_jarvis_token: str | None = Header(default=None)
    ):
        _check_token(x_jarvis_token)
        body = await request.json()
        if not body.get("endpoint"):
            raise HTTPException(status_code=400, detail="Missing subscription endpoint.")
        server.add_push_subscription(body)
        return {"ok": True}

    @app.post("/api/push/unsubscribe")
    async def api_push_unsubscribe(
        request: Request, x_jarvis_token: str | None = Header(default=None)
    ):
        _check_token(x_jarvis_token)
        body = await request.json()
        server.remove_push_subscription((body.get("endpoint") or "").strip())
        return {"ok": True}

    @app.post("/api/briefing/send")
    def api_briefing_send(x_jarvis_token: str | None = Header(default=None)):
        _check_token(x_jarvis_token)
        return server.send_briefing()

    # ── conversation threads ────────────────────────────────────────────
    @app.get("/api/threads")
    def api_threads(x_jarvis_token: str | None = Header(default=None)):
        _check_token(x_jarvis_token)
        return {"threads": server.list_threads(), "current": server.current_thread()}

    @app.post("/api/threads/new")
    def api_threads_new(x_jarvis_token: str | None = Header(default=None)):
        _check_token(x_jarvis_token)
        return {"current": server.new_thread(), "messages": []}

    @app.post("/api/threads/switch")
    async def api_threads_switch(
        request: Request, x_jarvis_token: str | None = Header(default=None)
    ):
        _check_token(x_jarvis_token)
        body = await request.json()
        messages = server.switch_thread(int(body.get("id", 0)))
        if messages is None:
            raise HTTPException(status_code=404, detail="No such thread.")
        return {"current": server.current_thread(), "messages": messages}

    @app.post("/api/threads/rename")
    async def api_threads_rename(
        request: Request, x_jarvis_token: str | None = Header(default=None)
    ):
        _check_token(x_jarvis_token)
        body = await request.json()
        title = (body.get("title") or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="Empty title.")
        server.rename_thread(int(body.get("id", 0)), title)
        return {"ok": True}

    @app.post("/api/threads/delete")
    async def api_threads_delete(
        request: Request, x_jarvis_token: str | None = Header(default=None)
    ):
        _check_token(x_jarvis_token)
        body = await request.json()
        current = server.delete_thread(int(body.get("id", 0)))
        return {"current": current, "messages": server.memory.transcript()}

    @app.get("/api/threads/search")
    def api_threads_search(
        q: str = "", x_jarvis_token: str | None = Header(default=None)
    ):
        _check_token(x_jarvis_token)
        return {"results": server.search(q)}

    @app.post("/api/forget")
    async def api_forget(
        request: Request, x_jarvis_token: str | None = Header(default=None)
    ):
        _check_token(x_jarvis_token)
        body = await request.json()
        text = (body.get("text") or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="Nothing to forget.")
        msg = server.memory.forget(text)
        server._save()
        return {"message": msg}

    @app.post("/api/clear-history")
    def api_clear_history(x_jarvis_token: str | None = Header(default=None)):
        _check_token(x_jarvis_token)
        msg = server.memory.clear_history()
        server.assistant.reset()
        server._save()
        return {"message": msg}

    @app.on_event("shutdown")
    def _persist_on_shutdown() -> None:
        if server.persistence is not None:
            server.persistence.flush_now()

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
