from __future__ import annotations

from pydantic import BaseModel, Field


class ReasoningStep(BaseModel):
    """One explicit chain-of-thought step: [thought] -> [evidence] -> [conclusion].

    Represents a single inference in the agent's reasoning chain. Consecutive
    steps should be linked: the conclusion of step N informs the thought of
    step N+1, and the final conclusions ground the arguments the agent emits.
    """

    step_index: int = Field(..., ge=1, description="Position in the chain (1-based, consecutive)")
    thought: str = Field(..., description="The insight: why this step matters")
    evidence: str = Field(..., description="Context-grounded evidence this step relies on")
    conclusion: str = Field(..., description="What this step establishes")
