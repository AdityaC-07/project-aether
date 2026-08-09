from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class FallbackStrategy(str, Enum):
    """The action taken when a primary LLM call cannot succeed."""

    NONE = "none"
    RETRY = "retry"
    USE_CHEAPER_MODEL = "use_cheaper_model"
    USE_CACHE = "use_cache"
    SKIP_AGENT = "skip_agent"


class ModelTier(str, Enum):
    """Model priority tier within the resilient client."""

    PRIMARY = "primary"
    FALLBACK = "fallback"


class FallbackDecision(BaseModel):
    """One logged resilience decision made during a call.

    Every retry, cheaper-model fallback, cache hit, and agent skip is recorded
    here so operators can audit exactly what the system did under load or
    during an outage.
    """

    call_id: str = Field(..., description="Unique id for the logical LLM call")
    agent: str = Field(default="unknown", description="Agent/step that issued the call")
    strategy: FallbackStrategy = FallbackStrategy.NONE
    tier: ModelTier = ModelTier.PRIMARY
    model: str = Field(default="", description="Model that was being attempted")
    attempt: int = Field(default=0, description="0-based attempt index on this model")
    reason: str = Field(default="", description="Human-readable explanation")
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    retry_after_ms: float = Field(default=0.0, description="Backoff delay applied before retry")
    elapsed_ms: float = Field(default=0.0, description="Latency of the attempted call")
    cached: bool = Field(default=False, description="True when the response came from the cache")
    recovery_action: Optional[str] = Field(default=None, description="retry, fallback_model, skip_agent, fail_request")
    user_message: Optional[str] = Field(default=None, description="Sanitized message safe to return to users")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
