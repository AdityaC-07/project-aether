from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from app.evaluation.metrics import token_overlap_ratio
from app.evaluation.reasoning_validator import ReasoningValidation
from app.schemas.confidence import (
    ArgumentConfidence,
    ConfidenceReport,
    FactorConfidence,
    FactorUncertainty,
    UncertaintyProfile,
    UncertaintySource,
)
from app.schemas.debate import (
    CounterArgument,
    DebateTrace,
    OppositionCounterArguments,
    SupportArgument,
    SupportArguments,
)

_NUMERIC_RE = re.compile(
    r"(?:\d[\d,.]*|%|percent|\b(?:up|down)\s+by\b|\bgrew\b|\bfell\b|\bdeclined\b|\brisen\b)",
    re.IGNORECASE,
)
_HEDGE_RE = re.compile(
    r"\b(maybe|might|could|possibly|perhaps|seems|appears|suggests?|likely|unlikely|may)\b",
    re.IGNORECASE,
)
_CONTRADICTION_RE = re.compile(
    r"\b(not|never|no|nor|isn.?t|aren.?t|didn.?t|doesn.?t|wasn.?t|weren.?t|"
    r"can.?t|cannot|incorrect|inaccurate|wrong|false|contradicts|refutes|"
    r"disputes|unfounded|unsupported|challenges?)\b",
    re.IGNORECASE,
)

_PREMISE_ENGAGEMENT_MIN = 0.3
_CONTRADICTION_MIN = 0.2
_DIRECT_REFUTATION_OVERLAP = 0.5


def _has_numeric(text: str) -> bool:
    return bool(_NUMERIC_RE.search(text))


def _hedged(text: str) -> bool:
    return bool(_HEDGE_RE.search(text))


