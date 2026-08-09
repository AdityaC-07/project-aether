from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.context import ReasoningContext
from app.schemas.factor import DomainEnum, Factor


class FactorValidation(BaseModel):
    """Result of checking whether a candidate factor is worth debating."""

    factor_id: str
    is_debatable: bool
    quality_score: float = Field(ge=0, le=100, description="0-100 quality of the factor")
    reason: str = Field(..., description="Why the factor is or is not debatable")
    refinement: Optional[str] = Field(
        default=None,
        description="Optional clearer restatement of the factor, when the original is weak",
    )


class FactorSuggestion(BaseModel):
    """A related factor worth adding, derived from the input and selected factors."""

    description: str
    domain: DomainEnum
    relation: str = Field(..., description="How this factor relates to the selected ones")
    rationale: str = Field(..., description="Why this factor is likely worth debating")


class FactorAdviseRequest(BaseModel):
    context: ReasoningContext
    custom_factors: List[Factor] = Field(default_factory=list)


class FactorAdviseResponse(BaseModel):
    narrative: str = Field(default="")
    context: Optional[ReasoningContext] = Field(
        default=None,
        description="Normalized context the plan was derived from, for reuse in the analysis step",
    )
    extracted_factors: List[Factor] = Field(default_factory=list)
    custom_factors: List[Factor] = Field(default_factory=list)
    validations: List[FactorValidation] = Field(default_factory=list)
    suggestions: List[FactorSuggestion] = Field(default_factory=list)
