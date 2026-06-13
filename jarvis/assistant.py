"""The JARVIS agent: a streaming, tool-using conversation loop over Claude."""

from __future__ import annotations

from typing import Callable

import anthropic

from .config import Config
from .memory import Memory
from .persona import build_system_prompt
from .tools import ToolContext, ToolRegistry, build_registry

# Anthropic-hosted tools that give JARVIS live web access. These execute on
# Anthropic's side — we just declare them.
SERVER_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search"},
    {"type": "web_fetch_20260209", "name": "web_fetch"},
]

# Fable 5 can decline a request via safety classifiers; opt into a fallback so
# a refusal is transparently re-served instead of failing the turn.
_FALLBACK_BETA = "server-side-fallback-2026-06-01"
_FALLBACK_MODEL = "claude-opus-4-8"


class Assistant:
    def __init__(
        self,
        config: Config,
        memory: Memory,
        *,
        emit: Callable[[str], None],
        confirm: Callable[[str], bool],
        notify: Callable[[str], None] = lambda _m: None,
        on_thinking: Callable[[str], None] | None = None,
    ):
        self.config = config
        self.memory = memory
        self.emit = emit
        self.on_thinking = on_thinking
        self.client = anthropic.Anthropic(api_key=config.api_key)
        self.registry: ToolRegistry = build_registry(config)
        self.tool_ctx = ToolContext(
            config=config, memory=memory, confirm=confirm, notify=notify
        )
        # Working context for the live session, seeded from saved history.
        self.messages: list[dict] = memory.recent_messages()

    # ── prompt + request assembly ──────────────────────────────────────
    def _system_prompt(self) -> str:
        return build_system_prompt(self.config, self.memory.facts_as_text())

    def _tools(self) -> list[dict]:
        return self.registry.api_definitions() + SERVER_TOOLS

    def _is_fable(self) -> bool:
        return self.config.model.startswith("claude-fable") or self.config.model.startswith(
            "claude-mythos"
        )

    def _stream(self):
        """Open a streaming request for the current message list."""
        kwargs = dict(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            system=self._system_prompt(),
            tools=self._tools(),
            messages=self.messages,
            thinking={
                "type": "adaptive",
                "display": "summarized" if self.config.show_thinking else "omitted",
            },
            output_config={"effort": self.config.effort},
        )
        if self._is_fable():
            # Opt into refusal fallbacks for Fable 5 / Mythos 5.
            return self.client.beta.messages.stream(
                betas=[_FALLBACK_BETA],
                fallbacks=[{"model": _FALLBACK_MODEL}],
                **kwargs,
            )
        return self.client.messages.stream(**kwargs)

    # ── main turn loop ─────────────────────────────────────────────────
    def chat(self, user_input: str) -> str:
        """Run one full user turn, streaming output, and return final text."""
        self.messages.append({"role": "user", "content": user_input})
        self.memory.append_turn("user", user_input)

        final_text_parts: list[str] = []

        while True:
            response = self._consume_stream()
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "tool_use":
                self._run_client_tools(response)
                continue

            if response.stop_reason == "pause_turn":
                # Server-side tool loop paused; re-send to let it resume.
                continue

            if response.stop_reason == "refusal":
                text = self._refusal_text(response)
                final_text_parts.append(text)
                self.emit("\n" + text)
                break

            # Normal completion (end_turn / max_tokens / stop_sequence).
            final_text_parts.append(self._collect_text(response))
            if response.stop_reason == "max_tokens":
                self.emit("\n[response truncated — hit the output limit]")
            break

        final_text = "\n".join(p for p in final_text_parts if p).strip()
        self.memory.append_turn("assistant", final_text)
        return final_text

    def _consume_stream(self):
        """Stream one model response, emitting text/thinking as it arrives."""
        thinking_emitted = False
        with self._stream() as stream:
            for event in stream:
                if event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        self.emit(event.delta.text)
                    elif (
                        event.delta.type == "thinking_delta"
                        and self.on_thinking is not None
                    ):
                        if not thinking_emitted:
                            thinking_emitted = True
                        self.on_thinking(event.delta.thinking)
            return stream.get_final_message()

    def _run_client_tools(self, response) -> None:
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        results = []
        for block in tool_uses:
            self.tool_ctx.notify(f"using {block.name}")
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

    @staticmethod
    def _refusal_text(response) -> str:
        category = None
        if getattr(response, "stop_details", None) is not None:
            category = getattr(response.stop_details, "category", None)
        base = "I'm not able to help with that one"
        return f"{base}{f' ({category})' if category else ''}."

    # ── session helpers ────────────────────────────────────────────────
    def reset(self) -> None:
        """Drop the in-memory conversation context (keeps long-term memory)."""
        self.messages = []
