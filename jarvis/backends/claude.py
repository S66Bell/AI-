"""Claude (Anthropic API) backend."""

from __future__ import annotations

import anthropic

from .base import Backend

# Anthropic-hosted tools that give JARVIS live web access (server-executed).
SERVER_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search"},
    {"type": "web_fetch_20260209", "name": "web_fetch"},
]

# Fable 5 can decline a request via safety classifiers; opt into a fallback so
# a refusal is transparently re-served instead of failing the turn.
_FALLBACK_BETA = "server-side-fallback-2026-06-01"
_FALLBACK_MODEL = "claude-opus-4-8"


class ClaudeBackend(Backend):
    name = "claude"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = anthropic.Anthropic(api_key=self.config.api_key)

    def _is_fable(self) -> bool:
        m = self.config.model
        return m.startswith("claude-fable") or m.startswith("claude-mythos")

    def _tools(self) -> list[dict]:
        return self.registry.api_definitions() + SERVER_TOOLS

    def _stream(self):
        kwargs = dict(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            system=self.system_fn(),
            tools=self._tools(),
            messages=self.messages,
            thinking={
                "type": "adaptive",
                "display": "summarized" if self.config.show_thinking else "omitted",
            },
            output_config={"effort": self.config.effort},
        )
        if self._is_fable():
            return self.client.beta.messages.stream(
                betas=[_FALLBACK_BETA],
                fallbacks=[{"model": _FALLBACK_MODEL}],
                **kwargs,
            )
        return self.client.messages.stream(**kwargs)

    def run_turn(self, user_input: str) -> str:
        self.messages.append({"role": "user", "content": user_input})
        final_parts: list[str] = []

        while True:
            response = self._consume_stream()
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "tool_use":
                self._run_client_tools(response)
                continue
            if response.stop_reason == "pause_turn":
                continue  # server-tool loop paused; re-send to resume
            if response.stop_reason == "refusal":
                text = self._refusal_text(response)
                final_parts.append(text)
                self.emit("\n" + text)
                break

            final_parts.append(self._collect_text(response))
            if response.stop_reason == "max_tokens":
                self.emit("\n[response truncated — hit the output limit]")
            break

        return "\n".join(p for p in final_parts if p).strip()

    def _consume_stream(self):
        with self._stream() as stream:
            for event in stream:
                if event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        self.emit(event.delta.text)
                    elif (
                        event.delta.type == "thinking_delta"
                        and self.on_thinking is not None
                    ):
                        self.on_thinking(event.delta.thinking)
            return stream.get_final_message()

    def _run_client_tools(self, response) -> None:
        results = []
        for block in (b for b in response.content if b.type == "tool_use"):
            self.notify(f"using {block.name}")
            result_text, is_error = self.registry.execute(
                block.name, dict(block.input or {}), self.tool_ctx
            )
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                    "is_error": is_error,
                }
            )
        self.messages.append({"role": "user", "content": results})

    @staticmethod
    def _collect_text(response) -> str:
        return "".join(b.text for b in response.content if b.type == "text").strip()

    # ── one-shot completion (no streaming, no tools, no thinking) ──────
    def complete(self, system: str, user: str, *, max_tokens: int) -> str:
        kwargs = dict(
            model=self.config.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        # Mirror _stream()'s refusal fallback so reflection works on Fable too.
        if self._is_fable():
            resp = self.client.beta.messages.create(
                betas=[_FALLBACK_BETA],
                fallbacks=[{"model": _FALLBACK_MODEL}],
                **kwargs,
            )
        else:
            resp = self.client.messages.create(**kwargs)
        return "".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        )

    @staticmethod
    def _refusal_text(response) -> str:
        category = None
        if getattr(response, "stop_details", None) is not None:
            category = getattr(response.stop_details, "category", None)
        return f"I'm not able to help with that one{f' ({category})' if category else ''}."
