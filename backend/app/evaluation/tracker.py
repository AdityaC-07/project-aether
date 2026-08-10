from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Type
from uuid import uuid4

from pydantic import BaseModel, Field

from app.evaluation.metrics import MetricsEngine, PromptMetrics
from app.evaluation.reasoning_validator import ReasoningValidation
from app.schemas.factor import DomainEnum


class PromptRun(BaseModel):
    """Immutable record tying one generated output to the exact prompt version."""

    run_id: str = Field(default_factory=lambda: uuid4().hex)
    prompt_name: str
    prompt_version: str
    domain: Optional[DomainEnum] = None
    input_context: Dict[str, Any] = Field(default_factory=dict)
    rendered_prompt: str = Field(default_factory=str)
    raw_output: str = Field(default_factory=str)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metrics: Optional[PromptMetrics] = None
    validation: Optional[ReasoningValidation] = None

    def evaluate(
        self,
        *,
        context_text: Optional[str] = None,
        expected_schema: Optional[Type[BaseModel]] = None,
        weights: Optional[Dict[str, float]] = None,
    ) -> PromptMetrics:
        """Compute and attach metrics. Returns the metrics for convenience."""
        engine = MetricsEngine(weights=weights)
        self.metrics = engine.evaluate(
            output=self.raw_output,
            context_text=context_text,
            expected_schema=expected_schema,
        )
        return self.metrics


class PromptTracker:
    """Append-only JSONL store of prompt runs.

    JSONL (one JSON object per line) is chosen over a JSON array so concurrent
    or crashed writes never corrupt earlier runs and appends are O(1).
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        if path is None:
            path = Path(__file__).resolve().parents[2] / "logs" / "prompt_runs.jsonl"
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, run: PromptRun) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(run.model_dump_json() + "\n")

    def load_runs(self, prompt_name: Optional[str] = None) -> List[PromptRun]:
        if not self.path.exists():
            return []

        runs: List[PromptRun] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    run = PromptRun.model_validate_json(line)
                except Exception:
                    continue  # skip corrupt or partial lines
                if prompt_name is None or run.prompt_name == prompt_name:
                    runs.append(run)
        return runs
