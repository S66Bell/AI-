"""Persistence for JARVIS: conversation history and long-term memory.

Two distinct stores:

* Conversation history — a rolling, text-only transcript of past turns, so a
  fresh session can pick up where the last one left off. We deliberately store
  only the visible text (not raw thinking/tool-use blocks) so the on-disk log
  stays simple and portable across model versions.

* Long-term memory — a list of durable facts JARVIS has been asked to remember
  ("my sister's birthday is...", "I prefer tabs over spaces"). These are
  injected into the system prompt every session.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class Memory:
    def __init__(self, data_dir: Path, history_turns: int = 40):
        self.data_dir = data_dir
        self.history_path = data_dir / "conversation.jsonl"
        self.facts_path = data_dir / "memory.json"
        self.history_turns = history_turns

    # ── Long-term facts ────────────────────────────────────────────────
    def load_facts(self) -> list[dict]:
        if not self.facts_path.exists():
            return []
        try:
            return json.loads(self.facts_path.read_text())
        except (json.JSONDecodeError, OSError):
            return []

    def remember(self, fact: str) -> str:
        facts = self.load_facts()
        entry = {"fact": fact.strip(), "added": datetime.now().isoformat(timespec="seconds")}
        facts.append(entry)
        self.facts_path.write_text(json.dumps(facts, indent=2, ensure_ascii=False))
        return f"Noted and remembered: {fact.strip()}"

    def forget(self, query: str) -> str:
        facts = self.load_facts()
        q = query.strip().lower()
        kept = [f for f in facts if q not in f["fact"].lower()]
        removed = len(facts) - len(kept)
        self.facts_path.write_text(json.dumps(kept, indent=2, ensure_ascii=False))
        if removed == 0:
            return f"No remembered facts matched '{query}'."
        return f"Forgot {removed} remembered fact(s) matching '{query}'."

    def facts_as_text(self) -> str:
        facts = self.load_facts()
        if not facts:
            return ""
        return "\n".join(f"- {f['fact']}" for f in facts)

    # ── Conversation transcript ────────────────────────────────────────
    def append_turn(self, role: str, text: str) -> None:
        """Append one visible turn (role is 'user' or 'assistant')."""
        if not text.strip():
            return
        line = json.dumps(
            {"role": role, "text": text, "ts": datetime.now().isoformat(timespec="seconds")},
            ensure_ascii=False,
        )
        with self.history_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def recent_messages(self) -> list[dict]:
        """Return the last N turns as Anthropic-style message dicts.

        Only text content is reconstructed — enough for the model to have
        continuity without replaying thinking/tool blocks across sessions.
        """
        if not self.history_path.exists():
            return []
        rows: list[dict] = []
        try:
            with self.history_path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))
        except (json.JSONDecodeError, OSError):
            return []

        rows = rows[-self.history_turns :]
        messages: list[dict] = []
        for row in rows:
            role = row.get("role")
            text = row.get("text", "")
            if role in ("user", "assistant") and text:
                messages.append({"role": role, "content": text})

        # The API requires the history to start with a user turn.
        while messages and messages[0]["role"] != "user":
            messages.pop(0)
        return messages

    def clear_history(self) -> str:
        if self.history_path.exists():
            self.history_path.unlink()
        return "Conversation history cleared."

    def transcript(self, limit: int = 100) -> list[dict]:
        """Return the last `limit` visible turns for display in the UI, each as
        {role, text, ts}. Unlike recent_messages (which feeds the model and so
        must start on a user turn), this keeps everything for the user to read."""
        if not self.history_path.exists():
            return []
        rows: list[dict] = []
        try:
            with self.history_path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))
        except (json.JSONDecodeError, OSError):
            return []

        out: list[dict] = []
        for row in rows[-limit:]:
            role = row.get("role")
            text = row.get("text", "")
            if role in ("user", "assistant") and text:
                out.append({"role": role, "text": text, "ts": row.get("ts", "")})
        return out
