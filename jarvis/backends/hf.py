"""Hugging Face Inference backend.

Runs JARVIS's brain on Hugging Face instead of a local machine: it talks to
HF's OpenAI-compatible router (https://router.huggingface.co/v1) so any served
open model — Qwen, Llama, Mistral, … — can drive the same agentic loop as the
Ollama and Claude backends. All you need is a Hugging Face access token.

This is what makes a no-GPU / cloud deployment possible: the model runs on HF,
while the tools still run wherever this process runs (your PC, or a Space).
"""

from __future__ import annotations

import json

import requests

from .base import MAX_TOOL_ITERATIONS, Backend


class HFError(RuntimeError):
    pass


class HFBackend(Backend):
    name = "hf"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.base_url = self.config.hf_base_url.rstrip("/")
        self.model = self.config.hf_model
        self.token = self.config.hf_token
        # Like Gemma on Ollama, not every served model exposes tool calling.
        # Start optimistic and fall back to chat-only on the first refusal.
        self._tools_supported = True
        if not self.token:
            raise HFError(
                "No Hugging Face token found. Create one at "
                "https://huggingface.co/settings/tokens and set it as "
                "HF_TOKEN (or HUGGINGFACEHUB_API_TOKEN) in your environment."
            )

    # ── tool schema (OpenAI function format) ───────────────────────────
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

    @staticmethod
    def _is_tools_unsupported(message: str) -> bool:
        m = message.lower()
        return ("tool" in m and ("not support" in m or "unsupported" in m)) or (
            "does not support tools" in m
        )

    def _disable_tools(self) -> None:
        if self._tools_supported:
            self._tools_supported = False
            self.notify(
                f"{self.model} can't call tools on this provider — continuing "
                "chat-only (no shell/file/web actions). Pick a tool-capable model "
                "via JARVIS_HF_MODEL if you need those."
            )

    # ── one streamed model call ────────────────────────────────────────
    def _call_model(self) -> dict:
        """Stream one assistant message; returns {'content', 'tool_calls'}."""
        use_tools = self._tools_supported and bool(self.registry.api_definitions())
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": self.system_fn()}] + self.messages,
            "stream": True,
            "max_tokens": self.config.hf_max_tokens,
        }
        if self.config.temperature is not None:
            payload["temperature"] = self.config.temperature
        if use_tools:
            payload["tools"] = self._tools()

        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                },
                stream=True,
                timeout=600,
            )
        except requests.RequestException as exc:
            raise HFError(f"Hugging Face request failed: {exc}") from exc

        if resp.status_code >= 400:
            detail = self._error_detail(resp)
            if use_tools and self._is_tools_unsupported(detail):
                self._disable_tools()
                return self._call_model()
            raise HFError(f"Hugging Face request failed ({resp.status_code}): {detail}")

        content_parts: list[str] = []
        # Tool calls stream as fragments keyed by index; assemble them here.
        partial: dict[int, dict] = {}

        for raw in resp.iter_lines():
            if not raw:
                continue
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[len("data:") :].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            if isinstance(chunk, dict) and chunk.get("error"):
                err = self._stringify_error(chunk["error"])
                if use_tools and self._is_tools_unsupported(err):
                    self._disable_tools()
                    return self._call_model()
                raise HFError(err)

            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}

            reasoning = delta.get("reasoning") or delta.get("reasoning_content")
            if reasoning and self.on_thinking is not None:
                self.on_thinking(reasoning)

            text = delta.get("content")
            if text:
                content_parts.append(text)
                self.emit(text)

            for tc in delta.get("tool_calls") or []:
                self._accumulate_tool_call(partial, tc)

        tool_calls = [partial[i] for i in sorted(partial)]
        return {"content": "".join(content_parts), "tool_calls": tool_calls}

    @staticmethod
    def _accumulate_tool_call(partial: dict[int, dict], tc: dict) -> None:
        idx = tc.get("index", 0)
        slot = partial.setdefault(idx, {"id": None, "name": "", "arguments": ""})
        if tc.get("id"):
            slot["id"] = tc["id"]
        fn = tc.get("function") or {}
        if fn.get("name"):
            slot["name"] = fn["name"]
        if fn.get("arguments"):
            slot["arguments"] += fn["arguments"]

    @staticmethod
    def _stringify_error(error) -> str:
        if isinstance(error, dict):
            return str(error.get("message") or error)
        return str(error)

    def _error_detail(self, resp: "requests.Response") -> str:
        try:
            data = resp.json()
            if isinstance(data, dict) and data.get("error"):
                return self._stringify_error(data["error"])
        except ValueError:
            pass
        return resp.text or f"HTTP {resp.status_code}"

    # ── main turn loop ─────────────────────────────────────────────────
    def run_turn(self, user_input: str) -> str:
        self.messages.append({"role": "user", "content": user_input})
        final_text = ""

        for _ in range(MAX_TOOL_ITERATIONS):
            result = self._call_model()
            assistant_msg: dict = {"role": "assistant", "content": result["content"]}
            if result["tool_calls"]:
                assistant_msg["tool_calls"] = [
                    {
                        "id": c["id"] or f"call_{i}",
                        "type": "function",
                        "function": {"name": c["name"], "arguments": c["arguments"] or "{}"},
                    }
                    for i, c in enumerate(result["tool_calls"])
                ]
            self.messages.append(assistant_msg)

            if not result["tool_calls"]:
                final_text = result["content"].strip()
                break

            self._run_tools(assistant_msg["tool_calls"])
        else:
            note = "[stopped after too many tool calls]"
            self.emit("\n" + note)
            final_text = (final_text or "").strip()

        return final_text

    def _run_tools(self, tool_calls: list[dict]) -> None:
        for call in tool_calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args) if args.strip() else {}
                except json.JSONDecodeError:
                    args = {}
            self.notify(f"using {name}")
            result_text, _is_error = self.registry.execute(name, args, self.tool_ctx)
            self.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id", ""),
                    "content": result_text,
                }
            )

    # ── one-shot completion (no streaming, no tools) ───────────────────
    def complete(self, system: str, user: str, *, max_tokens: int) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "max_tokens": max_tokens,
        }
        if self.config.temperature is not None:
            payload["temperature"] = self.config.temperature
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"].get("content") or ""
