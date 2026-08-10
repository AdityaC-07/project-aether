from __future__ import annotations

from typing import Awaitable, Callable, Dict, List, Optional, Tuple

from app.evaluation.metrics import token_overlap_ratio
from app.evaluation.reasoning_validator import ReasoningValidator
from app.schemas.context import ReasoningContext
from app.schemas.debate import DebateTrace
from app.schemas.explainability import (
    CounterfactualResult,
    FactorImportance,
    FeatureImportance,
)
from app.schemas.factor import Factor
from app.schemas.final_report import FinalReport

_REPORT_TEXT_FIELDS = (
    "what_worked",
    "what_failed",
    "why_it_happened",
    "how_to_improve",
    "synthesis",
    "recommendation",
)


def _report_text(report: FinalReport) -> str:
    """Concatenate the substantive narrative fields of a final report."""
    parts = [getattr(report, field) for field in _REPORT_TEXT_FIELDS]
    return " ".join(part for part in parts if part and part.strip())


def _factor_text(factor: Factor) -> str:
    return f"{factor.factor_id} {factor.description} {factor.domain.value}"


class SynthesisQuality:
    """Deterministic 0..1 quality score for a synthesized report.

    Three components (weighted):

      * relevance  - how much of the report's narrative is grounded in the
                     source context
      * coherence  - how logically consistent the report's chain-of-thought is
                     (ReasoningValidator score)
      * coverage   - how well the report reflects the factors it was asked
                     about (token overlap of each factor with the narrative)
    """

    WEIGHTS = {"relevance": 0.4, "coherence": 0.3, "coverage": 0.3}

    def __init__(self) -> None:
        self._validator = ReasoningValidator()

    def score(
        self,
        report: FinalReport,
        context_text: str,
        factors: List[Factor],
    ) -> float:
        report_text = _report_text(report)
        if not report_text.strip():
            return 0.0

        relevance = (
            token_overlap_ratio(report_text, context_text)
            if context_text.strip()
            else 0.0
        )
        coherence = self._validator.validate_steps(report.reasoning, context_text).score
        coverage = self._coverage(report_text, factors)

        return round(
            self.WEIGHTS["relevance"] * relevance
            + self.WEIGHTS["coherence"] * coherence
            + self.WEIGHTS["coverage"] * coverage,
            4,
        )

    @staticmethod
    def _coverage(report_text: str, factors: List[Factor]) -> float:
        if not factors or not report_text.strip():
            return 0.0
        return round(
            sum(token_overlap_ratio(_factor_text(f), report_text) for f in factors)
            / len(factors),
            4,
        )


