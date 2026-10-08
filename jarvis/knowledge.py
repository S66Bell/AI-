"""A small on-device knowledge base so MIRA can learn new material.

"Learning" here means: take a web page, a file or pasted text, cut it into
chunks, index it, and pull the most relevant chunks into the conversation
when a question touches them. No extra model is needed: the index is a
character-bigram TF-IDF, which works for Japanese (no word boundaries) as
well as for English, and is tiny and fast for a personal collection.
"""

from __future__ import annotations

import json
import math
import re
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

_WS = re.compile(r"\s+")


def _grams(text: str) -> Counter:
    t = _WS.sub("", text.lower())
    if len(t) < 2:
        return Counter([t]) if t else Counter()
    return Counter(t[i : i + 2] for i in range(len(t) - 1))


def similarity(a: str, b: str) -> float:
    """Cosine similarity of character-bigram counts (0..1)."""
    ga, gb = _grams(a), _grams(b)
    if not ga or not gb:
        return 0.0
    dot = sum(v * gb.get(k, 0) for k, v in ga.items())
    na = math.sqrt(sum(v * v for v in ga.values()))
    nb = math.sqrt(sum(v * v for v in gb.values()))
    return dot / (na * nb) if na and nb else 0.0


def chunk_text(text: str, size: int = 600) -> list[str]:
    """Split on paragraphs, then pack paragraphs into ~size-char chunks."""
    paras = [p.strip() for p in re.split(r"\n\s*\n|\r\n\s*\r\n", text) if p.strip()]
    chunks: list[str] = []
    cur = ""
    for p in paras:
        while len(p) > size * 1.5:  # a single huge paragraph
            chunks.append(p[:size])
            p = p[size:]
        if cur and len(cur) + len(p) + 1 > size:
            chunks.append(cur)
            cur = p
        else:
            cur = f"{cur}\n{p}" if cur else p
    if cur:
        chunks.append(cur)
    return chunks


class Knowledge:
    def __init__(self, data_dir: Path, max_docs: int = 500):
        self.path = data_dir / "knowledge.json"
        self.max_docs = max_docs
        self._docs: list[dict] = []
        self._df: Counter = Counter()
        self._n_chunks = 0
        self._load()

    # ── persistence ────────────────────────────────────────────────────
    def _load(self) -> None:
        if self.path.exists():
            try:
                self._docs = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._docs = []
        self._reindex()

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._docs, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def _reindex(self) -> None:
        self._df = Counter()
        self._n_chunks = 0
        for d in self._docs:
            for c in d["chunks"]:
                c["_g"] = _grams(c["text"])
                self._df.update(c["_g"].keys())
                self._n_chunks += 1

    # ── public API ─────────────────────────────────────────────────────
    def add(self, title: str, text: str, source: str = "text") -> dict:
        text = text.strip()
        if not text:
            raise ValueError("Nothing to learn: the text is empty.")
        chunks = [{"text": c} for c in chunk_text(text)]
        doc = {
            "id": uuid.uuid4().hex[:8],
            "title": (title or source or "untitled").strip()[:120],
            "source": source,
            "added": datetime.now().isoformat(timespec="seconds"),
            "chars": len(text),
            "chunks": chunks,
        }
        self._docs.append(doc)
        self._docs = self._docs[-self.max_docs :]
        self._reindex()
        self._save()
        return self.describe(doc)

    def remove(self, doc_id: str) -> bool:
        before = len(self._docs)
        self._docs = [d for d in self._docs if d["id"] != doc_id]
        if len(self._docs) == before:
            return False
        self._reindex()
        self._save()
        return True

    def describe(self, doc: dict) -> dict:
        return {k: doc[k] for k in ("id", "title", "source", "added", "chars")} | {"chunks": len(doc["chunks"])}

    def list(self) -> list[dict]:
        return [self.describe(d) for d in reversed(self._docs)]

    def __len__(self) -> int:
        return len(self._docs)

    def search(self, query: str, k: int = 3, min_score: float = 0.12) -> list[dict]:
        """Top-k chunks by TF-IDF-weighted bigram cosine."""
        q = _grams(query)
        if not q or not self._n_chunks:
            return []

        def idf(g: str) -> float:
            return math.log(1 + self._n_chunks / (1 + self._df.get(g, 0)))

        qw = {g: v * idf(g) for g, v in q.items()}
        qn = math.sqrt(sum(v * v for v in qw.values())) or 1.0
        hits = []
        for d in self._docs:
            for c in d["chunks"]:
                cg = c["_g"]
                dot = sum(w * cg.get(g, 0) * idf(g) for g, w in qw.items())
                if dot <= 0:
                    continue
                cn = math.sqrt(sum((v * idf(g)) ** 2 for g, v in cg.items())) or 1.0
                score = dot / (qn * cn)
                if score >= min_score:
                    hits.append({"score": round(score, 3), "title": d["title"], "source": d["source"], "text": c["text"]})
        hits.sort(key=lambda h: -h["score"])
        return hits[:k]

    def context_for(self, query: str, k: int = 3, max_chars: int = 1500) -> str:
        """Formatted snippet block to append to a user turn, or ''."""
        hits = self.search(query, k=k)
        if not hits:
            return ""
        out, used = [], 0
        for h in hits:
            piece = f"- ({h['title']}) {h['text']}"
            if used + len(piece) > max_chars:
                piece = piece[: max_chars - used]
            out.append(piece)
            used += len(piece)
            if used >= max_chars:
                break
        return "\n".join(out)
