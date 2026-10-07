"""Local LLM backend via Ollama.

This is what makes JARVIS independent: it talks to a model running entirely on
your own machine through Ollama (https://ollama.com). No API keys, no usage
fees, no calls to Claude or OpenAI — once the model is pulled, it works fully
offline.

Ollama exposes an OpenAI-style chat endpoint at /api/chat with streaming and
tool-calling support. We drive the same agentic loop as the Claude backend:
stream the reply, run any tool calls locally, feed results back, repeat.
"""

from __future__ import annotations

import json

import requests

from .base import Backend
from .tool_calls import extract_text_tool_calls, parse_arguments


class OllamaError(RuntimeError):
    pass


class OllamaBackend(Backend):
    name = "ollama"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.host = self.config.ollama_host.rstrip("/")
        self.model = self.config.ollama_model
        self._check_ready()

    # ── readiness ──────────────────────────────────────────────────────
    def _check_ready(self) -> None:
        """Fail early with a helpful message if Ollama or the model is missing."""
        try:
            resp = requests.get(f"{self.host}/api/tags", timeout=5)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise OllamaError(
                f"Can't reach Ollama at {self.host}. Is it running?\n"
                f"  • Install:  https://ollama.com/download\n"
                f"  • Start it, then pull a model:  ollama pull {self.model}\n"
                f"  (underlying error: {exc})"
            ) from exc

        installed = {m.get("name", "") for m in resp.json().get("models", [])}
        # Names look like "qwen2.5:7b"; also accept a bare family match.
        if self.model not in installed and not any(
            name.split(":")[0] == self.model.split(":")[0] for name in installed
        ):
            raise OllamaError(
                f"Model '{self.model}' isn't installed in Ollama.\n"
                f"  Pull it with:  ollama pull {self.model}\n"
                f"  (installed: {', '.join(sorted(installed)) or 'none'})"
            )

    # ── tool schema conversion ─────────────────────────────────────────
    def _tools(self) -> list[dict]:
        tools = []
        for d in self.registry.api_definitions():
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": d["name"],
                        "description": d["description"],
                        "parameters": d["input_schema"],
                    },
                }
            )
        return tools

    # ── one streamed model call ────────────────────────────────────────
    def _call_model(self) -> dict:
        """Stream one assistant message; returns {'content', 'tool_calls'}."""
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": self.system_fn()}] + self.messages,
            "tools": self._tools(),
            "stream": True,
            "options": {"num_ctx": self.config.ollama_num_ctx},
        }
        content_parts: list[str] = []
        tool_calls: list[dict] = []

        try:
            resp = requests.post(
                f"{self.host}/api/chat", json=payload, stream=True, timeout=600
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise OllamaError(f"Ollama request failed: {exc}") from exc

        for line in resp.iter_lines():
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "error" in chunk:
                raise OllamaError(chunk["error"])

            msg = chunk.get("message") or {}
            if msg.get("thinking") and self.on_thinking is not None:
                self.on_thinking(msg["thinking"])
            text = msg.get("content")
            if text:
                content_parts.append(text)
                self.emit(text)
            for call in msg.get("tool_calls") or []:
                tool_calls.append(call)
            if chunk.get("done"):
                break

        return {"content": "".join(content_parts), "tool_calls": tool_calls}

    # ── main turn loop ─────────────────────────────────────────────────
    def run_turn(self, user_input: str) -> str:
        self.messages.append({"role": "user", "content": user_input})
        final_text = ""

        for _ in range(self.max_tool_iterations):
            if self.cancelled():
                final_text = "[cancelled]"
                break
            result = self._call_model()
            if not result["tool_calls"]:
                # Small models sometimes write the call as text instead.
                text, calls = extract_text_tool_calls(
                    result["content"], set(self.registry.tools)
                )
                if calls:
                    result = {"content": text, "tool_calls": calls}
            assistant_msg: dict = {"role": "assistant", "content": result["content"]}
            if result["tool_calls"]:
                assistant_msg["tool_calls"] = result["tool_calls"]
            self.messages.append(assistant_msg)

            if not result["tool_calls"]:
                final_text = result["content"].strip()
                break

            self._run_tools(result["tool_calls"])
        else:
            note = "[stopped after too many tool calls]"
            self.emit("\n" + note)
            final_text = (final_text or "").strip()

        return final_text

    def _run_tools(self, tool_calls: list[dict]) -> None:
        for call in tool_calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            args = parse_arguments(fn.get("arguments", {}))
            self.notify(f"using {name}")
            result_text, _is_error = self.registry.execute(name, args, self.tool_ctx)
            self.messages.append(
                {"role": "tool", "tool_name": name, "content": result_text}
            )
