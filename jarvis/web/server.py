"""A dependency-free HTTP server for the phone UI.

Built on the standard library only (``http.server``) so it installs on
Android/Termux without compiling anything. It serves the single-page app in
``static/`` and a small JSON/SSE API:

    GET  /api/state                  who's running, which model, busy?
    POST /api/chat        {message}  one chat turn, streamed as SSE events
    POST /api/confirm     {id, approved}
    POST /api/reset
    GET  /api/history
    GET  /api/memory · POST /api/memory {fact} · POST /api/memory/forget {query}
    GET  /api/tasks · POST /api/tasks {goal} · GET /api/tasks/<id> · POST /api/tasks/<id>/cancel
    GET  /api/schedules · POST /api/schedules {goal, every_minutes | daily_at}
    POST /api/schedules/<id>/toggle · POST /api/schedules/<id>/run · DELETE /api/schedules/<id>
    GET  /api/events                 live task progress (SSE)

Chat streaming uses Server-Sent Events over a POST so a single request carries
the whole turn; tool confirmations arrive as ``confirm`` events and are
answered through ``/api/confirm``.
"""

from __future__ import annotations

import json
import mimetypes
import queue
import threading
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .. import __version__
from ..agent import TaskRunner
from ..assistant import Assistant
from ..config import Config
from ..memory import Memory
from ..scheduler import Scheduler

STATIC_DIR = Path(__file__).parent / "static"
CONFIRM_TIMEOUT = 180.0  # seconds to wait for a yes/no from the phone


class _Sink:
    """Where one chat request's streamed output goes."""

    def __init__(self, write):
        self._write = write
        self.lock = threading.Lock()

    def event(self, name: str, data) -> None:
        with self.lock:
            self._write(name, data)


class JarvisWeb:
    def __init__(self, config: Config, memory: Memory | None = None):
        self.config = config
        self.memory = memory or Memory(config.data_dir)
        self.runner = TaskRunner(config, self.memory)
        self.scheduler = Scheduler(self.runner, config.data_dir)
        self.scheduler.start()

        self.assistant: Assistant | None = None
        self.backend_error: str | None = None
        self._chat_lock = threading.Lock()
        self._sink_local = threading.local()
        self._pending: dict[str, dict] = {}
        self._pending_lock = threading.Lock()
        self._event_clients: list[queue.Queue] = []
        self._event_lock = threading.Lock()
        self.runner.subscribe(self._on_task_event)

    # ── assistant wiring ───────────────────────────────────────────────
    def _sink(self) -> _Sink | None:
        return getattr(self._sink_local, "sink", None)

    def _emit(self, chunk: str) -> None:
        sink = self._sink()
        if sink:
            sink.event("text", chunk)

    def _notify(self, msg: str) -> None:
        sink = self._sink()
        if sink:
            sink.event("status", msg)

    def _thinking(self, chunk: str) -> None:
        sink = self._sink()
        if sink:
            sink.event("thinking", chunk)

    def _confirm(self, question: str) -> bool:
        sink = self._sink()
        if sink is None:
            return False
        cid = uuid.uuid4().hex[:8]
        waiter = {"event": threading.Event(), "answer": False}
        with self._pending_lock:
            self._pending[cid] = waiter
        sink.event("confirm", {"id": cid, "question": question})
        waiter["event"].wait(CONFIRM_TIMEOUT)
        with self._pending_lock:
            self._pending.pop(cid, None)
        return bool(waiter["answer"])

    def answer_confirm(self, cid: str, approved: bool) -> bool:
        with self._pending_lock:
            waiter = self._pending.get(cid)
        if waiter is None:
            return False
        waiter["answer"] = approved
        waiter["event"].set()
        return True

    def ensure_assistant(self) -> Assistant | None:
        if self.assistant is not None:
            return self.assistant
        try:
            self.assistant = Assistant(
                self.config,
                self.memory,
                emit=self._emit,
                confirm=self._confirm,
                notify=self._notify,
                on_thinking=self._thinking if self.config.show_thinking else None,
                runner=self.runner,
            )
            self.backend_error = None
        except Exception as exc:  # model server down, model missing, ...
            self.backend_error = str(exc)
            self.assistant = None
        return self.assistant

    # ── chat ───────────────────────────────────────────────────────────
    def chat(self, message: str, sink: _Sink) -> None:
        if not self._chat_lock.acquire(blocking=False):
            sink.event("error", "まだ前のメッセージに返事してる途中だよ。ちょっと待ってね。")
            sink.event("done", {"reply": ""})
            return
        try:
            self._sink_local.sink = sink
            assistant = self.ensure_assistant()
            if assistant is None:
                sink.event("error", self.backend_error or "Model backend unavailable.")
                sink.event("done", {"reply": ""})
                return
            try:
                reply = assistant.chat(message)
                sink.event("done", {"reply": reply})
            except Exception as exc:
                sink.event("error", f"{type(exc).__name__}: {exc}")
                sink.event("done", {"reply": ""})
        finally:
            self._sink_local.sink = None
            self._chat_lock.release()

    def reset(self) -> None:
        if self.assistant is not None:
            self.assistant.reset()

    # ── task event fan-out ─────────────────────────────────────────────
    def _on_task_event(self, task, event: dict) -> None:
        payload = {"task": task.to_dict(with_log=False), "event": event}
        with self._event_lock:
            clients = list(self._event_clients)
        for q in clients:
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass

    def subscribe_events(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=500)
        with self._event_lock:
            self._event_clients.append(q)
        return q

    def unsubscribe_events(self, q: queue.Queue) -> None:
        with self._event_lock:
            if q in self._event_clients:
                self._event_clients.remove(q)

    # ── state ──────────────────────────────────────────────────────────
    def state(self) -> dict:
        assistant = self.ensure_assistant()
        ready = assistant is not None
        model = self.config.active_model
        if ready:
            # The llama.cpp backend adopts whatever the server is serving.
            model = getattr(assistant.backend, "model", model)
        return {
            "name": self.config.assistant_name,
            "user_name": self.config.user_name,
            "provider": self.config.provider,
            "model": model,
            "ready": ready,
            "error": self.backend_error,
            "busy": self._chat_lock.locked(),
            "version": __version__,
            "auth": bool(self.config.web_token),
        }

    # ── serve ──────────────────────────────────────────────────────────
    def serve(self, host: str | None = None, port: int | None = None) -> None:
        host = host or self.config.web_host
        port = port or self.config.web_port
        handler = _make_handler(self)
        server = ThreadingHTTPServer((host, port), handler)
        server.daemon_threads = True
        shown = "localhost" if host in ("127.0.0.1", "0.0.0.0", "") else host
        print(f"{self.config.assistant_name} web UI: http://{shown}:{port}/")
        if host == "0.0.0.0" and not self.config.web_token:
            print("  warning: listening on all interfaces without JARVIS_WEB_TOKEN set")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self.scheduler.stop()
            server.server_close()


