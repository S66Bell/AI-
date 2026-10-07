"""Helpers for turning a local model's output into tool calls.

Small open models are not always tidy about tool calling. Depending on the
chat template and the server, a call may arrive as:

* a proper structured ``tool_calls`` entry (what we want), with
  ``arguments`` as a JSON string or an already-parsed object;
* JSON wrapped in ``<tool_call>...</tool_call>`` tags in the plain text
  (the Qwen / Hermes convention when the server isn't applying a template);
* a bare JSON object in the text like ``{"name": ..., "arguments": {...}}``.

The functions here normalise all of those so the backends can stay simple.
"""

from __future__ import annotations

import json
import re
import uuid

_TAGGED_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_arguments(raw) -> dict:
    """Return the tool arguments as a dict, repairing common JSON mistakes."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    text = raw.strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        pass
    repaired = _repair_json(text)
    try:
        value = json.loads(repaired)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def _repair_json(text: str) -> str:
    """Best-effort fixes for the JSON slips small models make."""
    text = text.strip()
    # Strip a code fence if the model wrapped the arguments in one.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # Trailing commas before a closing brace/bracket.
    text = re.sub(r",\s*([}\]])", r"\1", text)
    # Single-quoted keys/strings → double quotes (only if there are no double quotes).
    if '"' not in text and "'" in text:
        text = text.replace("'", '"')
    # Python literals.
    text = re.sub(r"\bTrue\b", "true", text)
    text = re.sub(r"\bFalse\b", "false", text)
    text = re.sub(r"\bNone\b", "null", text)
    # Unbalanced braces: close what was opened.
    opens = text.count("{") - text.count("}")
    if opens > 0:
        text += "}" * opens
    return text


def new_call_id() -> str:
    return "call_" + uuid.uuid4().hex[:12]


def normalise_call(name: str, arguments, call_id: str | None = None) -> dict:
    """Build the canonical tool-call structure used across backends."""
    return {
        "id": call_id or new_call_id(),
        "type": "function",
        "function": {"name": name, "arguments": parse_arguments(arguments)},
    }


def extract_text_tool_calls(content: str, known_tools: set[str]) -> tuple[str, list[dict]]:
    """Pull tool calls the model emitted as plain text.

    Returns ``(remaining_text, calls)``. Only calls naming a known tool are
    accepted, so ordinary JSON in a reply is never mistaken for a call.
    """
    if not content or not known_tools:
        return content, []

    calls: list[dict] = []
    remaining = content

    def _try(candidate: str) -> bool:
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            try:
                obj = json.loads(_repair_json(candidate))
            except json.JSONDecodeError:
                return False
        if not isinstance(obj, dict):
            return False
        name = obj.get("name") or (obj.get("function") or {}).get("name")
        if name not in known_tools:
            return False
        args = obj.get("arguments")
        if args is None:
            args = obj.get("parameters")
        if args is None:
            args = (obj.get("function") or {}).get("arguments")
        calls.append(normalise_call(name, args))
        return True

    for pattern in (_TAGGED_RE, _FENCED_JSON_RE):
        for m in list(pattern.finditer(remaining)):
            if _try(m.group(1)):
                remaining = remaining.replace(m.group(0), "", 1)

    if not calls:
        stripped = remaining.strip()
        if stripped.startswith("{") and stripped.endswith("}") and _try(stripped):
            remaining = ""

    return remaining.strip(), calls
