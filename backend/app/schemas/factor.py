from __future__ import annotations

from enum import Enum
from typing import List

from pydantic import BaseModel, Field

from app.schemas.reasoning import ReasoningStep


class DomainEnum(str, Enum):
    sales = "sales"
    statistics = "statistics"
    policy = "policy"
    organization = "organization"


class Factor(BaseModel):
    factor_id: str = Field(..., description="Identifier like F1, F2, ...")
    description: str
    domain: DomainEnum


class FactorExtraction(BaseModel):
    """Factor-extractor output including the chain-of-thought that produced it."""

    reasoning: List[ReasoningStep] = Field(
        ...,
        description="Chain-of-thought steps that led to the extracted factors",
    )
    factors: List[Factor]
