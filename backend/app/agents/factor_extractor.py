from __future__ import annotations

from typing import List

from fastapi import HTTPException
from pydantic import BaseModel

from app.agents.base_agent import BaseAgent
from app.schemas.context import ReasoningContext
from app.schemas.factor import DomainEnum, Factor, FactorExtraction


class FactorsPayload(BaseModel):
    """Wrapper schema used to validate factor-extractor output."""

    factors: List[Factor]


class FactorExtractorAgent(BaseAgent):
    async def extract_factors(self, context: ReasoningContext) -> FactorExtraction:
        rendered = self._render_prompt(
            "factor_extractor",
            context_json=context.model_dump_json(),
        )

        content = await self._complete(
            rendered,
            input_context={"context": context.model_dump_json()},
        )

        print("\n" + "=" * 60)
        print("RAW LLM OUTPUT (FACTOR EXTRACTOR):")
        print(content)
        print("=" * 60 + "\n")

        try:
            data = self.llm.parse_json(content)
            reasoning = self._parse_reasoning(data)
            raw_factors = data.get("factors", [])
            factors: List[Factor] = []
            for rf in raw_factors:
                # Normalize domain to enum
                domain_value = str(rf.get("domain", "")).strip().lower()
                try:
                    rf["domain"] = DomainEnum(domain_value)
                except ValueError:
                    raise HTTPException(status_code=422, detail=f"Invalid domain: {domain_value}")
                factors.append(Factor(**rf))
            if not factors:
                raise HTTPException(status_code=422, detail="No factors extracted")

            self._finalize_run(
                context_text=context.model_dump_json(),
                expected_schema=FactorsPayload,
                steps=reasoning,
            )
            return FactorExtraction(reasoning=reasoning, factors=factors)
        except HTTPException:
            self._finalize_run(context_text=context.model_dump_json())
            raise
        except Exception as e:
            self._finalize_run(context_text=context.model_dump_json())
            raise HTTPException(status_code=422, detail=f"Factor parsing failed: {e}")
