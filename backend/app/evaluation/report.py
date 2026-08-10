from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from app.evaluation.tracker import PromptRun


class PromptVariantStats(BaseModel):
    """Aggregate performance of one (prompt, version) across many runs."""

    prompt_name: str
    prompt_version: str
    sample_size: int
    mean_relevance: float
    mean_format_adherence: float
    mean_argument_strength: float
    mean_overall: float
    std_overall: float = 0.0
    domain_breakdown: Dict[str, float] = Field(
        default_factory=dict, description="Domain -> mean overall score"
    )
    rank: int = Field(0, description="1 is best; 0 until ranked")


class PromptPerformanceReport(BaseModel):
    """Ranked effectiveness report across prompt versions."""

    generated_at: datetime
    weights: Dict[str, float]
    total_runs: int
    variants: List[PromptVariantStats]


class ReportGenerator:
    """Aggregates PromptRuns into a ranked performance report.

    Variants with fewer than ``min_samples`` runs are excluded so small
    samples do not skew promotion decisions. Ranking uses the same weighted
    overall score the MetricsEngine computes, so the report and live tracking
    always agree.
    """

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        min_samples: int = 2,
    ) -> None:
        from app.evaluation.metrics import MetricsEngine

        self.weights = dict(weights or MetricsEngine.DEFAULT_WEIGHTS)
        self.min_samples = min_samples

    def generate(self, runs: List[PromptRun]) -> PromptPerformanceReport:
        grouped: Dict[tuple[str, str], List[PromptRun]] = defaultdict(list)
        for run in runs:
            if run.metrics is None:
                continue
            grouped[(run.prompt_name, run.prompt_version)].append(run)

        variants: List[PromptVariantStats] = []
        for (prompt_name, prompt_version), group in grouped.items():
            if len(group) < self.min_samples:
                continue

            overalls = [r.metrics.overall_score for r in group if r.metrics]
            domain_scores: Dict[str, List[float]] = defaultdict(list)
            for run in group:
                if run.metrics is not None and run.domain is not None:
                    domain_scores[run.domain.value].append(run.metrics.overall_score)

            variants.append(
                PromptVariantStats(
                    prompt_name=prompt_name,
                    prompt_version=prompt_version,
                    sample_size=len(group),
                    mean_relevance=_mean("relevance_score", group),
                    mean_format_adherence=_mean("format_adherence", group),
                    mean_argument_strength=_mean("argument_strength", group),
                    mean_overall=round(sum(overalls) / len(overalls), 4),
                    std_overall=_std(overalls),
                    domain_breakdown={
                        domain: round(sum(scores) / len(scores), 4)
                        for domain, scores in domain_scores.items()
                    },
                )
            )

        variants.sort(key=lambda v: v.mean_overall, reverse=True)
        for rank, variant in enumerate(variants, 1):
            variant.rank = rank

        return PromptPerformanceReport(
            generated_at=datetime.now(timezone.utc),
            weights=self.weights,
            total_runs=sum(1 for r in runs if r.metrics is not None),
            variants=variants,
        )

    def to_markdown(self, report: PromptPerformanceReport) -> str:
        lines = [
            "# Prompt Performance Report",
            "",
            f"- Generated: {report.generated_at.isoformat()}",
            f"- Evaluated runs: {report.total_runs}",
            f"- Weights: {report.weights}",
            "",
            "| Rank | Prompt | Version | Runs | Overall | Relevance | Format | Argument | Std |",
            "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for variant in report.variants:
            lines.append(
                f"| {variant.rank} | {variant.prompt_name} | {variant.prompt_version} "
                f"| {variant.sample_size} | {variant.mean_overall:.3f} "
                f"| {variant.mean_relevance:.3f} | {variant.mean_format_adherence:.3f} "
                f"| {variant.mean_argument_strength:.3f} | {variant.std_overall:.3f} |"
            )

        if report.variants:
            best = report.variants[0]
            lines += ["", f"**Recommendation:** promote `{best.prompt_name}@{best.prompt_version}` (overall {best.mean_overall:.3f})."]
        else:
            lines += ["", "_No variant met the minimum sample size for ranking._"]
        return "\n".join(lines) + "\n"


def _mean(field: str, group: List[PromptRun]) -> float:
    values = [getattr(r.metrics, field) for r in group if r.metrics is not None]
    return round(sum(values) / len(values), 4) if values else 0.0


def _std(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    return round(statistics.stdev(values), 4)
