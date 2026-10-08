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

import hmac
import ipaddress
import json
import mimetypes
import queue
import ssl
import threading
import time
import uuid
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .. import __version__
from ..agent import TaskRunner
from ..assistant import Assistant
from ..config import Config
from ..learning import Learner
from ..memory import Memory
from ..scheduler import Scheduler

STATIC_DIR = Path(__file__).parent / "static"
CONFIRM_TIMEOUT = 180.0  # seconds to wait for a yes/no from the phone
MAX_BODY = 1_000_000  # bytes; nothing the UI sends is anywhere near this
AUTH_MAX_FAILURES = 10  # wrong tokens from one address before a lockout
AUTH_LOCKOUT = 600.0  # seconds
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), geolocation=(), payment=()",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    ),
}


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
        self.memory = memory or Memory(config.data_dir, history_turns=config.history_turns)
        self.log_path = config.data_dir / "web.log"
        self.runner = TaskRunner(config, self.memory)
        self.scheduler = Scheduler(self.runner, config.data_dir)
        self.scheduler.start()
        self.learner = Learner(
            config, self.memory, log=self.log, busy=lambda: self._chat_lock.locked()
        )
        self._turn_started: float | None = None

        self.assistant: Assistant | None = None
        self.backend_error: str | None = None
        self._chat_lock = threading.Lock()
        self._cancel_requested = False
        self._sink_local = threading.local()
        self._pending: dict[str, dict] = {}
        self._pending_lock = threading.Lock()
        self._event_clients: list[queue.Queue] = []
        self._event_lock = threading.Lock()
        self.runner.subscribe(self._on_task_event)
        # Security: allowed client networks and per-address auth lockout.
        self._allowed_nets = []
        for cidr in config.web_allow:
            try:
                self._allowed_nets.append(ipaddress.ip_network(cidr, strict=False))
            except ValueError:
                self.log(f"ignoring bad JARVIS_WEB_ALLOW entry: {cidr!r}")
        self._auth_failures: dict[str, list] = {}  # ip -> [count, locked_until]
        self._auth_lock = threading.Lock()

    # ── security helpers ───────────────────────────────────────────────
    def client_allowed(self, ip: str) -> bool:
        if not self._allowed_nets:
            return True
        try:
            addr = ipaddress.ip_address(ip.split("%")[0])
        except ValueError:
            return False
        if addr.version == 6 and addr.ipv4_mapped:
            addr = addr.ipv4_mapped
        return any(addr in net for net in self._allowed_nets)

    def token_ok(self, presented: str | None) -> bool:
        token = self.config.web_token
        if not token:
            return True
        return bool(presented) and hmac.compare_digest(presented.encode(), token.encode())

    def auth_locked(self, ip: str) -> bool:
        with self._auth_lock:
            entry = self._auth_failures.get(ip)
            if not entry:
                return False
            if entry[1] and time.monotonic() < entry[1]:
                return True
            if entry[1] and time.monotonic() >= entry[1]:
                del self._auth_failures[ip]
            return False

    def auth_failed(self, ip: str) -> None:
        with self._auth_lock:
            entry = self._auth_failures.setdefault(ip, [0, 0.0])
            entry[0] += 1
            if entry[0] >= AUTH_MAX_FAILURES:
                entry[1] = time.monotonic() + AUTH_LOCKOUT
                self.log(f"auth lockout for {ip} after {entry[0]} bad tokens")

    def auth_succeeded(self, ip: str) -> None:
        with self._auth_lock:
            self._auth_failures.pop(ip, None)

    def log(self, msg: str) -> None:
        """Append a timestamped line to ~/.jarvis/web.log (for doctor.sh)."""
        try:
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"{datetime.now().isoformat(timespec='seconds')} {msg}\n")
        except OSError:
            pass

    # ── assistant wiring ───────────────────────────────────────────────
    def _sink(self) -> _Sink | None:
        return getattr(self._sink_local, "sink", None)

    def _emit(self, chunk: str) -> None:
        sink = self._sink()
        if sink:
            sink.event("text", chunk)

    def _notify(self, msg: str) -> None:
        self.log(f"  {msg}")
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
                learner=self.learner,
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
        started = time.monotonic()
        self._turn_started = started
        if self.config.log_messages:
            self.log(f"chat start: {message[:80]!r}")
        else:
            self.log(f"chat start ({len(message)} chars)")
        try:
            self._sink_local.sink = sink
            assistant = self.ensure_assistant()
            if assistant is None:
                self.log(f"chat failed: backend unavailable: {self.backend_error}")
                sink.event("error", self.backend_error or "Model backend unavailable.")
                sink.event("done", {"reply": ""})
                return
            self.learner.yield_to_chat()
            assistant.backend.should_stop = lambda: self._cancel_requested
            assistant.backend.debug_log = self.log
            self._cancel_requested = False
            try:
                reply = assistant.chat(message)
                self.log(f"chat done in {time.monotonic() - started:.1f}s ({len(reply)} chars)")
                sink.event("done", {"reply": reply})
            except Exception as exc:
                self.log(f"chat error after {time.monotonic() - started:.1f}s: {type(exc).__name__}: {exc}")
                if self._cancel_requested:
                    sink.event("error", "止めたよ。")
                else:
                    sink.event("error", f"{type(exc).__name__}: {exc}")
                sink.event("done", {"reply": ""})
        finally:
            self._sink_local.sink = None
            self._turn_started = None
            self._chat_lock.release()

    def cancel_chat(self) -> bool:
        """Stop the turn in progress (closes the model stream)."""
        if not self._chat_lock.locked():
            return False
        self._cancel_requested = True
        if self.assistant is not None:
            self.assistant.backend.cancel()
        self.log("chat cancel requested")
        return True

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
            "busy_seconds": round(time.monotonic() - self._turn_started) if self._turn_started else 0,
            "learning": self.learner.last_result,
            "version": __version__,
            "auth": bool(self.config.web_token),
        }

    # ── serve ──────────────────────────────────────────────────────────
    def serve(self, host: str | None = None, port: int | None = None) -> None:
        host = host or self.config.web_host
        port = port or self.config.web_port
        handler = _make_handler(self)
        server = _QuietServer((host, port), handler)
        server.daemon_threads = True
        scheme = "http"
        if self.config.web_cert and self.config.web_key:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.load_cert_chain(self.config.web_cert, self.config.web_key)
            server.socket = ctx.wrap_socket(server.socket, server_side=True)
            scheme = "https"
        shown = "localhost" if host in ("127.0.0.1", "0.0.0.0", "") else host
        print(f"{self.config.assistant_name} web UI: {scheme}://{shown}:{port}/")
        if host == "0.0.0.0" and not self.config.web_token:
            print("  warning: listening on all interfaces without JARVIS_WEB_TOKEN set")
        if self.config.fs_root == Path("/"):
            print("  note: file tools are unrestricted (JARVIS_FS_ROOT=/)")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self.scheduler.stop()
            server.server_close()


