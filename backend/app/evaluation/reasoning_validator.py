from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.evaluation.metrics import token_overlap_ratio
from app.schemas.reasoning import ReasoningStep

_STEP_REF_RE = re.compile(r"step\s*(\d+)", re.IGNORECASE)


class StepValidation(BaseModel):
    step_index: int
    status: Literal["valid", "warning", "invalid"]
    issues: List[str] = Field(default_factory=list)


class ReasoningValidation(BaseModel):
    """Result of validating one chain-of-thought trace.

    ``score`` (0..1) is a weighted penalty sum used for reporting.
    ``is_valid`` is strict: any invalid step, global defect, or untraced
    argument makes the trace invalid (warnings alone do not).
    """

    score: float = Field(ge=0, le=1)
    is_valid: bool
    steps_checked: int
    step_checks: List[StepValidation] = Field(default_factory=list)
    global_issues: List[str] = Field(default_factory=list)
    argument_issues: List[str] = Field(default_factory=list)


class ReasoningValidator:
    """Checks a chain-of-thought trace for logical consistency.

    Four checks:
      1. Structure   - steps are consecutive from index 1; no empty fields.
      2. Progress    - a conclusion must not merely restate its thought.
      3. Grounding   - each step's evidence must overlap the source context.
      4. Coherence   - step N+1's thought must build on step N's conclusion.
      5. Alignment   - every emitted argument traces to a reasoning step
                       (via a "Step N" reference or a conclusion match).
    """

    MIN_THOUGHT_CHARS = 8
    MIN_EVIDENCE_GROUNDING = 0.15
    MIN_CHAIN_LINK = 0.05

    def validate_steps(
        self,
        steps: List[ReasoningStep],
        context_text: str = "",
        arguments: Optional[List[Dict[str, Any]]] = None,
    ) -> ReasoningValidation:
        step_checks: List[StepValidation] = []
        global_issues: List[str] = []
        argument_issues: List[str] = []

        if not steps:
            return ReasoningValidation(
                score=0.0,
                is_valid=False,
                steps_checked=0,
                global_issues=["no reasoning steps were captured"],
            )

        indices = [step.step_index for step in steps]
        if indices != list(range(1, len(steps) + 1)):
            global_issues.append(
                f"step indices must be consecutive starting at 1; got {indices}"
            )

        for index, step in enumerate(steps, 1):
            invalid: List[str] = []
            warnings: List[str] = []

            if not step.thought.strip():
                invalid.append("thought is empty")
            elif len(step.thought.strip()) < self.MIN_THOUGHT_CHARS:
                warnings.append(f"thought is very short ({len(step.thought.strip())} chars); be more specific")

            if not step.evidence.strip():
                invalid.append("evidence is empty")

            if not step.conclusion.strip():
                invalid.append("conclusion is empty")
            elif step.thought.strip().lower() == step.conclusion.strip().lower():
                invalid.append("conclusion restates the thought; no logical progress")

            if context_text.strip() and step.evidence.strip():
                grounding = token_overlap_ratio(step.evidence, context_text)
                if grounding < self.MIN_EVIDENCE_GROUNDING:
                    warnings.append(
                        f"evidence only weakly grounded in context (token overlap {grounding:.2f})"
                    )

            if index > 1:
                link = token_overlap_ratio(step.thought, steps[index - 2].conclusion)
                if link < self.MIN_CHAIN_LINK:
                    warnings.append(
                        f"step {step.step_index} does not build on the previous step's "
                        f"conclusion (link {link:.2f})"
                    )

            status: Literal["valid", "warning", "invalid"]
            if invalid:
                status = "invalid"
            elif warnings:
                status = "warning"
            else:
                status = "valid"

            step_checks.append(
                StepValidation(step_index=step.step_index, status=status, issues=invalid + warnings)
            )

        if arguments:
            valid_indices = set(indices)
            for idx, argument in enumerate(arguments, 1):
                rationale = str(argument.get("rationale") or "").strip()
                if not rationale:
                    argument_issues.append(
                        f"argument {idx} has no rationale, so it cannot be traced to a reasoning step"
                    )
                    continue

                refs = [int(match) for match in _STEP_REF_RE.findall(rationale)]
                if refs:
                    missing = [ref for ref in refs if ref not in valid_indices]
                    for ref in missing:
                        argument_issues.append(
                            f"argument {idx} rationale references step {ref}, which does not exist"
                        )
                else:
                    matched = any(
                        token_overlap_ratio(rationale, step.conclusion) > 0.0
                        for step in steps
                    )
                    if not matched:
                        argument_issues.append(
                            f"argument {idx} rationale does not match any step conclusion"
                        )

        score = 1.0
        for check in step_checks:
            if check.status == "invalid":
                score -= 0.25
            elif check.status == "warning":
                score -= 0.1
        score -= 0.2 * len(global_issues)
        score -= 0.1 * len(argument_issues)
        score = max(0.0, round(score, 2))

        has_invalid = any(check.status == "invalid" for check in step_checks)
        is_valid = not has_invalid and not global_issues and not argument_issues

        return ReasoningValidation(
            score=score,
            is_valid=is_valid,
            steps_checked=len(steps),
            step_checks=step_checks,
            global_issues=global_issues,
            argument_issues=argument_issues,
        )
