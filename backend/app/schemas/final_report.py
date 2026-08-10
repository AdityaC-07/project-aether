from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from app.schemas.confidence import ConfidenceReport
from app.schemas.explainability import CounterfactualResult, FeatureImportance
from app.schemas.reasoning import ReasoningStep


class FinalReport(BaseModel):
    what_worked: str
    what_failed: str
    why_it_happened: str
    how_to_improve: str
    synthesis: str = Field(default="")
    recommendation: str = Field(default="")
    confidence_score: float = Field(default=0.0)
    confidence_report: Optional[ConfidenceReport] = Field(
        default=None,
        description="Nuanced confidence surface: per-factor certainty, agreement, and uncertainty breakdown",
    )
    factor_contribution_scores: Dict[str, float] = Field(
        default_factory=dict,
        description="Factor ID -> signed synthesis-quality delta when that factor is removed",
    )
    top_factors: List[str] = Field(
        default_factory=list,
        description="Factor IDs ranked by absolute contribution to the final recommendation",
    )
    feature_importance: Optional[FeatureImportance] = Field(
        default=None,
        description="Permutation-based ranked importance with driver arguments",
    )
    counterfactuals: List[CounterfactualResult] = Field(
        default_factory=list,
        description="What the synthesis would conclude if each factor were removed",
    )
    reasoning: List[ReasoningStep] = Field(
        ...,
        description="Chain-of-thought steps that led to the synthesized report",
    )
