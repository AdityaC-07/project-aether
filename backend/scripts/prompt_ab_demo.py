"""A/B demo: compare two versions of the support prompt end-to-end.

Runs without a live LLM (uses canned responses) so anyone can see the full
pipeline: versioned template resolution -> domain-adaptive few-shot rendering
-> metric evaluation -> run tracking -> ranked performance report.

Usage: python scripts/prompt_ab_demo.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation import PromptRun, PromptTracker, ReportGenerator  # noqa: E402
from app.prompts import PromptRegistry  # noqa: E402
from app.schemas.context import ReasoningContext  # noqa: E402
from app.schemas.debate import SupportArguments  # noqa: E402
from app.schemas.factor import DomainEnum, Factor  # noqa: E402

# Simulated LLM responses: v1 is vague/generic, v2 is quantified and grounded.
CANNED_OUTPUTS = {
    ("1.0.0", "sales"): {
        "support_arguments": [
            {
                "claim": "The deal count decline likely hurt revenue",
                "evidence": "Deal count went down a lot last quarter",
                "assumption": "Revenue depends on deals",
            }
        ]
    },
    ("2.0.0", "sales"): {
        "support_arguments": [
            {
                "claim": "Deal count fell by 70 (33%), the dominant driver of the 12% QoQ revenue drop",
                "evidence": "Deal count dropped from 210 to 140 in the same period revenue fell 12% QoQ",
                "assumption": "Average deal size stayed near $18k, so volume drove the decline",
            }
        ]
    },
    ("1.0.0", "policy"): {
        "support_arguments": [
            {
                "claim": "The program now reaches more firms",
                "evidence": "The cap was increased",
                "assumption": "More firms qualify",
            }
        ]
    },
    ("2.0.0", "policy"): {
        "support_arguments": [
            {
                "claim": "The 50% cap increase ($2M to $3M) expands eligible spend for affected firms",
                "evidence": "Cap raised from $2M to $3M per firm; roughly 120 firms are affected",
                "assumption": "The 30-FTE eligibility floor does not exclude the target mid-size firms",
            }
        ]
    },
}

CONTEXT_TEXT = (
    "Q3 revenue fell 12% QoQ. Deal count dropped from 210 to 140. Average deal "
    "size grew 8% to $18k. Subsidy cap raised from $2M to $3M per firm; "
    "eligibility now requires 30 full-time staff, roughly 120 firms affected."
)

FACTORS = [
    Factor(
        factor_id="F1",
        description="Revenue decline driven by reduced deal count",
        domain=DomainEnum.sales,
    ),
    Factor(
        factor_id="F2",
        description="Raised subsidy cap improves access for mid-size firms",
        domain=DomainEnum.policy,
    ),
]

SCHEMA = SupportArguments  # expected output schema for format-adherence scoring


def main() -> None:
    registry = PromptRegistry()
    tracker = PromptTracker(Path(__file__).resolve().parents[1] / "logs" / "prompt_runs.jsonl")

    context = ReasoningContext(narrative=CONTEXT_TEXT)
    factors = [f for f in FACTORS]
    experiments = [("1.0.0", 6), ("2.0.0", 6)]  # version -> number of simulated runs

    print("Resolving versions from registry:")
    print(f"  deployed support version: {registry.get('support').version}")

    runs = []
    for version, count in experiments:
        template = registry.get("support", version=version)
        print(f"\n--- A/B arm: support v{version} ---")
        for i in range(count):
            factor = factors[i % len(factors)]
            rendered = template.render(
                domain=factor.domain,
                context_json=context.model_dump_json(),
                factor_json=factor.model_dump_json(),
            )
            canned = CANNED_OUTPUTS[(version, factor.domain.value)]
            raw_output = json.dumps(canned)

            # Prove the domain-adaptive few-shot landed in the prompt.
            if i == 0:
                print(
                    f"  domain={factor.domain.value} -> few-shot section present: "
                    f"{'## Examples' in rendered.text}"
                )

            run = PromptRun(
                prompt_name="support",
                prompt_version=version,
                domain=factor.domain,
                input_context={"context": context.model_dump_json(), "factor": factor.model_dump_json()},
                rendered_prompt=rendered.text,
                raw_output=raw_output,
            )
            run.evaluate(context_text=CONTEXT_TEXT, expected_schema=SCHEMA)
            tracker.log(run)
            runs.append(run)

    print(f"\nLogged {len(runs)} runs to {tracker.path}")

    report = ReportGenerator().generate(runs)
    markdown = ReportGenerator().to_markdown(report)
    print("\n" + markdown)

    out_path = Path(__file__).resolve().parents[1] / "logs" / "prompt_performance_report.md"
    out_path.write_text(markdown, encoding="utf-8")
    print(f"Report written to {out_path}")


if __name__ == "__main__":
    main()
