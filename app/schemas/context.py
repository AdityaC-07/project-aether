from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class Metric(BaseModel):
    name: str
    region: Optional[str] = None
    value: float


class ReasoningContext(BaseModel):
    narrative: str = Field(..., description="Main report text")
    extracted_facts: List[str] = Field(default_factory=list)
    metrics: List[Metric] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
