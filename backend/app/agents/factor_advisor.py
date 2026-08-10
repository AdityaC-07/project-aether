from __future__ import annotations

from typing import List

from pydantic import BaseModel

from app.agents.base_agent import BaseAgent
from app.schemas.context import ReasoningContext
from app.schemas.factor import Factor
from app.schemas.factor_advisor import FactorSuggestion, FactorValidation
from app.utils.logger import StructuredLogger

_DEBATABLE_MARKERS = (
    "whether",
    "should",
    "impact",
    "effect",
    "growth",
    "decline",
    "risk",
    "return",
    "increase",
    "decrease",
    "trend",
    "versus",
    "vs ",
    "compared",
    "relation",
    "adoption",
    "churn",
    "cost",
    "revenue",
    "feasib",
    "trade",
)


class ValidationPayload(BaseModel):
    """Wrapper schema used to validate factor-advisor output."""

    validations: List[FactorValidation]


class SuggestionPayload(BaseModel):
    """Wrapper schema used to validate factor-suggestion output."""

    suggestions: List[FactorSuggestion]


def _fallback_validation(factor: Factor) -> FactorValidation:
    """Deterministic debatability check used when the LLM is unavailable."""
    description = factor.description.strip()
    lowered = description.lower()
    if len(description) < 12:
        return FactorValidation(
            factor_id=factor.factor_id,
            is_debatable=False,
            quality_score=30,
            reason="Too vague to debate meaningfully.",
        )
    if description.rstrip().endswith("?"):
        return FactorValidation(
            factor_id=factor.factor_id,
            is_debatable=True,
            quality_score=min(90, 55 + len(description)),
            reason="Framed as a question, so reasonable arguments exist on both sides.",
        )
    if any(marker in lowered for marker in _DEBATABLE_MARKERS):
        return FactorValidation(
            factor_id=factor.factor_id,
            is_debatable=True,
            quality_score=min(90, 55 + len(description)),
            reason="Contains a testable, two-sided claim.",
        )
    return FactorValidation(
        factor_id=factor.factor_id,
        is_debatable=True,
        quality_score=48,
        reason="Potentially debatable, but the phrasing could be sharper.",
    )


class FactorAdvisorAgent(BaseAgent):
    """Validates candidate factors for debatability and suggests related ones.

    Uses two dedicated prompts (``factor_advisor_validate`` and
    ``factor_advisor_suggest``). When the LLM is unavailable or the output does
    not parse, it degrades gracefully: heuristic validation for the quality
    check, and no suggestions for the suggestion step.
    """

    async def validate_factors(
        self,
        context: ReasoningContext,
        factors: List[Factor],
        *,
        trace: StructuredLogger | None = None,
    ) -> List[FactorValidation]:
        if not factors:
            return []
        rendered = self._render_prompt(
            "factor_advisor_validate",
            context_json=context.model_dump_json(),
            factors_json=self._factors_json(factors),
        )
        try:
            content = await self._complete(
                rendered,
                input_context={"context": context.model_dump_json()},
                trace=trace,
                agent_name="factor_advisor_validate",
            )
            result = await self._parse_structured(
                content,
                schema=ValidationPayload,
                agent_name="factor_advisor_validate",
            )
            payload = result.model if result.model is not None else (
                ValidationPayload.model_validate(result.data) if result.data else None
            )
            self._finalize_run(
                context_text=context.model_dump_json(),
                expected_schema=ValidationPayload,
            )
            if payload is not None:
                return self._complete_validations(factors, payload.validations)
        except Exception:
            pass
        return [self._complete_one(factor, _fallback_validation(factor)) for factor in factors]

    async def suggest_factors(
        self,
        context: ReasoningContext,
        factors: List[Factor],
        *,
        trace: StructuredLogger | None = None,
    ) -> List[FactorSuggestion]:
        if not factors:
            return []
        rendered = self._render_prompt(
            "factor_advisor_suggest",
            context_json=context.model_dump_json(),
            factors_json=self._factors_json(factors),
        )
        try:
            content = await self._complete(
                rendered,
                input_context={"context": context.model_dump_json()},
                trace=trace,
                agent_name="factor_advisor_suggest",
            )
            result = await self._parse_structured(
                content,
                schema=SuggestionPayload,
                agent_name="factor_advisor_suggest",
            )
            payload = result.model if result.model is not None else (
                SuggestionPayload.model_validate(result.data) if result.data else None
            )
            self._finalize_run(
                context_text=context.model_dump_json(),
                expected_schema=SuggestionPayload,
            )
            if payload is not None:
                return payload.suggestions[:4]
        except Exception:
            pass
        return []

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _factors_json(factors: List[Factor]) -> str:
        import json

        return json.dumps([f.dict() for f in factors], ensure_ascii=False)

    @staticmethod
    def _complete_one(factor: Factor, validation: FactorValidation) -> FactorValidation:
        return validation.model_copy(
            update={
                "factor_id": factor.factor_id,
                "refinement": validation.refinement or None,
            }
        )

    @classmethod
    def _complete_validations(
        cls,
        factors: List[Factor],
        validations: List[FactorValidation],
    ) -> List[FactorValidation]:
        by_id = {validation.factor_id: validation for validation in validations}
        return [
            cls._complete_one(factor, by_id.get(factor.factor_id, _fallback_validation(factor)))
            for factor in factors
        ]
