"""Tools that let JARVIS remember and forget things across sessions."""

from __future__ import annotations

from . import Tool, ToolContext


def _remember(tool_input: dict, ctx: ToolContext) -> str:
    fact = tool_input.get("fact", "").strip()
    if not fact:
        return "Error: nothing to remember."
    return ctx.memory.remember(fact)


def _recall(tool_input: dict, ctx: ToolContext) -> str:
    facts = ctx.memory.facts_as_text()
    return facts if facts else "I have no long-term memories stored yet."


def _forget(tool_input: dict, ctx: ToolContext) -> str:
    query = tool_input.get("query", "").strip()
    if not query:
        return "Error: specify what to forget."
    return ctx.memory.forget(query)


def get_tools() -> list[Tool]:
    return [
        Tool(
            name="remember",
            description=(
                "Store a durable fact about the user or their preferences so you "
                "recall it in future conversations. Use this whenever the user "
                "shares something worth remembering ('remember that...', a "
                "preference, an important date, how they like things done)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "fact": {
                        "type": "string",
                        "description": "The fact, one short sentence.",
                    }
                },
                "required": ["fact"],
            },
            run=_remember,
        ),
        Tool(
            name="recall_memories",
            description="List long-term memory.",
            input_schema={"type": "object", "properties": {}, "required": []},
            run=_recall,
        ),
        Tool(
            name="forget",
            description="Delete memories matching a text.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Text to match.",
                    }
                },
                "required": ["query"],
            },
            run=_forget,
        ),
    ]
