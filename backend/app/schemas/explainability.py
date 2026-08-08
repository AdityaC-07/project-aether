from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class FactorImportance:
    """Contribution of one factor to the final synthesis.

    ``contribution`` is the signed synthesis-quality delta when the factor is
    removed (positive = removing it hurt quality, so it matters; negative =
    removing it improved quality). ``importance`` is the relative share of the
    absolute contributions (ranks sum to 1). ``driver_arguments`` lists the
    arguments from this factor's debate that most influenced the report.
    """

    factor_id: str
    importance: float = 0.0
    contribution: float = 0.0
    rank: int = 0
    driver_arguments: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class FeatureImportance:
    """Ranked factor-importance summary for a full analysis session."""

    method: str = "permutation"
    rankings: List[FactorImportance] = field(default_factory=list)
    total_reruns: int = 0


class CounterfactualResult(BaseModel):
    """What the synthesis would have concluded if a factor were removed."""

    factor_id: str
    contribution: float = Field(
        ..., description="Signed synthesis-quality delta when the factor is removed"
    )
    quality_full: float = Field(ge=0, le=1)
    quality_without: float = Field(ge=0, le=1)
    counterfactual_synthesis: str = Field(default="")
    counterfactual_recommendation: str = Field(default="")
    explanation: str = Field(default="", description="Why this factor mattered")
