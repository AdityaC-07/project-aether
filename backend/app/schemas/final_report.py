from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from app.schemas.reasoning import ReasoningStep


class FinalReport(BaseModel):
    what_worked: str
    what_failed: str
    why_it_happened: str
    how_to_improve: str
    synthesis: str = Field(default="")
    recommendation: str = Field(default="")
    confidence_score: float = Field(default=0.0)
    reasoning: List[ReasoningStep] = Field(
        ...,
        description="Chain-of-thought steps that led to the synthesized report",
    )
