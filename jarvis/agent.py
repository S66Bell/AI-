"""Autonomous background tasks — what turns JARVIS from a chatbot into an agent.

A *task* is a goal handed to JARVIS ("find this week's top three AI papers and
summarise them", "check whether my site is up and note any errors") that it
works on by itself: it plans, calls tools as many times as needed, checks its
own result against the goal, and files a final report. Tasks run one at a
time in a background thread — a phone has one model server and limited RAM,
so parallelism would only slow everything down.

Tasks come from three places: the web UI's Tasks tab, the chat (JARVIS can
delegate work to itself with the ``start_background_task`` tool), and the
scheduler (``scheduler.py``) for recurring jobs.
"""

from __future__ import annotations

import json
import queue
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Callable

from .backends import make_backend
from .config import Config
from .memory import Memory
from .persona import build_agent_prompt
from .tools import Tool, ToolContext, build_registry

STATUSES = ("queued", "running", "done", "failed", "cancelled")

# How many finished tasks to keep on disk / show in the UI.
_KEEP = 200


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Task:
    id: str
    goal: str
    source: str = "manual"  # "manual", "chat", or "schedule:<id>"
    status: str = "queued"
    created: str = field(default_factory=_now)
    started: str | None = None
    finished: str | None = None
    steps: int = 0
    log: list[dict] = field(default_factory=list)
    result: str = ""
    error: str = ""

    def to_dict(self, *, with_log: bool = True) -> dict:
        d = asdict(self)
        if not with_log:
            d["log"] = []
            d["log_len"] = len(self.log)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        known = {k: d.get(k) for k in cls.__dataclass_fields__ if k in d}
        return cls(**known)


