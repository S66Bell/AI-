import json
import threading
import time

import requests

from jarvis.web.server import JarvisWeb, _make_handler
from http.server import ThreadingHTTPServer


def _sse(resp):
    events = []
    for raw in resp.iter_lines():
        if not raw:
            continue
        line = raw.decode()
        if line.startswith("event:"):
            events.append([line[6:].strip(), ""])
        elif line.startswith("data:") and events:
            events[-1][1] = json.loads(line[5:].strip())
    return events


class Server:
    def __init__(self, config):
        self.app = JarvisWeb(config)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(self.app))
        self.httpd.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.app.scheduler.stop()
        self.httpd.shutdown()
        self.httpd.server_close()


def test_state_and_static(config):
    srv = Server(config)
    try:
        s = requests.get(srv.url + "/api/state").json()
        assert s["ready"] is True and s["provider"] == "llamacpp"
        assert s["model"] == "fake-model.gguf"  # adopted from the server
        assert "JARVIS" in requests.get(srv.url + "/").text
        assert requests.get(srv.url + "/manifest.webmanifest").status_code == 200
        assert requests.get(srv.url + "/icon-192.png").headers["Content-Type"] == "image/png"
        assert requests.get(srv.url + "/../etc/passwd").status_code == 404
    finally:
        srv.close()


def test_chat_streams_and_runs_tools(config, fake_model):
    srv = Server(config)
    try:
        r = requests.post(srv.url + "/api/chat", json={"message": "what time is it?"}, stream=True)
        events = _sse(r)
        kinds = [e[0] for e in events]
        assert "status" in kinds and any(e[1] == "using get_datetime" for e in events if e[0] == "status")
        assert "text" in kinds
        done = [e for e in events if e[0] == "done"][0][1]
        assert done["reply"].startswith("Tool said:")
        # The tool result went back to the model in OpenAI format.
        tool_msgs = [m for m in fake_model.requests[-1]["messages"] if m["role"] == "tool"]
        assert tool_msgs and tool_msgs[0]["tool_call_id"] == "call_1"
        # History persisted for the UI.
        rows = requests.get(srv.url + "/api/history").json()["rows"]
        assert [x["role"] for x in rows] == ["user", "assistant"]
    finally:
        srv.close()


def test_chat_parses_text_tool_calls(config):
    srv = Server(config)
    try:
        r = requests.post(srv.url + "/api/chat", json={"message": "textcall please"}, stream=True)
        events = _sse(r)
        assert any(e[1] == "using get_datetime" for e in events if e[0] == "status")
    finally:
        srv.close()


def test_background_task_runs_to_done(config):
    srv = Server(config)
    try:
        t = requests.post(srv.url + "/api/tasks", json={"goal": "find something"}).json()["task"]
        deadline = time.time() + 15
        while time.time() < deadline:
            task = requests.get(srv.url + f"/api/tasks/{t['id']}").json()["task"]
            if task["status"] in ("done", "failed", "cancelled"):
                break
            time.sleep(0.1)
        assert task["status"] == "done", task
        assert task["result"] == "Report for: find something"
        assert any(e["kind"] == "status" and e["text"] == "self-check" for e in task["log"])
        # The result is surfaced to the chat as a note.
        rows = requests.get(srv.url + "/api/history").json()["rows"]
        assert "Background task finished" in rows[-1]["text"]
        assert requests.post(srv.url + "/api/tasks", json={"goal": ""}).status_code == 400
    finally:
        srv.close()


def test_schedules_api(config):
    srv = Server(config)
    try:
        s = requests.post(srv.url + "/api/schedules", json={"goal": "morning news", "daily_at": "07:00"}).json()["schedule"]
        assert s["describe"] == "daily at 07:00"
        assert requests.post(srv.url + f"/api/schedules/{s['id']}/toggle").json()["schedule"]["enabled"] is False
        t = requests.post(srv.url + f"/api/schedules/{s['id']}/run").json()["task"]
        assert t["source"] == f"schedule:{s['id']}"
        assert requests.delete(srv.url + f"/api/schedules/{s['id']}").json()["ok"] is True
        assert requests.get(srv.url + "/api/schedules").json()["schedules"] == []
    finally:
        srv.close()


def test_token_protects_api(config, monkeypatch):
    config.web_token = "secret"
    srv = Server(config)
    try:
        assert requests.get(srv.url + "/api/state").status_code == 401
        assert requests.get(srv.url + "/api/state?token=secret").status_code == 200
        assert requests.get(srv.url + "/api/state", headers={"Authorization": "Bearer secret"}).status_code == 200
        assert requests.get(srv.url + "/").status_code == 200  # the shell itself is public
    finally:
        srv.close()


def test_confirm_round_trip(config):
    """A risky shell command asks the phone and runs only when approved."""
    from jarvis.tools.shell import _run_shell
    from jarvis.tools import ToolContext
    from jarvis.memory import Memory

    app = JarvisWeb(config)
    seen = {}

    class Sink:
        def event(self, name, data):
            if name == "confirm":
                seen.update(data)
                threading.Thread(target=lambda: app.answer_confirm(data["id"], True)).start()

    app._sink_local.sink = Sink()
    ctx = ToolContext(config=config, memory=Memory(config.data_dir), confirm=app._confirm, notify=lambda m: None)
    out = _run_shell({"command": "echo hi && sudo -n true || true"}, ctx)
    assert "question" in seen and "hi" in out
    app.scheduler.stop()
