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
    def __init__(self, data_dir: Path, history_turns: int = 40, summary_after: int = 80):
        self.data_dir = data_dir
        self.history_path = data_dir / "conversation.jsonl"
        self.facts_path = data_dir / "memory.json"
        self.summary_path = data_dir / "summary.txt"
        # Learned behaviour rules ("when X, do Y") and task playbook entries.
        self.lessons_path = data_dir / "lessons.json"
        self.playbook_path = data_dir / "playbook.json"
        self.feedback_path = data_dir / "feedback.jsonl"
        self.history_turns = history_turns
        # When the transcript has more rows than this, old turns get folded
        # into the rolling summary (see learning.py).
        self.summary_after = summary_after

    # ── Long-term facts ────────────────────────────────────────────────
    def load_facts(self) -> list[dict]:
        if not self.facts_path.exists():
            return []
        try:
            return json.loads(self.facts_path.read_text())
        except (json.JSONDecodeError, OSError):
            return []

    def remember(self, fact: str, source: str = "user") -> str:
        facts = self.load_facts()
        entry = {
            "fact": fact.strip(),
            "added": datetime.now().isoformat(timespec="seconds"),
            "source": source,
        }
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

    def has_similar_fact(self, fact: str) -> bool:
        """Cheap duplicate check: identical or one contains the other."""
        q = _norm(fact)
        if not q:
            return True
        for f in self.load_facts():
            k = _norm(f.get("fact", ""))
            if q == k or (len(q) > 6 and (q in k or k in q)):
                return True
        return False

    # ── Lessons: how the user wants to be treated ──────────────────────
    def load_lessons(self) -> list[dict]:
        try:
            return json.loads(self.lessons_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def add_lesson(self, text: str, source: str = "feedback", max_items: int = 40) -> bool:
        text = text.strip()
        if not text:
            return False
        items = self.load_lessons()
        q = _norm(text)
        for it in items:
            k = _norm(it.get("text", ""))
            if q == k or (len(q) > 8 and (q in k or k in q)):
                return False
        items.append({"text": text, "source": source, "added": datetime.now().isoformat(timespec="seconds")})
        items = items[-max_items:]
        self.lessons_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        return True

    def forget_lesson(self, query: str) -> int:
        items = self.load_lessons()
        q = query.strip().lower()
        kept = [it for it in items if q not in it["text"].lower()]
        self.lessons_path.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
        return len(items) - len(kept)

    def lessons_as_text(self) -> str:
        return "\n".join(f"- {it['text']}" for it in self.load_lessons())

    def record_feedback(self, entry: dict) -> None:
        entry = dict(entry, ts=datetime.now().isoformat(timespec="seconds"))
        with self.feedback_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ── Playbook: what worked for past tasks ───────────────────────────
    def load_playbook(self) -> list[dict]:
        try:
            return json.loads(self.playbook_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def add_playbook(self, goal: str, lesson: str, max_items: int = 100) -> None:
        items = self.load_playbook()
        items.append({"goal": goal.strip()[:200], "lesson": lesson.strip()[:400], "added": datetime.now().isoformat(timespec="seconds")})
        self.playbook_path.write_text(json.dumps(items[-max_items:], ensure_ascii=False, indent=2), encoding="utf-8")

    def playbook_for(self, goal: str, k: int = 3) -> str:
        from .knowledge import similarity

        items = self.load_playbook()
        scored = sorted(((similarity(goal, it["goal"]), it) for it in items), key=lambda x: -x[0])
        picked = [it for score, it in scored[:k] if score > 0.15]
        return "\n".join(f"- 「{it['goal'][:60]}」のとき: {it['lesson']}" for it in picked)

    # ── Rolling summary of older conversation ──────────────────────────
    def load_summary(self) -> str:
        try:
            return self.summary_path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def save_summary(self, text: str) -> None:
        self.summary_path.write_text(text.strip() + "\n", encoding="utf-8")

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

    def recent_rows(self, limit: int = 60) -> list[dict]:
        """Raw recent transcript rows (role, text, ts) for display in a UI."""
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
        return rows[-limit:]

    def rewrite_history(self, rows: list[dict]) -> None:
        """Replace the transcript with ``rows`` (used after summarising)."""
        tmp = self.history_path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        tmp.replace(self.history_path)

    def clear_history(self) -> str:
        if self.history_path.exists():
            self.history_path.unlink()
        return "Conversation history cleared."


def _norm(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())
