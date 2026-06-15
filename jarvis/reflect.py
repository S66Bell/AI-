"""Post-turn reflection: quietly learn durable facts about the user.

After a turn, we ask the model to extract any long-term, user-specific facts
from the exchange and remember the new ones. Best-effort and degradable — any
failure (provider error, non-JSON output) is swallowed so it never affects the
user's reply."""
from __future__ import annotations

import json

REFLECT_MAX_TOKENS = 256

REFLECT_PROMPT = """\
You extract durable, long-term facts about the USER from a single conversation
turn, so an assistant can remember them later.

Output ONLY a JSON array of short strings. Each string is one concise fact
written about the user (e.g. "Prefers tabs over spaces", "Sister's birthday is
March 3", "Working on a Rust game engine called Drift").

Include only durable, user-specific facts: stable preferences, relationships,
important dates, ongoing projects, goals, and recurring context.

Exclude: ephemeral details, one-off questions, trivia, world facts, anything
the assistant said, and anything not specifically about the user.

If there is nothing worth remembering, output exactly: []
Output the JSON array and nothing else."""


def _payload(user_text: str, reply_text: str) -> str:
    return f"User said:\n{user_text}\n\nAssistant replied:\n{reply_text}"


def _parse_facts(raw: str) -> list[str]:
    """Pull a JSON array of fact strings out of the model's output, tolerating
    code fences and surrounding prose. Returns [] on any problem."""
    if not raw:
        return []
    text = raw.strip()
    # Drop code fences if present.
    if text.startswith("```"):
        text = text.strip("`")
        # after stripping backticks a leading "json" word may remain
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [s.strip() for s in data if isinstance(s, str) and s.strip()]


def _worth_reflecting(user_text: str) -> bool:
    """Cheap gate to skip trivial turns and avoid a needless extra model call."""
    t = (user_text or "").strip()
    if len(t) < 12:
        return False
    if t.startswith("/"):
        return False
    return True


def reflect(backend, memory, user_text: str, reply_text: str) -> list[str]:
    """Extract durable facts from the turn and remember the new ones. Returns
    the newly-added facts; [] on any failure. Never raises."""
    try:
        raw = backend.complete(
            REFLECT_PROMPT, _payload(user_text, reply_text),
            max_tokens=REFLECT_MAX_TOKENS,
        )
        facts = _parse_facts(raw)
        if not facts:
            return []
        return memory.remember_many(facts)
    except Exception:
        return []