class ConfidenceScorer:
    """Deterministic, heuristic confidence scoring for debate outputs.

    No LLM judge in the loop: every score is computed from the structured
    arguments, their grounding in the source context, and how the two sides
    engage one another, so the numbers are cheap, reproducible, and safe to run
    on 100% of production calls.

    Scores are 0..100. The core heuristics:

      * higher confidence when evidence is grounded in the source and specific
      * higher confidence when multiple sides engage (agree on) the same premises
      * lower confidence when the opposition directly contradicts a claim
      * lower confidence when evidence is weak, hedged, or ungrounded
    """

    def __init__(self, uncertain_threshold: float = 60.0) -> None:
        self.uncertain_threshold = uncertain_threshold

    # ------------------------------------------------------------------ #
    # Public metrics
    # ------------------------------------------------------------------ #

    def claim_certainty(
        self,
        claim: str,
        evidence: str,
        context_text: str = "",
        *,
        contradicted: bool = False,
    ) -> float:
        """Rate how certain a single claim is, 0..100."""
        score, _ = self._certainty_components(claim, evidence, context_text, contradicted)
        return score

    def evidence_quality(self, evidence: str, context_text: str = "") -> float:
        """Rate evidence strength, 0..100.

        Components: specificity (0-40), grounding in the source context (0-40),
        and credibility proxy via hedging language (0-20).
        """
        score, _ = self._evidence_components(evidence, context_text)
        return score

    def support_opposition_agreement(
        self,
        support: SupportArguments,
        opposition: OppositionCounterArguments,
    ) -> float:
        """How much the two sides agree on premises, 0..100."""
        _, _, agreement = self._agreement_components(support, opposition)
        return agreement

    # ------------------------------------------------------------------ #
    # Scoring pipeline
    # ------------------------------------------------------------------ #

    def score_debate(self, debate: DebateTrace, context_text: str = "") -> FactorConfidence:
        """Score a full factor debate into a FactorConfidence."""
        support_conf = self._score_support_arguments(debate.support, debate.opposition, context_text)
        opposition_conf = self._score_opposition_arguments(debate.opposition, context_text)
        premise_overlap, contradiction, agreement = self._agreement_components(
            debate.support, debate.opposition
        )

        all_args = support_conf + opposition_conf
        if all_args:
            mean_arg_conf = sum(a.confidence for a in all_args) / len(all_args)
            mean_evidence = sum(a.evidence_quality for a in all_args) / len(all_args)
        else:
            mean_arg_conf = 0.0
            mean_evidence = 0.0

        confidence = round(0.65 * mean_arg_conf + 0.35 * agreement, 1)
        uncertainty = self._factor_uncertainty(
            mean_evidence, premise_overlap, contradiction, confidence
        )
        justification = self._factor_justification(
            confidence, agreement, mean_arg_conf, len(all_args), uncertainty
        )

        return FactorConfidence(
            factor_id=debate.factor_id,
            confidence=confidence,
            support_opposition_agreement=agreement,
            arguments=all_args,
            uncertainty=uncertainty,
            justification=justification,
        )

    def build_report(
        self,
        debates: List[DebateTrace],
        synthesis_validation: Optional[ReasoningValidation] = None,
    ) -> ConfidenceReport:
        """Aggregate per-factor confidence into the final confidence report.

        ``synthesis_validation`` is the reasoning validation of the synthesis
        agent's chain-of-thought, used to gauge how coherently consensus was
        reached.
        """
        factor_confidences: List[FactorConfidence] = [
            debate.confidence_data
            for debate in debates
            if debate.confidence_data is not None
        ]

        if not factor_confidences:
            return ConfidenceReport(
                overall_confidence=0.0,
                synthesizer_confidence=0.0,
                synthesizer_justification="No factor confidence data was available.",
                uncertain_factors=[],
                uncertainty_breakdown={"epistemic": 0.0, "aleatoric": 0.0},
            )

        mean_factor_conf = sum(f.confidence for f in factor_confidences) / len(factor_confidences)
        mean_agreement = sum(f.support_opposition_agreement for f in factor_confidences) / len(
            factor_confidences
        )

        synthesizer_confidence = mean_agreement
        if synthesis_validation is not None:
            synthesizer_confidence = round(
                0.6 * mean_agreement + 0.4 * (synthesis_validation.score * 100.0), 1
            )

        overall_confidence = round(0.7 * mean_factor_conf + 0.3 * synthesizer_confidence, 1)

        uncertain_factors = [
            FactorUncertainty(
                factor_id=f.factor_id,
                confidence=f.confidence,
                uncertainty_source=f.uncertainty.uncertainty_source,
                magnitude=f.uncertainty.magnitude,
                reason=f.uncertainty.description,
            )
            for f in factor_confidences
            if f.confidence < self.uncertain_threshold
        ]

        breakdown: Dict[str, float] = {"epistemic": 0.0, "aleatoric": 0.0}
        for f in factor_confidences:
            key = f.uncertainty.uncertainty_source.value
            breakdown[key] += f.uncertainty.magnitude
        breakdown = {
            key: round(value / len(factor_confidences), 2) for key, value in breakdown.items()
        }

        return ConfidenceReport(
            overall_confidence=overall_confidence,
            synthesizer_confidence=round(synthesizer_confidence, 1),
            synthesizer_justification=self._synthesizer_justification(
                mean_agreement, factor_confidences, uncertain_factors, synthesis_validation
            ),
            uncertain_factors=uncertain_factors,
            uncertainty_breakdown=breakdown,
        )

    # ------------------------------------------------------------------ #
    # Argument-level scoring
    # ------------------------------------------------------------------ #

    def _score_support_arguments(
        self,
        support: SupportArguments,
        opposition: OppositionCounterArguments,
        context_text: str,
    ) -> List[ArgumentConfidence]:
        confidences: List[ArgumentConfidence] = []
        for index, argument in enumerate(support.support_arguments, 1):
            contradicted = self._is_contradicted(argument, opposition.counter_arguments)
            confidences.append(
                self._score_argument(
                    index=index,
                    role="support",
                    claim=argument.claim,
                    evidence=argument.evidence,
                    context_text=context_text,
                    contradicted=contradicted,
                    hedge_text=argument.claim,
                )
            )
        return confidences

    def _score_opposition_arguments(
        self,
        opposition: OppositionCounterArguments,
        context_text: str,
    ) -> List[ArgumentConfidence]:
        confidences: List[ArgumentConfidence] = []
        for index, counter in enumerate(opposition.counter_arguments, 1):
            evidence = f"{counter.challenge} {counter.risk}".strip()
            confidences.append(
                self._score_argument(
                    index=index,
                    role="opposition",
                    claim=counter.challenge,
                    evidence=evidence,
                    context_text=context_text,
                    contradicted=False,
                    hedge_text=counter.challenge,
                )
            )
        return confidences

    def _score_argument(
        self,
        *,
        index: int,
        role: str,
        claim: str,
        evidence: str,
        context_text: str,
        contradicted: bool,
        hedge_text: str,
    ) -> ArgumentConfidence:
        certainty, reasons = self._certainty_components(claim, evidence, context_text, contradicted)
        evidence_score, quality_blurb = self._evidence_components(evidence, context_text, hedge_text)
        confidence = round(0.6 * certainty + 0.4 * evidence_score, 1)
        justification = self._argument_justification(certainty, evidence_score, reasons, quality_blurb)
        return ArgumentConfidence(
            argument_index=index,
            role=role,
            claim=claim,
            confidence=confidence,
            claim_certainty=certainty,
            evidence_quality=evidence_score,
            justification=justification,
        )

    def _certainty_components(
        self,
        claim: str,
        evidence: str,
        context_text: str,
        contradicted: bool,
    ) -> Tuple[float, List[str]]:
        """Compute claim certainty plus the reasons that moved the score."""
        claim = (claim or "").strip()
        evidence = (evidence or "").strip()
        if not claim and not evidence:
            return 0.0, ["the argument has no claim or evidence"]

        score = 100.0
        reasons: List[str] = []

        grounding = (
            token_overlap_ratio(evidence, context_text) if context_text.strip() else 0.0
        )
        if grounding < 0.2:
            score -= 30
            reasons.append(f"evidence is weakly grounded in the source (overlap {grounding:.2f})")
        elif grounding < 0.4:
            score -= 15
            reasons.append(f"evidence is only moderately grounded (overlap {grounding:.2f})")

        if not _has_numeric(evidence):
            score -= 15
            reasons.append("evidence lacks quantified or specific support")

        if _hedged(claim):
            score -= 10
            reasons.append("the claim is hedged rather than asserted")

        if len(claim) < 12:
            score -= 10
            reasons.append("the claim is very short / underspecified")

        if contradicted:
            score -= 25
            reasons.append("the opposing side directly contradicts this claim")

        if not reasons:
            reasons.append("claim is specific, quantified, and grounded")
        return round(max(0.0, min(100.0, score)), 1), reasons

    def _evidence_components(
        self,
        evidence: str,
        context_text: str,
        hedge_text: Optional[str] = None,
    ) -> Tuple[float, str]:
        """Compute evidence quality plus a human-readable quality blurb."""
        evidence = (evidence or "").strip()
        if not evidence:
            return 0.0, "no evidence supplied"

        score = 0.0
        if _has_numeric(evidence):
            score += 40
        elif len(evidence) >= 40:
            score += 20

        grounding = (
            token_overlap_ratio(evidence, context_text) if context_text.strip() else 0.0
        )
        score += min(40.0, grounding * 100.0)

        if hedge_text is not None:
            score += 20 if not _hedged(hedge_text) else 10
        else:
            score += 20 if not _hedged(evidence) else 10

        score = round(min(100.0, score), 1)
        if score >= 80:
            blurb = "strong, specific, well-grounded"
        elif score >= 55:
            blurb = "moderate quality"
        else:
            blurb = "weak or poorly grounded"
        return score, blurb

    def _is_engaged(
        self, argument: SupportArgument, counter_arguments: List[CounterArgument]
    ) -> bool:
        """True when opposition addresses (engages) this claim's premise."""
        return any(
            token_overlap_ratio(argument.claim, counter.target_claim) >= _PREMISE_ENGAGEMENT_MIN
            for counter in counter_arguments
        )

    def _is_contradicted(
        self, argument: SupportArgument, counter_arguments: List[CounterArgument]
    ) -> bool:
        """True when opposition engages the claim AND refutes its facts.

        A direct refutation is recognized by explicit negation/refutation
        language (\"did not drop\", \"factually wrong\") or by very high
        lexical overlap with the support evidence (the opposition restating
        the same facts to dispute them). Merely reusing a keyword such as
        \"decline\" is not enough.
        """
        for counter in counter_arguments:
            premise = token_overlap_ratio(argument.claim, counter.target_claim)
            if premise < _PREMISE_ENGAGEMENT_MIN:
                continue
            challenge_text = f"{counter.challenge} {counter.risk}".strip()
            if _CONTRADICTION_RE.search(challenge_text):
                return True
            if challenge_text and token_overlap_ratio(
                argument.evidence, challenge_text
            ) >= _DIRECT_REFUTATION_OVERLAP:
                return True
        return False

    def _agreement_components(
        self,
        support: SupportArguments,
        opposition: OppositionCounterArguments,
    ) -> Tuple[float, float, float]:
        """(premise_overlap, factual_contradiction, agreement) for a debate.

        For each support premise:

          * ignored      - opposition never addresses the premise.
          * contradicted - opposition engages the premise and directly refutes
                           its evidence.
          * agreed       - opposition engages the premise without refuting its
                           facts.

        * premise_overlap       = engaged / total premises (0..1)
        * factual_contradiction = contradicted / total premises (0..1)
        * agreement             = agreed / total premises (0..1), the fraction
                                  of premises the two sides actually concur on
        """
        support_args = support.support_arguments
        counter_args = opposition.counter_arguments
        if not support_args or not counter_args:
            return 0.0, 0.0, 0.0

        engaged_count = 0
        contradicted_count = 0
        agreed_count = 0
        for argument in support_args:
            engaged = self._is_engaged(argument, counter_args)
            contradicted = engaged and self._is_contradicted(argument, counter_args)
            if engaged:
                engaged_count += 1
                if contradicted:
                    contradicted_count += 1
                else:
                    agreed_count += 1

        total = len(support_args)
        premise_overlap = engaged_count / total
        factual_contradiction = contradicted_count / total
        agreement = agreed_count / total * 100.0
        return (
            premise_overlap,
            factual_contradiction,
            round(max(0.0, min(100.0, agreement)), 1),
        )

    # ------------------------------------------------------------------ #
    # Uncertainty classification
    # ------------------------------------------------------------------ #

    def _factor_uncertainty(
        self,
        mean_evidence: float,
        premise_overlap: float,
        factual_contradiction: float,
        confidence: float,
    ) -> UncertaintyProfile:
        magnitude = round(max(0.0, min(1.0, (100.0 - confidence) / 100.0)), 2)

        if mean_evidence < 55.0:
            source = UncertaintySource.EPISTEMIC
            description = (
                "Evidence is weak or not specific enough to pin down the factor; "
                "more information would reduce the uncertainty."
            )
        elif premise_overlap >= _PREMISE_ENGAGEMENT_MIN and factual_contradiction >= _CONTRADICTION_MIN:
            source = UncertaintySource.ALEATORIC
            description = (
                "Both sides engage the same premises but directly contradict the facts, "
                "leaving an irreducible disagreement on the evidence."
            )
        else:
            source = UncertaintySource.EPISTEMIC
            description = "Residual uncertainty from evidence that could not be fully grounded."

        if magnitude < 0.2:
            description = "The factor is well supported; only residual uncertainty remains."

        return UncertaintyProfile(
            uncertainty_source=source,
            magnitude=magnitude,
            description=description,
        )

    # ------------------------------------------------------------------ #
    # Justification strings (the WHY)
    # ------------------------------------------------------------------ #

    def _argument_justification(
        self,
        certainty: float,
        evidence_score: float,
        reasons: List[str],
        quality_blurb: str,
    ) -> str:
        penalty_note = "; ".join(reasons)
        return (
            f"Claim certainty {certainty}/100 ({penalty_note}). "
            f"Evidence quality {evidence_score}/100 ({quality_blurb})."
        )

    def _factor_justification(
        self,
        confidence: float,
        agreement: float,
        mean_arg_conf: float,
        argument_count: int,
        uncertainty: UncertaintyProfile,
    ) -> str:
        return (
            f"Factor confidence {confidence}/100. Support/opposition agreement {agreement}/100; "
            f"mean argument confidence {round(mean_arg_conf, 1)}/100 over {argument_count} arguments. "
            f"Uncertainty: {uncertainty.uncertainty_source.value} (magnitude {uncertainty.magnitude})."
        )

    def _synthesizer_justification(
        self,
        mean_agreement: float,
        factor_confidences: List[FactorConfidence],
        uncertain_factors: List[FactorUncertainty],
        synthesis_validation: Optional[ReasoningValidation],
    ) -> str:
        parts = [
            f"Consensus across {len(factor_confidences)} factors: "
            f"mean support/opposition agreement {round(mean_agreement, 1)}/100."
        ]
        if uncertain_factors:
            flags = ", ".join(
                f"{f.factor_id} ({f.uncertainty_source.value}, magnitude {f.magnitude})"
                for f in uncertain_factors
            )
            parts.append(f"Factors below the confidence threshold: {flags}.")
        if synthesis_validation is not None:
            parts.append(
                f"Synthesis chain-of-thought validated at {synthesis_validation.score:.2f} "
                f"({'valid' if synthesis_validation.is_valid else 'invalid'})."
            )
        return " ".join(parts)
