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
    config: Config, due: Sequence[Any], now: datetime | None = None
) -> str:
    """Compose the proactive opening line shown when the app is opened.

    Templated in Python — no model call — so it's instant and costs nothing.
    Leads with a time-of-day greeting in Mira's dry, concise voice, then, if
    any reminders are due, appends a compact summary. `due` rows behave like
    dicts / `sqlite3.Row`, read via `r["text"]` / `r["due_at"]`.
    """

    now = now or datetime.now()
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

    if not due:
        return lead

    rows = list(due)
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
        items.append(f"  • …他{overflow}件" if japanese else f"  • …and {overflow} more")

    return lead + "\n" + header + "\n" + "\n".join(items)


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
Date and time: {datetime.now().strftime('%A, %d %B %Y, %H:%M')}
Host system: {platform.system()} {platform.release()} ({platform.machine()})
"""

    if long_term_memory.strip():
        context += f"""
── What you remember about {config.user_name} ──
{long_term_memory.strip()}
"""

    return persona + context
