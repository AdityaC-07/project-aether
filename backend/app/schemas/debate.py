from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.confidence import FactorConfidence
from app.schemas.factor import Factor
from app.schemas.reasoning import ReasoningStep
from app.schemas.tooling import ToolInvocationRecord


class SupportArgument(BaseModel):
    claim: str
    evidence: str
    assumption: str
    rationale: str = Field(
        default="",
        description="Why this argument was generated (references a reasoning step)",
    )
    tool_citations: List[str] = Field(default_factory=list)


class SupportArguments(BaseModel):
    support_arguments: List[SupportArgument] = Field(default_factory=list)
    reasoning: List[ReasoningStep] = Field(
        ...,
        description="Chain-of-thought steps that led to these arguments",
    )
    tool_usage: List[ToolInvocationRecord] = Field(default_factory=list)


class CounterArgument(BaseModel):
    target_claim: str
    challenge: str
    risk: str
    rationale: str = Field(
        default="",
        description="Why this counter-argument was generated (references a reasoning step)",
    )
    tool_citations: List[str] = Field(default_factory=list)


class OppositionCounterArguments(BaseModel):
    counter_arguments: List[CounterArgument] = Field(default_factory=list)
    reasoning: List[ReasoningStep] = Field(
        ...,
        description="Chain-of-thought steps that led to these counter-arguments",
    )
    tool_usage: List[ToolInvocationRecord] = Field(default_factory=list)


class DebateTrace(BaseModel):
    factor_id: str
    factor: Factor
    support: SupportArguments
    opposition: OppositionCounterArguments
    confidence_data: Optional[FactorConfidence] = Field(
        default=None,
        description="Confidence surface for this factor's debate, filled by the ConfidenceScorer",
    )
    tool_usage: List[ToolInvocationRecord] = Field(default_factory=list)
