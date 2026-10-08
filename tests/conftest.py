"""Shared fixtures: a fake OpenAI-compatible model server and a JARVIS config."""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class FakeModel:
    """Mimics llama-server's /v1 API with scripted, streaming replies.

    Behaviour (enough to exercise the agent loop end to end):
    * a user message containing "time"  -> calls get_datetime, then answers
    * a message starting "Task goal"    -> calls web-free finish_task with a report
    * a message starting "Self-check"   -> replies DONE
    * a message containing "textcall"   -> writes the tool call as <tool_call> text
    * anything else                     -> echoes "You said: ..."
    """

    def __init__(self):
        self.requests: list[dict] = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def _handler(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = json.dumps({"data": [{"id": "fake-model.gguf"}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(n))
                fake.requests.append(payload)
                chunks = fake.script(payload)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for c in chunks:
                    self.wfile.write(f"data: {json.dumps(c)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()

        return H

    @staticmethod
    def _text(*parts):
        return [{"choices": [{"delta": {"content": p}, "index": 0}]} for p in parts]

    @staticmethod
    def _tool(name, args, call_id="call_1"):
        return [
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": call_id, "function": {"name": name, "arguments": ""}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": json.dumps(args)}}]}}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
        ]

    def script(self, payload: dict) -> list[dict]:
        msgs = payload["messages"]
        last = msgs[-1]
        system = msgs[0]["content"] if msgs and msgs[0]["role"] == "system" else ""
        if "記憶整理係" in system:
            if "要約" in system and "統合" in system:
                return self._text("要約: ユーザーはテストを続けている。")
            return self._text('{"facts": ["ユーザーの名前はゆうき", "コーヒーが好き"], "lessons": ["返事は短くする"]}')
        if "コーチ" in system:
            return self._text("長い説明はせず、結論を先に言う")
        if "振り返り係" in system:
            return self._text("まず web_search で候補を集めてから web_fetch で本文を読む")
        if last["role"] == "tool":
            if last.get("name") == "finish_task":
                return self._text("Filed.")
            return self._text("Tool said: ", last["content"][:40])
        text = last.get("content") or ""
        if text.startswith("Task goal"):
            return self._tool("finish_task", {"report": "Report for: " + text.split("\n", 1)[1]})
        if text.startswith("Self-check"):
            return self._text("DONE")
        if "textcall" in text:
            return self._text('Sure. <tool_call>{"name": "get_datetime", "arguments": {}}</tool_call>')
        if "time" in text.lower():
            return self._tool("get_datetime", {})
        return self._text("You said: ", text)


@pytest.fixture(scope="session")
def fake_model():
    fm = FakeModel()
    yield fm
    fm.stop()


@pytest.fixture
def config(tmp_path, fake_model, monkeypatch):
    for k in list(os.environ):
        if k.startswith("JARVIS_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("JARVIS_PROVIDER", "llamacpp")
    monkeypatch.setenv("JARVIS_OPENAI_BASE_URL", fake_model.base_url)
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("JARVIS_AGENT_MAX_STEPS", "6")
    monkeypatch.setenv("JARVIS_LEARN_IDLE", "0")
    from jarvis.config import Config

    return Config.load()
