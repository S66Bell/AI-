"""Shared backend interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

from ..config import Config
from ..memory import Memory
from ..tools import ToolContext, ToolRegistry

# Cap on the number of tool-call round trips in a single turn, so a confused
# model can't loop forever.
MAX_TOOL_ITERATIONS = 12


class Backend(ABC):
    """Owns the message history and the model-call/tool loop for one turn."""

    name = "backend"

    def __init__(
        self,
        config: Config,
        registry: ToolRegistry,
        tool_ctx: ToolContext,
        memory: Memory,
        *,
        system_fn: Callable[[], str],
        emit: Callable[[str], None],
        notify: Callable[[str], None],
        on_thinking: Callable[[str], None] | None = None,
    ):
        self.config = config
        self.registry = registry
        self.tool_ctx = tool_ctx
        self.memory = memory
        self.system_fn = system_fn
        self.emit = emit
        self.notify = notify
        self.on_thinking = on_thinking
        # Seed from saved (text-only) history so a fresh session has continuity.
        self.messages: list[dict] = memory.recent_messages()

    @abstractmethod
    def run_turn(self, user_input: str) -> str:
        """Process one user turn end-to-end and return the final reply text."""

    def reset(self) -> None:
        self.messages = []
