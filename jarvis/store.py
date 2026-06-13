"""SQLite-backed persistence for JARVIS.

The original long-term memory lives in simple JSON files (see memory.py). This
adds a proper little database for the things that power a *proactive* JARVIS —
reminders and follow-ups it should bring up on its own — where structured
queries (what's due now? what's still pending?) matter.

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
        """Everything not yet completed, soonest-due first."""
        with self._lock:
            return list(
                self._conn.execute(
                    "SELECT * FROM reminders WHERE done = 0 "
                    "ORDER BY (due_at IS NULL), due_at ASC, id ASC"
                )
            )

    def due(self, now: str | None = None) -> list[sqlite3.Row]:
        """Pending reminders worth raising now: not yet surfaced, and either
        undated (raise next time) or past their due time."""
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
                "UPDATE reminders SET surfaced = 1 WHERE id = ?",
                [(i,) for i in ids],
            )
            self._conn.commit()

    def complete(self, query: str) -> int:
        """Mark reminders done by id (if query is a number) or text match.
        Returns how many were completed."""
        query = query.strip()
        with self._lock:
            if query.isdigit():
                cur = self._conn.execute(
                    "UPDATE reminders SET done = 1 WHERE done = 0 AND id = ?",
                    (int(query),),
                )
            else:
                cur = self._conn.execute(
                    "UPDATE reminders SET done = 1 "
                    "WHERE done = 0 AND text LIKE ?",
                    (f"%{query}%",),
                )
            self._conn.commit()
            return cur.rowcount

    def close(self) -> None:
        with self._lock:
            self._conn.close()
