"""Backend for any OpenAI-compatible chat server — above all llama.cpp.

This is the backend that lets JARVIS run on a phone: llama.cpp's
``llama-server`` runs on Android inside Termux and speaks the OpenAI chat
API (``/v1/chat/completions``) with streaming and tool calling. The same code
also works with LM Studio, vLLM, Hugging Face TGI, and anything else that
implements that API.

Start llama-server with ``--jinja`` so the model's native tool-calling chat
template is used; without it, tool calls fall back to being parsed out of the
plain text (which still works, just less reliably).
"""

from __future__ import annotations

import json
import time

import requests

from .base import Backend
from .tool_calls import extract_text_tool_calls, normalise_call, parse_arguments


class OpenAICompatError(RuntimeError):
    pass


class OpenAICompatBackend(Backend):
    name = "llamacpp"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.base_url = self.config.openai_base_url.rstrip("/")
        self.model = self.config.openai_model
        self._headers = {"Content-Type": "application/json"}
        if self.config.openai_api_key:
            self._headers["Authorization"] = f"Bearer {self.config.openai_api_key}"
        self._check_ready()

    # ── readiness ──────────────────────────────────────────────────────
    def _check_ready(self) -> None:
        if self.config.provider == "groq" and not self.config.openai_api_key:
            raise OpenAICompatError(
                "Groq の API キーが設定されていません。console.groq.com で無料キーを作って\n"
                "  bash scripts/brain.sh groq gsk_あなたのキー   を実行してね。"
            )
        try:
            resp = requests.get(f"{self.base_url}/models", headers=self._headers, timeout=15)
            if resp.status_code in (401, 403):
                raise OpenAICompatError("API キーが拒否されました(401)。キーを確認してね。")
            resp.raise_for_status()
        except OpenAICompatError:
            raise
        except requests.RequestException as exc:
            if self.config.is_cloud:
                raise OpenAICompatError(
                    f"{self.base_url} に接続できません。ネット接続を確認してね。(エラー: {exc})"
                ) from exc
            raise OpenAICompatError(
                f"Can't reach the model server at {self.base_url}.\n"
                f"  • On Android/Termux: run  scripts/termux/start.sh  (starts llama-server)\n"
                f"  • Or start it yourself:  llama-server -m model.gguf --jinja --port 8080\n"
                f"  (underlying error: {exc})"
            ) from exc
        try:
            ids = [m.get("id", "") for m in resp.json().get("data", [])]
        except (ValueError, AttributeError):
            ids = []
        # llama-server reports the model file path as the id; if the user left
        # the default name, adopt whatever the server is actually serving.
        if ids and self.model == "local" and not self.config.is_cloud:
            self.model = ids[0]

    # ── tool schema ────────────────────────────────────────────────────
    def _tools(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": d["name"],
                    "description": d["description"],
                    "parameters": d["input_schema"],
                },
            }
            for d in self.registry.api_definitions()
        ]

    # ── one streamed model call ────────────────────────────────────────
    def _call_model(self) -> dict:
        """Stream one assistant message; returns {'content', 'tool_calls'}."""
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": self.system_fn()}] + self.messages,
            "stream": True,
            "max_tokens": self.config.max_tokens,
        }
        tools = self._tools()
        if tools:
            payload["tools"] = tools

        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers,
                json=payload,
                stream=True,
                timeout=900,
            )
            resp.raise_for_status()
        except requests.HTTPError as exc:
            detail = ""
            try:
                detail = exc.response.text[:500]
            except Exception:  # pragma: no cover - best effort only
                pass
            status = getattr(exc.response, "status_code", None)
            if status == 429:
                raise OpenAICompatError("無料枠の上限に当たったみたい。少し待ってからもう一度送ってね。") from exc
            raise OpenAICompatError(f"Model server error: {exc} {detail}") from exc
        except requests.RequestException as exc:
            raise OpenAICompatError(f"Model request failed: {exc}") from exc

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        finish_reason = None
        started = time.monotonic()
        prompt_chars = sum(len(str(m.get("content") or "")) for m in payload["messages"])
        # index -> partial call being assembled from streamed fragments
        partial: dict[int, dict] = {}
        self._active_resp = resp

        try:
            for raw in resp.iter_lines():
                if not raw:
                    continue
                line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if "error" in chunk:
                    err = chunk["error"]
                    raise OpenAICompatError(err.get("message", str(err)) if isinstance(err, dict) else str(err))

                for choice in chunk.get("choices") or []:
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]
                    delta = choice.get("delta") or {}
                    reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                    if reasoning:
                        reasoning_parts.append(reasoning)
                        if self.on_thinking is not None:
                            self.on_thinking(reasoning)
                    text = delta.get("content")
                    if text:
                        content_parts.append(text)
                        self.emit(text)
                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index", len(partial))
                        slot = partial.setdefault(idx, {"id": None, "name": "", "arguments": ""})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] += fn["name"]
                        if fn.get("arguments"):
                            args = fn["arguments"]
                            slot["arguments"] += args if isinstance(args, str) else json.dumps(args)
        except (requests.RequestException, AttributeError, ValueError) as exc:
            # AttributeError/ValueError are what urllib3 raises when the
            # response was closed underneath us by cancel().
            raise OpenAICompatError(f"Model stream interrupted: {exc}") from exc
        finally:
            self._active_resp = None

        tool_calls = [
            normalise_call(slot["name"], slot["arguments"], slot["id"])
            for _, slot in sorted(partial.items())
            if slot["name"]
        ]
        content = "".join(content_parts)
        if not tool_calls:
            content, tool_calls = extract_text_tool_calls(content, set(self.registry.tools))
        reasoning = "".join(reasoning_parts)
        if not content.strip() and not tool_calls and reasoning.strip():
            # Some servers route the whole answer into reasoning_content.
            content = reasoning.strip()
            self.emit(content)
        self._debug(
            f"model call: {time.monotonic() - started:.1f}s, prompt≈{prompt_chars} chars, "
            f"content={len(content)} chars, reasoning={len(reasoning)} chars, "
            f"tool_calls={[c['function']['name'] for c in tool_calls]}, finish={finish_reason}"
        )
        return {"content": content, "tool_calls": tool_calls}

    # ── main turn loop ─────────────────────────────────────────────────
    def run_turn(self, user_input: str) -> str:
        self.messages.append({"role": "user", "content": user_input})
        final_text = ""

        for _ in range(self.max_tool_iterations):
            if self.cancelled():
                final_text = "[cancelled]"
                break
            result = self._call_model()
            calls = result["tool_calls"]
            assistant_msg: dict = {"role": "assistant", "content": result["content"] or ""}
            if calls:
                # The wire format wants arguments as a JSON string.
                assistant_msg["tool_calls"] = [
                    {
                        "id": c["id"],
                        "type": "function",
                        "function": {
                            "name": c["function"]["name"],
                            "arguments": json.dumps(c["function"]["arguments"], ensure_ascii=False),
                        },
                    }
                    for c in calls
                ]
            self.messages.append(assistant_msg)

            if not calls:
                final_text = (result["content"] or "").strip()
                if not final_text:
                    self._debug("model returned an empty reply")
                break

            self._run_tools(calls)
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
                {"role": "tool", "tool_call_id": call["id"], "name": name, "content": result_text}
            )
