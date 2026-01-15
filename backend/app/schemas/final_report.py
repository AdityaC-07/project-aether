from __future__ import annotations

from pydantic import BaseModel


class FinalReport(BaseModel):
    what_worked: str
    what_failed: str
    why_it_happened: str
    how_to_improve: str
