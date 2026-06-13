"""Model backends for JARVIS.

A backend owns the conversation with one model provider and drives the
agentic loop (call model -> run tools -> feed results back -> repeat). The
rest of JARVIS — persona, memory, tools, UI — is provider-agnostic and talks
to whatever backend is active.
"""

from __future__ import annotations

from typing import Callable

from ..config import Config
from ..memory import Memory
from ..tools import ToolContext, ToolRegistry
from .base import Backend


def make_backend(
    config: Config,
    registry: ToolRegistry,
    tool_ctx: ToolContext,
    memory: Memory,
    *,
    system_fn: Callable[[], str],
    emit: Callable[[str], None],
    notify: Callable[[str], None],
    on_thinking: Callable[[str], None] | None = None,
) -> Backend:
    kwargs = dict(
        config=config,
        registry=registry,
        tool_ctx=tool_ctx,
        memory=memory,
        system_fn=system_fn,
        emit=emit,
        notify=notify,
        on_thinking=on_thinking,
    )
    if config.is_local:
        from .ollama import OllamaBackend

        return OllamaBackend(**kwargs)

    from .claude import ClaudeBackend

    return ClaudeBackend(**kwargs)


__all__ = ["Backend", "make_backend"]
