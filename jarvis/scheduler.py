"""Recurring tasks: run a goal every N minutes or daily at a set time.

Schedules live in ``schedules.json`` under the data directory. A background
thread checks every 20 seconds and hands due schedules to the TaskRunner. If
the phone was asleep (or JARVIS wasn't running) when a run was due, the run
happens as soon as JARVIS is back — once, not once per missed slot.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .agent import TaskRunner

_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _now() -> datetime:
    return datetime.now()


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


def _parse(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


@dataclass
class Schedule:
    id: str
    goal: str
    every_minutes: int | None = None
    daily_at: str | None = None  # "HH:MM" local time
    enabled: bool = True
    created: str = field(default_factory=lambda: _iso(_now()))
    last_run: str | None = None
    next_run: str | None = None
    last_task_id: str | None = None

    def describe(self) -> str:
        if self.daily_at:
            return f"daily at {self.daily_at}"
        if self.every_minutes:
            return f"every {self.every_minutes} min"
        return "manual"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["describe"] = self.describe()
        return d


def compute_next_run(schedule: Schedule, after: datetime) -> datetime | None:
    """The first time strictly after ``after`` at which the schedule is due."""
    if schedule.daily_at:
        m = _TIME_RE.match(schedule.daily_at)
        if not m:
            return None
        hour, minute = int(m.group(1)), int(m.group(2))
        candidate = after.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= after:
            candidate += timedelta(days=1)
        return candidate
    if schedule.every_minutes:
        return after + timedelta(minutes=max(1, int(schedule.every_minutes)))
    return None


class Scheduler:
    def __init__(self, runner: TaskRunner, data_dir: Path, poll_seconds: float = 20.0):
        self.runner = runner
        self.path = data_dir / "schedules.json"
        self.poll_seconds = poll_seconds
        self._items: dict[str, Schedule] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._load()
        self._thread = threading.Thread(target=self._loop, name="jarvis-scheduler", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # ── persistence ────────────────────────────────────────────────────
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            rows = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for row in rows:
            known = {k: row.get(k) for k in Schedule.__dataclass_fields__ if k in row}
            s = Schedule(**known)
            self._items[s.id] = s

    def _save(self) -> None:
        with self._lock:
            rows = [asdict(s) for s in self._items.values()]
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    # ── public API ─────────────────────────────────────────────────────
    def add(self, goal: str, *, every_minutes: int | None = None, daily_at: str | None = None) -> Schedule:
        goal = goal.strip()
        if not goal:
            raise ValueError("A schedule needs a goal.")
        if daily_at and not _TIME_RE.match(daily_at):
            raise ValueError("daily_at must look like HH:MM (24-hour).")
        if not daily_at and not every_minutes:
            raise ValueError("Give either every_minutes or daily_at.")
        if every_minutes is not None and int(every_minutes) < 1:
            raise ValueError("every_minutes must be at least 1.")
        s = Schedule(
            id=uuid.uuid4().hex[:8],
            goal=goal,
            every_minutes=int(every_minutes) if every_minutes else None,
            daily_at=daily_at or None,
        )
        s.next_run = _iso(compute_next_run(s, _now()))
        with self._lock:
            self._items[s.id] = s
        self._save()
        return s

    def remove(self, schedule_id: str) -> bool:
        with self._lock:
            found = self._items.pop(schedule_id, None) is not None
        if found:
            self._save()
        return found

    def set_enabled(self, schedule_id: str, enabled: bool) -> Schedule | None:
        with self._lock:
            s = self._items.get(schedule_id)
            if s is None:
                return None
            s.enabled = enabled
            if enabled:
                s.next_run = _iso(compute_next_run(s, _now()))
        self._save()
        return s

    def run_now(self, schedule_id: str):
        s = self._items.get(schedule_id)
        if s is None:
            return None
        return self._fire(s, _now())

    def list(self) -> list[Schedule]:
        with self._lock:
            return sorted(self._items.values(), key=lambda s: s.created)

    # ── loop ───────────────────────────────────────────────────────────
    def _fire(self, s: Schedule, now: datetime):
        task = self.runner.submit(s.goal, source=f"schedule:{s.id}")
        with self._lock:
            s.last_run = _iso(now)
            s.last_task_id = task.id
            s.next_run = _iso(compute_next_run(s, now))
        self._save()
        return task

    def due(self, now: datetime | None = None) -> list[Schedule]:
        now = now or _now()
        with self._lock:
            items = list(self._items.values())
        out = []
        for s in items:
            if not s.enabled:
                continue
            nxt = _parse(s.next_run)
            if nxt is None:
                nxt = compute_next_run(s, now)
                s.next_run = _iso(nxt)
                continue
            if nxt <= now:
                out.append(s)
        return out

    def tick(self, now: datetime | None = None) -> int:
        """Fire everything that's due. Returns how many tasks were started."""
        now = now or _now()
        fired = 0
        for s in self.due(now):
            self._fire(s, now)
            fired += 1
        return fired

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # never let the scheduler thread die
                pass
            self._stop.wait(self.poll_seconds)
