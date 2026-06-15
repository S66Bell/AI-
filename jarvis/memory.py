"""Persistence for JARVIS: conversation history and long-term memory.

Two distinct stores:

* Conversation history — kept in a small SQLite database (see store.py) split
  into **threads**, so you can hold several separate conversations and switch
  between them. We store only the visible text (not raw thinking/tool-use
  blocks) so the log stays simple and portable across model versions.

* Long-term memory — a list of durable facts JARVIS has been asked to remember
  ("my sister's birthday is...", "I prefer tabs over spaces"), kept in a JSON
  file and injected into the system prompt every session. Facts are global, so
  JARVIS remembers them across all threads.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .store import Store

# Soft cap on stored facts. Every fact is injected into the system prompt each
# turn, so an unbounded file would steadily bloat the model's context. We stop
# adding new facts past this cap (no trimming — old facts are kept as-is).
MAX_FACTS = 200


class Memory:
    def __init__(self, data_dir: Path, history_turns: int = 40, store: Store | None = None):
        self.data_dir = data_dir
        self.facts_path = data_dir / "memory.json"
        self.history_turns = history_turns
        self.store = store or Store(data_dir)
        # Resume the most recent thread, or start one.
        self.thread_id = self.store.latest_thread_id() or self.store.create_thread()

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

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.strip().lower().split())

    def remember_many(self, facts: list[str]) -> list[str]:
        """Add each fact that isn't already known; return the newly-added ones.
        Conservative dedupe: skip a candidate if a known fact (normalized) equals,
        contains, or is contained by it, and skip in-batch duplicates. Stops once
        we hold MAX_FACTS, since every fact is injected into the system prompt and
        an unbounded file would bloat the model's context."""
        existing_rows = self.load_facts()
        seen = {self._normalize(f["fact"]) for f in existing_rows}
        count = len(existing_rows)
        added: list[str] = []
        for raw in facts:
            if count >= MAX_FACTS:
                break
            cand = raw.strip()
            if not cand:
                continue
            norm = self._normalize(cand)
            if norm in seen or any(norm in e or e in norm for e in seen):
                continue
            self.remember(cand)
            seen.add(norm)
            count += 1
            added.append(cand)
        return added

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

    # ── Conversation transcript (current thread) ───────────────────────
    def append_turn(self, role: str, text: str) -> None:
        """Append one visible turn (role is 'user' or 'assistant')."""
        if not text.strip():
            return
        self.store.add_message(self.thread_id, role, text)

    def recent_messages(self) -> list[dict]:
        """Last N turns of the current thread as Anthropic-style message dicts."""
        return self.store.recent_messages(self.thread_id, self.history_turns)

    def clear_history(self) -> str:
        self.store.clear_thread_messages(self.thread_id)
        return "Conversation history cleared."

    def transcript(self, limit: int = 200) -> list[dict]:
        """The current thread's visible turns for display, each as
        {role, text, ts}."""
        return self.store.get_messages(self.thread_id, limit)

    # ── Thread management ──────────────────────────────────────────────
    def list_threads(self) -> list[dict]:
        return self.store.list_threads()

    def new_thread(self) -> int:
        self.thread_id = self.store.create_thread()
        return self.thread_id

    def switch_thread(self, thread_id: int) -> bool:
        if not self.store.thread_exists(thread_id):
            return False
        self.thread_id = thread_id
        return True

    def rename_thread(self, thread_id: int, title: str) -> None:
        self.store.rename_thread(thread_id, title)

    def delete_thread(self, thread_id: int) -> None:
        self.store.delete_thread(thread_id)
        if thread_id == self.thread_id:
            # Land on another thread (or a fresh one) so we always have a current.
            self.thread_id = self.store.latest_thread_id() or self.store.create_thread()

    def search(self, query: str) -> list[dict]:
        return self.store.search_messages(query)
