"""The personality and operating instructions for Mira."""

from __future__ import annotations

import platform
from datetime import datetime
from typing import Any, Sequence

from .config import Config


def _is_japanese(config: Config) -> bool:
    """Whether to speak Japanese, per the configured language."""
    lang = (config.language or "").strip().lower()
    return "日本" in (config.language or "") or lang.startswith("ja")


def build_greeting(
    config: Config,
    due: Sequence[Any],
    now: datetime | None = None,
    *,
    events: Sequence[Any] = (),
) -> str:
    """Compose the proactive opening line shown when the app is opened.

    Templated in Python — no model call — so it's instant and costs nothing.
    Leads with a time-of-day greeting in Mira's dry, concise voice, then, if
    any calendar events fall today, lists the day's agenda, and finally, if any
    reminders are due, appends a compact summary. `due` rows behave like dicts /
    `sqlite3.Row` (read via `r["text"]` / `r["due_at"]`); `events` are the
    normalized dicts from `CalendarClient` (`summary`, `start`, `all_day`).
    """

    now = now or config.now()
    hour = now.hour
    japanese = _is_japanese(config)
    user = config.user_name

    if 5 <= hour < 12:
        tod = "おはようございます" if japanese else "Good morning"
    elif 12 <= hour < 17:
        tod = "こんにちは" if japanese else "Good afternoon"
    elif 17 <= hour < 22:
        tod = "こんばんは" if japanese else "Good evening"
    else:
        tod = "夜更かしですね" if japanese else "Still up"

    if japanese:
        lead = f"{tod}、{user}。"
    else:
        lead = f"{tod}, {user}."

    blocks = _agenda_and_reminder_blocks(config, due, events)
    if not blocks:
        return lead
    return lead + "\n" + "\n".join(blocks)


def _agenda_and_reminder_blocks(
    config: Config, due: Sequence[Any], events: Sequence[Any]
) -> list[str]:
    """The agenda + due-reminder text blocks shared by the in-app greeting and
    the proactive briefing. Each entry is a self-contained multi-line string;
    the caller joins them with newlines. `due` rows read like dicts /
    `sqlite3.Row` (`r["text"]` / `r["due_at"]`); `events` are the normalized
    dicts from `CalendarClient` (`summary`, `start`, `all_day`)."""
    japanese = _is_japanese(config)
    blocks: list[str] = []

    # Today's calendar agenda, when the calendar is configured and has events.
    event_rows = list(events)
    if event_rows:
        if japanese:
            agenda_header = f"本日の予定が{len(event_rows)}件あります："
        else:
            noun = "event" if len(event_rows) == 1 else "events"
            agenda_header = f"{len(event_rows)} {noun} today:"
        tz = config.tz
        agenda_items = []
        for ev in event_rows:
            summary = ev.get("summary") or ("(無題)" if japanese else "(no title)")
            if ev.get("all_day"):
                clock = "終日" if japanese else "all day"
            else:
                start = ev.get("start")
                if start is not None:
                    clock = (start.astimezone(tz) if tz else start).strftime("%H:%M")
                else:
                    clock = "?"
            agenda_items.append(f"  • {summary} ({clock})")
        blocks.append(agenda_header + "\n" + "\n".join(agenda_items))

    # Due reminders, rendered exactly as before.
    rows = list(due)
    if rows:
        shown = rows[:5]
        overflow = len(rows) - len(shown)

        if japanese:
            header = f"未対応のリマインダーが{len(rows)}件あります："
        else:
            noun = "reminder" if len(rows) == 1 else "reminders"
            header = f"{len(rows)} pending {noun}:"

        items = []
        for r in shown:
            text = r["text"]
            due_at = r["due_at"]
            items.append(f"  • {text} ({due_at})" if due_at else f"  • {text}")

        if overflow > 0:
            items.append(
                f"  • …他{overflow}件" if japanese else f"  • …and {overflow} more"
            )
        blocks.append(header + "\n" + "\n".join(items))

    return blocks


def build_briefing(
    config: Config, due: Sequence[Any], events: Sequence[Any]
) -> tuple[str, str]:
    """Compose the proactive briefing pushed to the phone as (title, body).

    Same templated content as the in-app greeting's agenda/reminder blocks, but
    shaped for a notification: a short title plus a body that stands on its own
    even when there's nothing to report."""
    japanese = _is_japanese(config)
    title = "今日のブリーフィング" if japanese else "Today's briefing"
    blocks = _agenda_and_reminder_blocks(config, due, events)
    if blocks:
        body = "\n".join(blocks)
    else:
        body = (
            "今日は予定もリマインダーもありません。"
            if japanese
            else "Nothing on the calendar and no pending reminders."
        )
    return title, body


def build_system_prompt(config: Config, long_term_memory: str = "") -> str:
    """Assemble the system prompt that defines who Mira is.

    The stable persona comes first so it caches well; the volatile bits
    (date, host, recalled memories) are appended at the end.
    """

    language_bullet = ""
    if config.language:
        language_bullet = (
            f"- Always reply in {config.language}, regardless of the language the "
            f"user writes in, unless they explicitly ask for another language.\n"
        )

    persona = f"""\
You are {config.assistant_name}, a personal AI assistant built for one person
only: {config.user_name}. Your name means "wonder" — and a guiding star. Be
exactly that for {config.user_name}: unfailingly competent, quietly witty, warm
but never sycophantic, and completely loyal to {config.user_name}.

How you operate:
{language_bullet}- Address the user as "{config.user_name}". Be concise and direct; lead with
  the answer or the result, then add detail only if it helps.
- You are a capable agent, not just a chatbot. You have tools to run shell
  commands, read and write files, search and read the web, and remember things
  across conversations. Use them proactively to actually accomplish tasks
  rather than describing how the user could do it themselves.
- Think before acting on anything non-trivial. For multi-step jobs, take the
  steps yourself with your tools instead of handing back instructions.
- When a request is ambiguous in a way that changes what you'd do, ask a brief
  clarifying question. Otherwise, make a sensible choice and proceed.
- Be honest about uncertainty and about failures. If a command errored or a
  step didn't work, say so plainly with the relevant output.

Safety and judgement:
- You run on {config.user_name}'s own machine with their authority, but you
  exercise care. Before anything destructive or irreversible (deleting data,
  overwriting files, changing system configuration, sending messages to other
  people), confirm intent first unless explicitly told to just do it.
- Never fabricate the result of a tool call. Report what actually happened.

Personality:
- Dry, understated humour is welcome. A well-placed quip is fine; a monologue
  is not.
- You take genuine initiative. If you notice something useful adjacent to the
  task, mention it briefly — but don't go off and do unrequested work.
"""

    context = f"""

── Current context ──
Date and time: {config.now().strftime('%A, %d %B %Y, %H:%M %Z')}
Host system: {platform.system()} {platform.release()} ({platform.machine()})
"""

    if long_term_memory.strip():
        context += f"""
── What you remember about {config.user_name} ──
{long_term_memory.strip()}
"""

    return persona + context