class CounterfactualAnalyzer:
    """Permutation-based explainability: re-run synthesis without each factor.

    For every factor the full analysis produced, the synthesizer is called
    again with that factor's debate removed, and the resulting report is scored
    against the SAME source context. The quality delta is the factor's
    contribution to the final recommendation.
    """

    def __init__(self, quality: Optional[SynthesisQuality] = None) -> None:
        self.quality = quality or SynthesisQuality()

    async def analyze(
        self,
        *,
        debates: List[DebateTrace],
        context: ReasoningContext,
        full_report: FinalReport,
        synth_fn: Callable[[List[DebateTrace]], Awaitable[FinalReport]],
        max_reruns: Optional[int] = None,
    ) -> List[CounterfactualResult]:
        """Run counterfactual synthesis for each (or the top ``max_reruns``) factor.

        ``synth_fn`` is an async callable that renders a synthesis for a subset
        of debates. When ``max_reruns`` caps the number of reruns, factors are
        permuted in order of how strongly they already appear in the full
        report (cheap proxy for likely importance).
        """
        if not debates:
            return []

        context_text = context.narrative
        factors = [debate.factor for debate in debates]
        quality_full = self.quality.score(full_report, context_text, factors)

        # Pre-rank by how much of the factor's content already landed in the
        # full report, so capped reruns test the most influential factors first.
        report_text = _report_text(full_report)
        ranked_debates = sorted(
            debates,
            key=lambda d: token_overlap_ratio(_factor_text(d.factor), report_text),
            reverse=True,
        )

        limit = len(ranked_debates) if max_reruns is None else max(0, min(max_reruns, len(ranked_debates)))

        results: List[CounterfactualResult] = []
        for debate in ranked_debates[:limit]:
            subset = [d for d in debates if d.factor_id != debate.factor_id]
            try:
                counterfactual = await synth_fn(subset)
            except Exception as exc:  # one bad rerun must not kill the analysis
                print(f"[COUNTERFACTUAL] skip {debate.factor_id}: {exc}")
                continue

            quality_without = self.quality.score(
                counterfactual, context_text, [d.factor for d in subset]
            )
            contribution = quality_full - quality_without
            results.append(
                CounterfactualResult(
                    factor_id=debate.factor_id,
                    contribution=round(contribution, 4),
                    quality_full=quality_full,
                    quality_without=round(quality_without, 4),
                    counterfactual_synthesis=counterfactual.synthesis,
                    counterfactual_recommendation=counterfactual.recommendation,
                    explanation=self._explanation(
                        debate.factor_id, contribution, counterfactual
                    ),
                )
            )
        return results

    @staticmethod
    def _explanation(
        factor_id: str, contribution: float, counterfactual: FinalReport
    ) -> str:
        direction = (
            "contributed meaningfully to the final recommendation"
            if contribution > 0
            else "did not help (removing it held or improved synthesis quality)"
        )
        recommendation = counterfactual.recommendation.strip()
        if recommendation:
            direction += f"; without {factor_id} the recommendation becomes: {recommendation}"
        return direction


class ContributionScorer:
    """Turns counterfactual reruns into ranked factor contributions."""

    def score(
        self,
        debates: List[DebateTrace],
        full_report: FinalReport,
        counterfactuals: List[CounterfactualResult],
    ) -> FeatureImportance:
        if not counterfactuals:
            return FeatureImportance(method="permutation", rankings=[], total_reruns=0)

        report_text = _report_text(full_report)
        contributions = {c.factor_id: c.contribution for c in counterfactuals}
        total_abs = sum(abs(value) for value in contributions.values())
        if total_abs <= 0:
            total_abs = 1.0

        rankings: List[FactorImportance] = []
        ordered = sorted(contributions.items(), key=lambda item: -abs(item[1]))
        for rank, (factor_id, contribution) in enumerate(ordered, 1):
            debate = next((d for d in debates if d.factor_id == factor_id), None)
            drivers = self._driver_arguments(debate, report_text) if debate else []
            rankings.append(
                FactorImportance(
                    factor_id=factor_id,
                    importance=round(abs(contribution) / total_abs, 4),
                    contribution=round(contribution, 4),
                    rank=rank,
                    driver_arguments=drivers,
                )
            )

        return FeatureImportance(
            method="permutation",
            rankings=rankings,
            total_reruns=len(counterfactuals),
        )

    @staticmethod
    def _driver_arguments(
        debate: DebateTrace, report_text: str, top_k: int = 3
    ) -> List[str]:
        """Arguments from this factor's debate most reflected in the report."""
        candidates: List[Tuple[str, str, float]] = []
        for argument in debate.support.support_arguments:
            text = f"{argument.claim} {argument.evidence}"
            candidates.append(
                ("support", argument.claim, token_overlap_ratio(text, report_text))
            )
        for counter in debate.opposition.counter_arguments:
            text = f"{counter.challenge} {counter.risk}"
            candidates.append(
                ("opposition", counter.challenge, token_overlap_ratio(text, report_text))
            )

        ranked = sorted(candidates, key=lambda item: -item[2])
        drivers = [
            f"{role}: {claim[:100]}"
            for role, claim, score in ranked[:top_k]
            if score > 0.0
        ]
        return drivers