class _QuietServer(ThreadingHTTPServer):
    """Don't print a traceback every time a phone browser drops a connection."""

    def handle_error(self, request, client_address):
        import sys

        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def _make_handler(app: JarvisWeb):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "MIRA/" + __version__

        def log_message(self, fmt, *args):  # keep the phone's terminal quiet
            return

        def end_headers(self):
            for k, v in SECURITY_HEADERS.items():
                self.send_header(k, v)
            super().end_headers()

        def _client_ip(self) -> str:
            return self.client_address[0]

        def _gate(self, query: dict, *, api: bool, allow_query_token: bool = False) -> bool:
            """Network allowlist, lockout and token check. Sends the error itself."""
            ip = self._client_ip()
            if not app.client_allowed(ip):
                self._json(HTTPStatus.FORBIDDEN, {"error": "this network is not allowed"})
                return False
            if not api:
                return True
            if app.auth_locked(ip):
                self._json(HTTPStatus.TOO_MANY_REQUESTS, {"error": "too many bad tokens; try later"})
                return False
            header = self.headers.get("Authorization", "")
            presented = header[7:] if header.startswith("Bearer ") else None
            if presented is None and allow_query_token:
                presented = query.get("token", [None])[0]
            if app.token_ok(presented):
                app.auth_succeeded(ip)
                return True
            app.auth_failed(ip)
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "token required"})
            return False

        # ── helpers ──────────────────────────────────────────────────
        def _json(self, status: int, payload) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # the browser went away (screen off, tab closed); nothing to do

        def _read_json(self) -> dict | None:
            """Parse the JSON body; None means the request was rejected."""
            ctype = self.headers.get("Content-Type", "")
            if not ctype.lower().startswith("application/json"):
                self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "send application/json"})
                return None
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "body too large"})
                return None
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            try:
                data = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return {}
            return data if isinstance(data, dict) else {}

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
            self.send_header("Cache-Control", "no-store" if path.suffix in (".html", ".js") else "no-cache")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        # ── routing ──────────────────────────────────────────────────
        def do_GET(self) -> None:
            url = urlparse(self.path)
            query = parse_qs(url.query)
            path = url.path

            if path in ("/", "/index.html"):
                return self._gate(query, api=False) and self._static("index.html")
            if path in ("/manifest.webmanifest", "/sw.js", "/icon-192.png", "/icon-512.png", "/icon.svg"):
                return self._gate(query, api=False) and self._static(path.lstrip("/"))

            if not path.startswith("/api/"):
                return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            # EventSource can't send headers, so /api/events may carry the token in the query.
            if not self._gate(query, api=True, allow_query_token=(path == "/api/events")):
                return None

            if path == "/api/state":
                return self._json(HTTPStatus.OK, app.state())
            if path == "/api/history":
                limit = int(query.get("limit", ["60"])[0])
                return self._json(HTTPStatus.OK, {"rows": app.memory.recent_rows(limit)})
            if path == "/api/memory":
                return self._json(
                    HTTPStatus.OK,
                    {"facts": app.memory.load_facts(), "summary": app.memory.load_summary()},
                )
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
            if not self._gate(query, api=True):
                return None
            body = self._read_json()
            if body is None:
                return None

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
            if path == "/api/chat/cancel":
                return self._json(HTTPStatus.OK, {"ok": app.cancel_chat()})
            if path == "/api/learn":
                app.learner.request("reflect")
                return self._json(HTTPStatus.OK, {"ok": True})
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
            if not self._gate(query, api=True):
                return None
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
