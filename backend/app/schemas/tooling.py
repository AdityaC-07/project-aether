from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ToolInvocationRecord(BaseModel):
    tool_name: str
    display_name: str
    agent: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    success: bool = True
    error: Optional[str] = None
    latency_ms: float = 0.0
    invoked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ToolResponseEnvelope(BaseModel):
    output: Any = None
    error: Optional[str] = None
    tool_name: Optional[str] = None
    display_name: Optional[str] = None


class ToolUsageSummary(BaseModel):
    agent: str
    tool_name: str
    display_name: str
    count: int = 1

