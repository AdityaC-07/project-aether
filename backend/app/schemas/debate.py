from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from app.schemas.factor import Factor
from app.schemas.reasoning import ReasoningStep


class SupportArgument(BaseModel):
    claim: str
    evidence: str
    assumption: str
    rationale: str = Field(
        default="",
        description="Why this argument was generated (references a reasoning step)",
    )


class SupportArguments(BaseModel):
    support_arguments: List[SupportArgument] = Field(default_factory=list)
    reasoning: List[ReasoningStep] = Field(
        ...,
        description="Chain-of-thought steps that led to these arguments",
    )


class CounterArgument(BaseModel):
    target_claim: str
    challenge: str
    risk: str
    rationale: str = Field(
        default="",
        description="Why this counter-argument was generated (references a reasoning step)",
    )


class OppositionCounterArguments(BaseModel):
    counter_arguments: List[CounterArgument] = Field(default_factory=list)
    reasoning: List[ReasoningStep] = Field(
        ...,
        description="Chain-of-thought steps that led to these counter-arguments",
    )


class DebateTrace(BaseModel):
    factor_id: str
    factor: Factor
    support: SupportArguments
    opposition: OppositionCounterArguments
