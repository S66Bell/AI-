"""Reminder / follow-up tools, backed by the SQLite store.

These are the foundation of a proactive JARVIS: it can jot down things to bring
up later ("remind me to…", "next time, tell me…") and review what's pending.
A later step surfaces due reminders on its own when you open the app.
"""

from __future__ import annotations

from . import Tool, ToolContext


def _add(tool_input: dict, ctx: ToolContext) -> str:
    if ctx.store is None:
        return "Reminders are unavailable (no store configured)."
    text = (tool_input.get("text") or "").strip()
    if not text:
        return "Error: nothing to remind about."
    due_at = (tool_input.get("due_at") or "").strip() or None
    rid = ctx.store.add_reminder(text, due_at)
    when = f" (due {due_at})" if due_at else ""
    return f"Noted reminder #{rid}{when}: {text}"


def _list(tool_input: dict, ctx: ToolContext) -> str:
    if ctx.store is None:
        return "Reminders are unavailable (no store configured)."
    rows = ctx.store.list_pending()
    if not rows:
        return "No pending reminders."
    lines = []
    for r in rows:
        when = f" — due {r['due_at']}" if r["due_at"] else ""
        lines.append(f"#{r['id']}: {r['text']}{when}")
    return "\n".join(lines)


def _complete(tool_input: dict, ctx: ToolContext) -> str:
    if ctx.store is None:
        return "Reminders are unavailable (no store configured)."
    query = (tool_input.get("query") or "").strip()
    if not query:
        return "Error: specify a reminder id or text to complete."
    n = ctx.store.complete(query)
    return f"Completed {n} reminder(s)." if n else f"No pending reminder matched '{query}'."


def get_tools() -> list[Tool]:
    return [
        Tool(
            name="add_reminder",
            description=(
                "Save a reminder or follow-up to bring up later. Use this when the "
                "user asks to be reminded of something, or when you want to follow "
                "up proactively next time. Optionally set due_at for a time."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "What to be reminded about, as a concise note.",
                    },
                    "due_at": {
                        "type": "string",
                        "description": (
                            "Optional ISO 8601 time to surface it (e.g. "
                            "2026-06-14T09:00:00). Omit to surface it next session."
                        ),
                    },
                },
                "required": ["text"],
            },
            run=_add,
        ),
        Tool(
            name="list_reminders",
            description="List all pending (not yet completed) reminders and follow-ups.",
            input_schema={"type": "object", "properties": {}, "required": []},
            run=_list,
        ),
        Tool(
            name="complete_reminder",
            description=(
                "Mark reminder(s) done, by their numeric id or by matching text."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A reminder id (e.g. '3') or text to match.",
                    }
                },
                "required": ["query"],
            },
            run=_complete,
        ),
    ]
