"""The JARVIS agent: a provider-agnostic orchestrator over a model backend.

The Assistant wires together the persona, memory, and tools, then delegates the
actual model conversation to a backend (local Ollama, or Claude). Swapping the
brain is a config change — everything here stays the same.
"""

from __future__ import annotations

from typing import Callable

from .backends import Backend, make_backend
from .config import Config
from .memory import Memory
from .persona import build_system_prompt
from .tools import ToolContext, build_registry


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
        runner=None,
        learner=None,
    ):
        self.config = config
        self.memory = memory
        self.learner = learner

        # The local backend needs its own web tools; Claude uses server-side ones.
        self.registry = build_registry(config, include_web=config.is_local)
        # With a TaskRunner attached, JARVIS can hand long jobs to itself.
        if runner is not None:
            from .agent import get_tools as agent_tools

            for tool in agent_tools(runner):
                self.registry.register(tool)
        self.tool_ctx = ToolContext(
            config=config, memory=memory, confirm=confirm, notify=notify
        )

        self.backend: Backend = make_backend(
            config,
            self.registry,
            self.tool_ctx,
            memory,
            system_fn=lambda: build_system_prompt(
                config, memory.facts_as_text(), memory.load_summary()
            ),
            emit=emit,
            notify=notify,
            on_thinking=on_thinking,
        )

    @property
    def on_thinking(self) -> Callable[[str], None] | None:
        return self.backend.on_thinking

    @on_thinking.setter
    def on_thinking(self, value: Callable[[str], None] | None) -> None:
        self.backend.on_thinking = value

    def chat(self, user_input: str) -> str:
        """Run one user turn and return the final reply text."""
        self.memory.append_turn("user", user_input)
        reply = self.backend.run_turn(user_input)
        self.memory.append_turn("assistant", reply)
        if self.learner is not None:
            self.learner.note_turn()
        return reply

    def reset(self) -> None:
        """Drop the in-session conversation context (keeps long-term memory)."""
        self.backend.reset()
