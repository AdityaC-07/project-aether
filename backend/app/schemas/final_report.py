from __future__ import annotations

from pydantic import BaseModel, Field


class FinalReport(BaseModel):
    what_worked: str
    what_failed: str
    why_it_happened: str
    how_to_improve: str
    synthesis: str = Field(default="")
    recommendation: str = Field(default="")
    confidence_score: float = Field(default=0.0)
