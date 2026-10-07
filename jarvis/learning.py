"""Continuous learning through memory.

A local model can't be re-trained on a phone, but MIRA can still get to know
the user better every day. After every few turns a background *reflection*
asks the model to pull durable facts out of the recent conversation (name,
preferences, people, plans, recurring requests) and stores the new ones in
long-term memory. When the transcript grows long, the oldest part is folded
into a rolling summary so nothing important is forgotten when the history
window moves on. Both go into the system prompt every session.
"""

from __future__ import annotations

import json
import queue
import re
import threading
from datetime import datetime
from typing import Callable

from .backends import make_backend
from .config import Config
from .memory import Memory
from .tools import ToolContext, ToolRegistry

_JSON_ARRAY_RE = re.compile(r"\[[\s\S]*\]")


def _reflect_system(config: Config) -> str:
    return (
        "あなたは記憶整理係。会話ログからユーザーについて今後も役立つ事実だけを抽出する。\n"
        "対象: 名前・呼び名、好み・苦手、仕事や生活の状況、人間関係、予定や目標、"
        "よく頼まれること、こう接してほしいという希望。\n"
        "対象外: 一時的な話題、挨拶、AI自身の発言、すでに記憶済みのこと、推測。\n"
        "出力は JSON の文字列配列だけ。各要素は日本語で短い一文。該当なしなら []。"
    )


def _summary_system(config: Config) -> str:
    return (
        "あなたは記憶整理係。これまでの要約と新しい会話ログを統合して、"
        "ユーザーとの関係や進行中の話題が分かる要約を日本語で書く。"
        "重要な出来事、決まったこと、継続中の話題を残し、些末な話は捨てる。"
        "400字以内。前置きなしで要約本文だけを出力。"
    )


class Learner:
    """Runs reflection / summarisation jobs on a background thread."""

    def __init__(self, config: Config, memory: Memory, *, log: Callable[[str], None] | None = None):
        self.config = config
        self.memory = memory
        self.log = log or (lambda _m: None)
        self.every = max(1, config.reflect_every)
        self._since_reflect = 0
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._backend = None
        self._lock = threading.Lock()
        self.last_result: dict = {}
        self._thread = threading.Thread(target=self._loop, name="mira-learner", daemon=True)
        self._thread.start()

    # ── hooks ──────────────────────────────────────────────────────────────────
    def note_turn(self) -> None:
        """Call after each completed chat turn."""
        if not self.config.reflect_enabled:
            return
        self._since_reflect += 1
        if self._since_reflect >= self.every:
            self._since_reflect = 0
            self.request("reflect")
        if len(self.memory.recent_rows(self.memory.summary_after + 1)) > self.memory.summary_after:
            self.request("summarise")

    def request(self, job: str) -> None:
        self._queue.put(job)

    # ── model access ──────────────────────────────────────────────────────────
    def _ask(self, system: str, prompt: str) -> str:
        with self._lock:
            backend = make_backend(
                self.config,
                ToolRegistry(),
                ToolContext(config=self.config, memory=self.memory, confirm=lambda _q: False),
                self.memory,
                system_fn=lambda: system,
                emit=lambda _c: None,
                notify=lambda _m: None,
            )
            backend.messages = []
            backend.max_tool_iterations = 1
            return backend.run_turn(prompt)

    # ── jobs ───────────────────────────────────────────────────────────────────
    def _loop(self) -> None:
        while True:
            job = self._queue.get()
            try:
                if job == "reflect":
                    self.reflect()
                elif job == "summarise":
                    self.summarise()
            except Exception as exc:  # learning must never break the chat
                self.log(f"learning {job} failed: {type(exc).__name__}: {exc}")

    def reflect(self) -> list[str]:
        rows = self.memory.recent_rows(self.every * 2 + 4)
        rows = [r for r in rows if not str(r.get("text", "")).startswith("[System note]")]
        if not rows:
            return []
        transcript = "\n".join(
            f"{'ユーザー' if r['role'] == 'user' else self.config.assistant_name}: {r['text'][:600]}"
            for r in rows
        )
        known = self.memory.facts_as_text() or "(なし)"
        prompt = f"■ すでに記憶済み\n{known}\n\n■ 最近の会話\n{transcript}\n\n新しく記憶すべき事実を JSON 配列で。"
        reply = self._ask(_reflect_system(self.config), prompt)
        facts = _parse_facts(reply)
        added = []
        for fact in facts:
            if self.memory.has_similar_fact(fact):
                continue
            self.memory.remember(fact, source="auto")
            added.append(fact)
        self.last_result = {"job": "reflect", "at": datetime.now().isoformat(timespec="seconds"), "added": added}
        if added:
            self.log(f"learned: {'; '.join(added)}")
        return added

    def summarise(self) -> str:
        rows = self.memory.recent_rows(10_000)
        keep = self.memory.history_turns
        if len(rows) <= self.memory.summary_after:
            return self.memory.load_summary()
        old, recent = rows[:-keep], rows[-keep:]
        transcript = "\n".join(
            f"{'ユーザー' if r['role'] == 'user' else self.config.assistant_name}: {r['text'][:400]}"
            for r in old
            if not str(r.get("text", "")).startswith("[System note]")
        )
        previous = self.memory.load_summary() or "(まだなし)"
        prompt = f"■ これまでの要約\n{previous}\n\n■ 新しく畳む会話ログ\n{transcript}\n\n統合した要約:"
        summary = self._ask(_summary_system(self.config), prompt).strip()
        if summary:
            self.memory.save_summary(summary)
            self.memory.rewrite_history(recent)
            self.log(f"summarised {len(old)} old turns into memory")
        self.last_result = {"job": "summarise", "at": datetime.now().isoformat(timespec="seconds"), "folded": len(old)}
        return summary


def _parse_facts(reply: str) -> list[str]:
    m = _JSON_ARRAY_RE.search(reply or "")
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    out = []
    for item in data if isinstance(data, list) else []:
        text = item.get("fact") if isinstance(item, dict) else item
        if isinstance(text, str) and 2 < len(text.strip()) < 200:
            out.append(text.strip())
    return out
