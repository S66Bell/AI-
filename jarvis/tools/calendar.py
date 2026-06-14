"""Google Calendar tools, backed by the shared CalendarClient.

These let Mira read the agenda and create / update / delete events on the user's
*real* Google Calendar. Times are ISO 8601 in the configured timezone; a time
with no offset is assumed to be in that zone. Mutations confirm with the user
first, since they touch a live external calendar.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from . import Tool, ToolContext


def _parse_iso(value: str, ctx: ToolContext) -> datetime:
    """Parse an ISO 8601 string, attaching the configured tz when naive."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None and ctx.config.tz is not None:
        dt = dt.replace(tzinfo=ctx.config.tz)
    return dt


def _fmt(ev: dict, ctx: ToolContext) -> str:
    """Render one normalized event as a single line, including its id."""
    start = ev.get("start")
    if start is None:
        when = "?"
    elif ev.get("all_day"):
        tz = ctx.config.tz
        when = (start.astimezone(tz) if tz else start).strftime("%Y-%m-%d (all day)")
    else:
        tz = ctx.config.tz
        when = (start.astimezone(tz) if tz else start).strftime("%Y-%m-%d %H:%M")
    return f"[{ev.get('id')}] {when} — {ev.get('summary')}"


def _list(tool_input: dict, ctx: ToolContext) -> str:
    if ctx.gcal is None:
        return "Calendar is unavailable (not configured)."
    start_raw = (tool_input.get("start") or "").strip()
    end_raw = (tool_input.get("end") or "").strip()
    if start_raw:
        start = _parse_iso(start_raw, ctx)
    else:
        now = ctx.config.now()
        start = datetime.combine(now.date(), time.min, tzinfo=now.tzinfo)
    end = _parse_iso(end_raw, ctx) if end_raw else start + timedelta(days=1)
    events = ctx.gcal.list_events(start, end)
    if not events:
        return "No events in that range."
    return "\n".join(_fmt(ev, ctx) for ev in events)


def _create(tool_input: dict, ctx: ToolContext) -> str:
    if ctx.gcal is None:
        return "Calendar is unavailable (not configured)."
    summary = (tool_input.get("summary") or "").strip()
    start_raw = (tool_input.get("start") or "").strip()
    if not summary or not start_raw:
        return "Error: both summary and start are required."
    if not ctx.confirm(f"Create calendar event '{summary}' at {start_raw}?"):
        return "Cancelled — no event was created."
    start = _parse_iso(start_raw, ctx)
    end_raw = (tool_input.get("end") or "").strip()
    end = _parse_iso(end_raw, ctx) if end_raw else None
    description = (tool_input.get("description") or "").strip()
    ev = ctx.gcal.create_event(
        summary=summary, start=start, end=end, description=description
    )
    return f"Created event [{ev['id']}] '{ev['summary']}'. {ev.get('htmlLink', '')}".strip()


def _update(tool_input: dict, ctx: ToolContext) -> str:
    if ctx.gcal is None:
        return "Calendar is unavailable (not configured)."
    event_id = (tool_input.get("event_id") or "").strip()
    if not event_id:
        return "Error: event_id is required."
    if not ctx.confirm(f"Update calendar event {event_id}?"):
        return "Cancelled — no changes were made."
    fields: dict = {}
    if tool_input.get("summary"):
        fields["summary"] = tool_input["summary"].strip()
    if tool_input.get("description") is not None:
        fields["description"] = (tool_input.get("description") or "").strip()
    if tool_input.get("start"):
        fields["start"] = _parse_iso(tool_input["start"].strip(), ctx)
    if tool_input.get("end"):
        fields["end"] = _parse_iso(tool_input["end"].strip(), ctx)
    ev = ctx.gcal.update_event(event_id, **fields)
    return f"Updated event [{ev['id']}] '{ev['summary']}'."


def _delete(tool_input: dict, ctx: ToolContext) -> str:
    if ctx.gcal is None:
        return "Calendar is unavailable (not configured)."
    event_id = (tool_input.get("event_id") or "").strip()
    if not event_id:
        return "Error: event_id is required."
    if not ctx.confirm(f"Delete calendar event {event_id}?"):
        return "Cancelled — the event was not deleted."
    ctx.gcal.delete_event(event_id)
    return f"Deleted event {event_id}."


def get_tools() -> list[Tool]:
    return [
        Tool(
            name="list_events",
            description=(
                "List events on the user's real Google Calendar in a time range. "
                "Times are ISO 8601 in the configured timezone; defaults to today. "
                "Returns each event's id so you can update or delete it."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "start": {
                        "type": "string",
                        "description": "Optional ISO 8601 start of the range. Defaults to today's start.",
                    },
                    "end": {
                        "type": "string",
                        "description": "Optional ISO 8601 end of the range. Defaults to 24h after start.",
                    },
                },
                "required": [],
            },
            run=_list,
        ),
        Tool(
            name="create_event",
            description=(
                "Create an event on the user's real Google Calendar. Times are "
                "ISO 8601 in the configured timezone. Confirms with the user first."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Event title."},
                    "start": {
                        "type": "string",
                        "description": "ISO 8601 start time (e.g. 2026-06-14T09:00:00).",
                    },
                    "end": {
                        "type": "string",
                        "description": "Optional ISO 8601 end time. Defaults to one hour after start.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional longer details for the event.",
                    },
                },
                "required": ["summary", "start"],
            },
            run=_create,
        ),
        Tool(
            name="update_event",
            description=(
                "Update an existing event on the user's real Google Calendar by "
                "its id. Only the fields you pass are changed. Times are ISO 8601 "
                "in the configured timezone. Confirms with the user first."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "The event id to update."},
                    "summary": {"type": "string", "description": "New title."},
                    "start": {"type": "string", "description": "New ISO 8601 start time."},
                    "end": {"type": "string", "description": "New ISO 8601 end time."},
                    "description": {"type": "string", "description": "New details."},
                },
                "required": ["event_id"],
            },
            run=_update,
        ),
        Tool(
            name="delete_event",
            description=(
                "Delete an event from the user's real Google Calendar by its id. "
                "Confirms with the user first."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "The event id to delete."},
                },
                "required": ["event_id"],
            },
            run=_delete,
        ),
    ]
