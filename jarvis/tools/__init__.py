"""Client-side tools JARVIS can call, plus the registry that wires them up.

Each tool is a `Tool` with an Anthropic input schema and a Python callable.
Server-side tools (web search / web fetch) are added directly in the assistant
loop because Anthropic executes those — we don't run them here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..config import Config
from ..memory import Memory


@dataclass
class ToolContext:
    """Everything a tool implementation might need at call time."""

    config: Config
    memory: Memory
    # Ask the user a yes/no question; returns True if approved.
    confirm: Callable[[str], bool]
    # Emit a short status line to the user (e.g. "running: ls -la").
    notify: Callable[[str], None] = lambda _msg: None


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    run: Callable[[dict, ToolContext], str]

    def to_api(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


@dataclass
class ToolRegistry:
    tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def api_definitions(self) -> list[dict]:
        return [t.to_api() for t in self.tools.values()]

    def execute(self, name: str, tool_input: dict, ctx: ToolContext) -> tuple[str, bool]:
        """Run a tool by name. Returns (result_text, is_error)."""
        tool = self.tools.get(name)
        if tool is None:
            return f"Unknown tool: {name}", True
        try:
            return tool.run(tool_input, ctx), False
        except Exception as exc:  # surface failures to the model, don't crash
            return f"{type(exc).__name__}: {exc}", True


def build_registry(ctx_config: Config) -> ToolRegistry:
    """Construct the default tool set."""
    from . import filesystem, memory_tool, shell, system_info

    registry = ToolRegistry()
    for tool in (
        *shell.get_tools(),
        *filesystem.get_tools(),
        *system_info.get_tools(),
        *memory_tool.get_tools(),
    ):
        registry.register(tool)
    return registry