class TaskRunner:
    """Queues tasks and runs them sequentially on a worker thread."""

    def __init__(self, config: Config, memory: Memory):
        self.config = config
        self.memory = memory
        self.path = config.data_dir / "tasks.json"
        self._tasks: dict[str, Task] = {}
        self._order: list[str] = []
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._lock = threading.RLock()
        self._cancel_requested: set[str] = set()
        self._listeners: list[Callable[[Task, dict], None]] = []
        self._load()
        self._worker = threading.Thread(target=self._loop, name="jarvis-tasks", daemon=True)
        self._worker.start()

    # ── persistence ────────────────────────────────────────────────────
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            rows = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for row in rows:
            task = Task.from_dict(row)
            # Anything that was mid-flight when we last stopped didn't finish.
            if task.status in ("queued", "running"):
                task.status = "failed"
                task.error = "JARVIS was stopped before this task finished."
                task.finished = task.finished or _now()
            self._tasks[task.id] = task
            self._order.append(task.id)

    def _save(self) -> None:
        with self._lock:
            keep = self._order[-_KEEP:]
            rows = [self._tasks[i].to_dict() for i in keep if i in self._tasks]
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    # ── public API ─────────────────────────────────────────────────────
    def submit(self, goal: str, source: str = "manual") -> Task:
        goal = goal.strip()
        if not goal:
            raise ValueError("A task needs a goal.")
        task = Task(id=uuid.uuid4().hex[:8], goal=goal, source=source)
        with self._lock:
            self._tasks[task.id] = task
            self._order.append(task.id)
        self._save()
        self._queue.put(task.id)
        self._notify(task, {"kind": "queued"})
        return task

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.status not in ("queued", "running"):
                return False
            if task.status == "queued":
                task.status = "cancelled"
                task.finished = _now()
            self._cancel_requested.add(task_id)
        self._save()
        return True

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def list(self, limit: int = 50) -> list[Task]:
        with self._lock:
            ids = list(reversed(self._order[-limit:]))
            return [self._tasks[i] for i in ids if i in self._tasks]

    def subscribe(self, fn: Callable[[Task, dict], None]) -> None:
        self._listeners.append(fn)

    def summary_text(self, limit: int = 10) -> str:
        tasks = self.list(limit)
        if not tasks:
            return "No background tasks yet."
        lines = []
        for t in tasks:
            head = f"[{t.id}] {t.status.upper()} — {t.goal[:80]}"
            if t.status == "done" and t.result:
                head += f"\n    result: {t.result[:300]}"
            elif t.error:
                head += f"\n    error: {t.error[:200]}"
            lines.append(head)
        return "\n".join(lines)

    # ── worker ─────────────────────────────────────────────────────────
    def _notify(self, task: Task, event: dict) -> None:
        for fn in list(self._listeners):
            try:
                fn(task, event)
            except Exception:  # a broken listener must never kill the worker
                pass

    def _log(self, task: Task, kind: str, text: str) -> None:
        if not text:
            return
        entry = {"ts": _now(), "kind": kind, "text": text}
        with self._lock:
            # Merge streamed text into the previous entry of the same kind.
            if task.log and kind == "text" and task.log[-1]["kind"] == "text":
                task.log[-1]["text"] += text
            else:
                task.log.append(entry)
        self._notify(task, entry)

    def _loop(self) -> None:
        while True:
            task_id = self._queue.get()
            task = self._tasks.get(task_id)
            if task is None or task.status != "queued":
                continue
            self._run(task)
            self._save()

    def _run(self, task: Task) -> None:
        task.status = "running"
        task.started = _now()
        self._save()
        self._notify(task, {"kind": "started"})

        finished = {"done": False}

        def finish_task(tool_input: dict, _ctx: ToolContext) -> str:
            report = str(tool_input.get("report", "")).strip()
            if not report:
                return "Error: the report must not be empty."
            task.result = report
            finished["done"] = True
            return "Report filed. The task is complete."

        def confirm(question: str) -> bool:
            if self.config.agent_allow_dangerous:
                self._log(task, "status", f"auto-approved: {question.splitlines()[-1].strip()}")
                return True
            self._log(task, "status", "declined a risky action (background tasks can't ask you)")
            return False

        def notify(msg: str) -> None:
            task.steps += 1
            self._log(task, "status", msg)

        registry = build_registry(self.config, include_web=self.config.is_local)
        registry.register(
            Tool(
                name="finish_task",
                description=(
                    "Call this exactly once when the task is complete, with your final "
                    "report for the user. The report should contain the actual findings "
                    "or results, not a description of what you did."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "report": {"type": "string", "description": "The final report."}
                    },
                    "required": ["report"],
                },
                run=finish_task,
            )
        )
        tool_ctx = ToolContext(config=self.config, memory=self.memory, confirm=confirm, notify=notify)

        try:
            backend = make_backend(
                self.config,
                registry,
                tool_ctx,
                self.memory,
                system_fn=lambda: build_agent_prompt(
                    self.config, self.memory.facts_as_text(), self.memory.load_summary()
                ),
                emit=lambda chunk: self._log(task, "text", chunk),
                notify=notify,
                on_thinking=None,
            )
            backend.messages = []  # a task starts from a clean slate
            backend.max_tool_iterations = self.config.agent_max_steps
            backend.should_stop = lambda: task.id in self._cancel_requested

            reply = backend.run_turn(f"Task goal:\n{task.goal}")
            if self._is_cancelled(task):
                return

            if not finished["done"]:
                backend.max_tool_iterations = 4
                reply = backend.run_turn(
                    "You stopped without filing a report. Call finish_task now with "
                    "your final report based on what you have found so far."
                )
                if not finished["done"]:
                    task.result = reply.strip() or "(no report)"

            if self._is_cancelled(task):
                return

            # Self-check: one bounded pass comparing the report with the goal.
            if self.config.agent_self_check and finished["done"]:
                self._log(task, "status", "self-check")
                backend.max_tool_iterations = max(6, self.config.agent_max_steps // 3)
                finished["done"] = False
                backend.run_turn(
                    "Self-check: re-read the task goal and your report. If the report "
                    "fully satisfies the goal, reply with just DONE. If anything is "
                    "missing or unverified, continue working and call finish_task again "
                    "with the complete report."
                )
                if self._is_cancelled(task):
                    return

            task.status = "done"
        except Exception as exc:
            task.status = "failed"
            task.error = f"{type(exc).__name__}: {exc}"
            self._log(task, "error", task.error)
        finally:
            if task.status == "running":
                task.status = "cancelled"
            task.finished = _now()
            self._cancel_requested.discard(task.id)
            self._notify(task, {"kind": "finished", "status": task.status})
            if task.status == "done":
                self.memory.append_turn(
                    "user",
                    f"[System note] Background task finished — goal: {task.goal}\n"
                    f"Result:\n{task.result[:2000]}",
                )

    def _is_cancelled(self, task: Task) -> bool:
        if task.id in self._cancel_requested:
            task.status = "cancelled"
            self._log(task, "status", "cancelled")
            return True
        return False


# ── tools the chat assistant uses to delegate to the runner ───────────────
def get_tools(runner: TaskRunner) -> list[Tool]:
    def start(tool_input: dict, _ctx: ToolContext) -> str:
        task = runner.submit(str(tool_input.get("goal", "")), source="chat")
        return (
            f"Started background task {task.id}. It will run on its own; "
            f"use check_background_tasks to see progress and results."
        )

    def check(tool_input: dict, _ctx: ToolContext) -> str:
        task_id = str(tool_input.get("task_id", "")).strip()
        if task_id:
            task = runner.get(task_id)
            if task is None:
                return f"No task with id {task_id}."
            tail = "\n".join(f"- {e['kind']}: {e['text'][:300]}" for e in task.log[-8:])
            return (
                f"[{task.id}] {task.status.upper()} — {task.goal}\n"
                f"steps: {task.steps}\nresult: {task.result or '(none yet)'}\n"
                f"error: {task.error or '(none)'}\nrecent log:\n{tail}"
            )
        return runner.summary_text()

    return [
        Tool(
            name="start_background_task",
            description=(
                "Delegate a multi-step job to yourself to run in the background "
                "(research, monitoring, long investigations). Returns immediately "
                "with a task id. Use for work that needs many tool calls or would "
                "take a while, so the conversation isn't blocked."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "A clear, self-contained description of what to achieve.",
                    }
                },
                "required": ["goal"],
            },
            run=start,
        ),
        Tool(
            name="check_background_tasks",
            description="List recent background tasks, or show one task's progress and result.",
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Optional task id for details."}
                },
            },
            run=check,
        ),
    ]
