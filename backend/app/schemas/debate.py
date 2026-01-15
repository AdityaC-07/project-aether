from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from app.schemas.factor import Factor


class SupportArgument(BaseModel):
    claim: str
    evidence: str
    assumption: str


class SupportArguments(BaseModel):
    support_arguments: List[SupportArgument] = Field(default_factory=list)


class CounterArgument(BaseModel):
    target_claim: str
    challenge: str
    risk: str


class OppositionCounterArguments(BaseModel):
    counter_arguments: List[CounterArgument] = Field(default_factory=list)


class DebateTrace(BaseModel):
    factor_id: str
    factor: Factor
    support: SupportArguments
    opposition: OppositionCounterArguments