def _make_handler(app: JarvisWeb):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "MIRA/" + __version__

        def log_message(self, fmt, *args):  # keep the phone's terminal quiet
            return

        # ── helpers ──────────────────────────────────────────────────
        def _json(self, status: int, payload) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            try:
                data = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return {}
            return data if isinstance(data, dict) else {}

        def _authorised(self, query: dict) -> bool:
            token = app.config.web_token
            if not token:
                return True
            header = self.headers.get("Authorization", "")
            if header == f"Bearer {token}":
                return True
            if query.get("token", [""])[0] == token:
                return True
            cookie = self.headers.get("Cookie", "")
            return f"jarvis_token={token}" in cookie

        def _start_sse(self) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()

        def _sse(self, name: str, data) -> None:
            body = json.dumps(data, ensure_ascii=False)
            self.wfile.write(f"event: {name}\ndata: {body}\n\n".encode("utf-8"))
            self.wfile.flush()

        def _static(self, name: str) -> None:
            path = (STATIC_DIR / name).resolve()
            if not str(path).startswith(str(STATIC_DIR.resolve())) or not path.is_file():
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            ctype = {
                ".webmanifest": "application/manifest+json",
                ".js": "text/javascript; charset=utf-8",
                ".html": "text/html; charset=utf-8",
                ".svg": "image/svg+xml",
            }.get(path.suffix) or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            body = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        # ── routing ──────────────────────────────────────────────────
        def do_GET(self) -> None:
            url = urlparse(self.path)
            query = parse_qs(url.query)
            path = url.path

            if path in ("/", "/index.html"):
                return self._static("index.html")
            if path in ("/manifest.webmanifest", "/sw.js", "/icon-192.png", "/icon-512.png", "/icon.svg"):
                return self._static(path.lstrip("/"))

            if not path.startswith("/api/"):
                return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            if not self._authorised(query):
                return self._json(HTTPStatus.UNAUTHORIZED, {"error": "token required"})

            if path == "/api/state":
                return self._json(HTTPStatus.OK, app.state())
            if path == "/api/history":
                limit = int(query.get("limit", ["60"])[0])
                return self._json(HTTPStatus.OK, {"rows": app.memory.recent_rows(limit)})
            if path == "/api/memory":
                return self._json(HTTPStatus.OK, {"facts": app.memory.load_facts()})
            if path == "/api/tasks":
                limit = int(query.get("limit", ["50"])[0])
                return self._json(
                    HTTPStatus.OK,
                    {"tasks": [t.to_dict(with_log=False) for t in app.runner.list(limit)]},
                )
            if path.startswith("/api/tasks/"):
                task = app.runner.get(path.split("/")[3])
                if task is None:
                    return self._json(HTTPStatus.NOT_FOUND, {"error": "no such task"})
                return self._json(HTTPStatus.OK, {"task": task.to_dict()})
            if path == "/api/schedules":
                return self._json(
                    HTTPStatus.OK, {"schedules": [s.to_dict() for s in app.scheduler.list()]}
                )
            if path == "/api/events":
                return self._events()
            return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:
            url = urlparse(self.path)
            query = parse_qs(url.query)
            path = url.path
            if not path.startswith("/api/"):
                return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            if not self._authorised(query):
                return self._json(HTTPStatus.UNAUTHORIZED, {"error": "token required"})
            body = self._read_json()

            if path == "/api/chat":
                message = str(body.get("message", "")).strip()
                if not message:
                    return self._json(HTTPStatus.BAD_REQUEST, {"error": "empty message"})
                self._start_sse()
                sink = _Sink(self._sse)
                try:
                    app.chat(message, sink)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                return
            if path == "/api/confirm":
                ok = app.answer_confirm(str(body.get("id", "")), bool(body.get("approved")))
                return self._json(HTTPStatus.OK if ok else HTTPStatus.NOT_FOUND, {"ok": ok})
            if path == "/api/reset":
                app.reset()
                return self._json(HTTPStatus.OK, {"ok": True})
            if path == "/api/clear-history":
                app.memory.clear_history()
                app.reset()
                return self._json(HTTPStatus.OK, {"ok": True})
            if path == "/api/memory":
                fact = str(body.get("fact", "")).strip()
                if not fact:
                    return self._json(HTTPStatus.BAD_REQUEST, {"error": "empty fact"})
                return self._json(HTTPStatus.OK, {"message": app.memory.remember(fact)})
            if path == "/api/memory/forget":
                q = str(body.get("query", "")).strip()
                if not q:
                    return self._json(HTTPStatus.BAD_REQUEST, {"error": "empty query"})
                return self._json(HTTPStatus.OK, {"message": app.memory.forget(q)})
            if path == "/api/tasks":
                try:
                    task = app.runner.submit(str(body.get("goal", "")), source="manual")
                except ValueError as exc:
                    return self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return self._json(HTTPStatus.OK, {"task": task.to_dict(with_log=False)})
            if path.startswith("/api/tasks/") and path.endswith("/cancel"):
                ok = app.runner.cancel(path.split("/")[3])
                return self._json(HTTPStatus.OK if ok else HTTPStatus.NOT_FOUND, {"ok": ok})
            if path == "/api/schedules":
                try:
                    every = body.get("every_minutes")
                    sched = app.scheduler.add(
                        str(body.get("goal", "")),
                        every_minutes=int(every) if every else None,
                        daily_at=(str(body.get("daily_at") or "").strip() or None),
                    )
                except (ValueError, TypeError) as exc:
                    return self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return self._json(HTTPStatus.OK, {"schedule": sched.to_dict()})
            if path.startswith("/api/schedules/"):
                parts = path.split("/")
                sid, action = parts[3], (parts[4] if len(parts) > 4 else "")
                if action == "toggle":
                    current = next((s for s in app.scheduler.list() if s.id == sid), None)
                    if current is None:
                        return self._json(HTTPStatus.NOT_FOUND, {"error": "no such schedule"})
                    sched = app.scheduler.set_enabled(sid, not current.enabled)
                    return self._json(HTTPStatus.OK, {"schedule": sched.to_dict()})
                if action == "run":
                    task = app.scheduler.run_now(sid)
                    if task is None:
                        return self._json(HTTPStatus.NOT_FOUND, {"error": "no such schedule"})
                    return self._json(HTTPStatus.OK, {"task": task.to_dict(with_log=False)})
            return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_DELETE(self) -> None:
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if not self._authorised(query):
                return self._json(HTTPStatus.UNAUTHORIZED, {"error": "token required"})
            if url.path.startswith("/api/schedules/"):
                ok = app.scheduler.remove(url.path.split("/")[3])
                return self._json(HTTPStatus.OK if ok else HTTPStatus.NOT_FOUND, {"ok": ok})
            return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def _events(self) -> None:
            q = app.subscribe_events()
            self._start_sse()
            try:
                self._sse("hello", {"ok": True})
                while True:
                    try:
                        payload = q.get(timeout=15)
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                        continue
                    self._sse("task", payload)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                app.unsubscribe_events(q)

    return Handler


def serve(config: Config, host: str | None = None, port: int | None = None) -> None:
    JarvisWeb(config).serve(host, port)
