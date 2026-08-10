from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List

from pydantic import BaseModel, Field


class UncertaintySource(str, Enum):
    EPISTEMIC = "epistemic"
    ALEATORIC = "aleatoric"


@dataclass(frozen=True)
class UncertaintyProfile:
    """Why a factor is uncertain, and by how much.

    ``magnitude`` is 0..1 (1 = maximally uncertain). ``uncertainty_source``
    distinguishes epistemic uncertainty (we lack information) from aleatoric
    uncertainty (the evidence genuinely disagrees / is irreducibly noisy).
    """

    uncertainty_source: UncertaintySource
    magnitude: float
    description: str = ""


class ArgumentConfidence(BaseModel):
    """Per-argument confidence breakdown for one support or opposition argument."""

    argument_index: int = Field(..., ge=1)
    role: str = Field(..., description="Either 'support' or 'opposition'")
    claim: str
    confidence: float = Field(ge=0, le=100, description="Overall rating for this argument")
    claim_certainty: float = Field(ge=0, le=100, description="How certain the claim is")
    evidence_quality: float = Field(ge=0, le=100, description="Strength of the supporting evidence")
    justification: str = Field(..., description="Why this confidence score is what it is")


class FactorConfidence(BaseModel):
    """Confidence surface for a single factor's debate."""

    factor_id: str
    confidence: float = Field(ge=0, le=100, description="Overall confidence for this factor")
    support_opposition_agreement: float = Field(
        ge=0, le=100, description="How much the two sides agree on premises"
    )
    arguments: List[ArgumentConfidence] = Field(default_factory=list)
    uncertainty: UncertaintyProfile
    justification: str = Field(..., description="Why this factor confidence is what it is")


class FactorUncertainty(BaseModel):
    """One factor flagged as uncertain in the final confidence report."""

    factor_id: str
    confidence: float = Field(ge=0, le=100)
    uncertainty_source: UncertaintySource
    magnitude: float = Field(ge=0, le=1)
    reason: str = Field(..., description="Why the factor is uncertain")


class ConfidenceReport(BaseModel):
    """Nuanced confidence surface for a full analysis session."""

    overall_confidence: float = Field(ge=0, le=100)
    synthesizer_confidence: float = Field(
        ge=0, le=100, description="How well the debate converged toward consensus"
    )
    synthesizer_justification: str = Field(..., description="Why the synthesizer confidence is what it is")
    uncertain_factors: List[FactorUncertainty] = Field(default_factory=list)
    uncertainty_breakdown: Dict[str, float] = Field(
        default_factory=dict,
        description="Mean magnitude per uncertainty source, e.g. {'epistemic': 0.3, 'aleatoric': 0.1}",
    )
