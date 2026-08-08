from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from pydantic import BaseModel, Field

from app.rag.models import RetrievalContext


class RetrievalMetrics(BaseModel):
    query: str
    backend: str
    strategy: str
    top_k: int
    latency_ms: float
    max_similarity: float = 0.0
    avg_similarity: float = 0.0
    retrieved_chunks: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RetrievalLogger:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(__file__).resolve().parents[2] / "logs" / "retrieval_logs.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, context: RetrievalContext) -> RetrievalMetrics:
        similarities = [match.similarity for match in context.matches]
        metrics = RetrievalMetrics(
            query=context.query,
            backend=context.backend,
            strategy=context.strategy,
            top_k=context.top_k,
            latency_ms=round(context.latency_ms, 2),
            max_similarity=max(similarities) if similarities else 0.0,
            avg_similarity=round(sum(similarities) / len(similarities), 6) if similarities else 0.0,
            retrieved_chunks=len(context.matches),
        )
        self._append(metrics.model_dump())
        return metrics

    def _append(self, payload: Dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

