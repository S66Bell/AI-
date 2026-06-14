"""SQLite-backed persistence for JARVIS.

Long-term facts still live in a JSON file (see memory.py). This database holds
the things that benefit from structured queries:

* conversation **threads** and their messages — so JARVIS can keep several
  separate conversations you can switch between and search;
* **reminders / follow-ups** for a proactive assistant.

It's a single SQLite file in the data directory, so on a Hugging Face Space it
persists exactly when you enable persistent storage (JARVIS_DATA_DIR=/data/...).
Single-user, low-traffic: one connection guarded by a lock is plenty.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Store:
    def __init__(self, data_dir: Path):
        self.path = data_dir / "jarvis.db"
        # check_same_thread=False: the web server runs turns on worker threads;
        # every access is serialized by our own lock below.
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS threads (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    title      TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id INTEGER NOT NULL,
                    role      TEXT NOT NULL,
                    text      TEXT NOT NULL,
                    ts        TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id);

                CREATE TABLE IF NOT EXISTS reminders (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    text       TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    due_at     TEXT,            -- ISO time; NULL = surface next session
                    surfaced   INTEGER NOT NULL DEFAULT 0,
                    done       INTEGER NOT NULL DEFAULT 0
                );
                """
            )
            self._conn.commit()

    # ── conversation threads ───────────────────────────────────────────
    def create_thread(self, title: str = "") -> int:
        now = _now()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO threads (title, created_at, updated_at) VALUES (?, ?, ?)",
                (title.strip(), now, now),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def latest_thread_id(self) -> int | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM threads ORDER BY updated_at DESC, id DESC LIMIT 1"
            ).fetchone()
            return int(row["id"]) if row else None

    def list_threads(self) -> list[dict]:
        """Threads newest-first, each with a short preview of the last message."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM threads ORDER BY updated_at DESC, id DESC"
            ).fetchall()
            out = []
            for t in rows:
                last = self._conn.execute(
                    "SELECT text FROM messages WHERE thread_id = ? "
                    "ORDER BY id DESC LIMIT 1",
                    (t["id"],),
                ).fetchone()
                out.append(
                    {
                        "id": t["id"],
                        "title": t["title"] or "新しい会話",
                        "updated_at": t["updated_at"],
                        "preview": (last["text"][:60] if last else ""),
                    }
                )
            return out

    def rename_thread(self, thread_id: int, title: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE threads SET title = ? WHERE id = ?", (title.strip(), thread_id)
            )
            self._conn.commit()

    def delete_thread(self, thread_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM messages WHERE thread_id = ?", (thread_id,))
            self._conn.execute("DELETE FROM threads WHERE id = ?", (thread_id,))
            self._conn.commit()

    def thread_exists(self, thread_id: int) -> bool:
        with self._lock:
            return (
                self._conn.execute(
                    "SELECT 1 FROM threads WHERE id = ?", (thread_id,)
                ).fetchone()
                is not None
            )

    # ── messages within a thread ───────────────────────────────────────
    def add_message(self, thread_id: int, role: str, text: str) -> None:
        text = text.strip()
        if not text:
            return
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO messages (thread_id, role, text, ts) VALUES (?, ?, ?, ?)",
                (thread_id, role, text, now),
            )
            self._conn.execute(
                "UPDATE threads SET updated_at = ? WHERE id = ?", (now, thread_id)
            )
            # Auto-title a fresh thread from its first user message.
            if role == "user":
                row = self._conn.execute(
                    "SELECT title FROM threads WHERE id = ?", (thread_id,)
                ).fetchone()
                if row is not None and not (row["title"] or "").strip():
                    title = text[:40] + ("…" if len(text) > 40 else "")
                    self._conn.execute(
                        "UPDATE threads SET title = ? WHERE id = ?", (title, thread_id)
                    )
            self._conn.commit()

    def get_messages(self, thread_id: int, limit: int = 200) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, text, ts FROM messages WHERE thread_id = ? "
                "ORDER BY id ASC LIMIT ?",
                (thread_id, limit),
            ).fetchall()
            return [{"role": r["role"], "text": r["text"], "ts": r["ts"]} for r in rows]

    def recent_messages(self, thread_id: int, history_turns: int) -> list[dict]:
        """Last N turns as {role, content} for seeding the model, trimmed so the
        history starts on a user turn (the API requires that)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, text FROM messages WHERE thread_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (thread_id, history_turns),
            ).fetchall()
        rows = list(reversed(rows))
        messages = [
            {"role": r["role"], "content": r["text"]}
            for r in rows
            if r["role"] in ("user", "assistant") and r["text"]
        ]
        while messages and messages[0]["role"] != "user":
            messages.pop(0)
        return messages

    def clear_thread_messages(self, thread_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM messages WHERE thread_id = ?", (thread_id,))
            self._conn.commit()

    def search_messages(self, query: str, limit: int = 30) -> list[dict]:
        """Threads containing a message matching the query, with a snippet."""
        q = query.strip()
        if not q:
            return []
        with self._lock:
            rows = self._conn.execute(
                "SELECT m.thread_id AS thread_id, t.title AS title, "
                "       m.text AS snippet, MAX(m.id) AS mid "
                "FROM messages m JOIN threads t ON t.id = m.thread_id "
                "WHERE m.text LIKE ? "
                "GROUP BY m.thread_id ORDER BY mid DESC LIMIT ?",
                (f"%{q}%", limit),
            ).fetchall()
            return [
                {
                    "thread_id": r["thread_id"],
                    "title": r["title"] or "新しい会話",
                    "snippet": r["snippet"][:80],
                }
                for r in rows
            ]

    # ── reminders / follow-ups ─────────────────────────────────────────
    def add_reminder(self, text: str, due_at: str | None = None) -> int:
        text = text.strip()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO reminders (text, created_at, due_at) VALUES (?, ?, ?)",
                (text, _now(), due_at or None),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def list_pending(self) -> list[sqlite3.Row]:
        with self._lock:
            return list(
                self._conn.execute(
                    "SELECT * FROM reminders WHERE done = 0 "
                    "ORDER BY (due_at IS NULL), due_at ASC, id ASC"
                )
            )

    def due(self, now: str | None = None) -> list[sqlite3.Row]:
        now = now or _now()
        with self._lock:
            return list(
                self._conn.execute(
                    "SELECT * FROM reminders WHERE done = 0 AND surfaced = 0 "
                    "AND (due_at IS NULL OR due_at <= ?) "
                    "ORDER BY (due_at IS NULL), due_at ASC, id ASC",
                    (now,),
                )
            )

    def mark_surfaced(self, ids: list[int]) -> None:
        if not ids:
            return
        with self._lock:
            self._conn.executemany(
                "UPDATE reminders SET surfaced = 1 WHERE id = ?", [(i,) for i in ids]
            )
            self._conn.commit()

    def complete(self, query: str) -> int:
        query = query.strip()
        with self._lock:
            if query.isdigit():
                cur = self._conn.execute(
                    "UPDATE reminders SET done = 1 WHERE done = 0 AND id = ?",
                    (int(query),),
                )
            else:
                cur = self._conn.execute(
                    "UPDATE reminders SET done = 1 WHERE done = 0 AND text LIKE ?",
                    (f"%{query}%",),
                )
            self._conn.commit()
            return cur.rowcount

    def close(self) -> None:
        with self._lock:
            self._conn.close()
