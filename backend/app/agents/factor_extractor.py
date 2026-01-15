from __future__ import annotations

import json
from typing import List

from fastapi import HTTPException

from app.agents.base_agent import BaseAgent
from app.schemas.context import ReasoningContext
from app.schemas.factor import Factor, DomainEnum


class FactorExtractorAgent(BaseAgent):
    async def extract_factors(self, context: ReasoningContext) -> List[Factor]:
        prompt_template = self._read_prompt("factor_prompt.txt")
        prompt = prompt_template.format(context_json=context.json())

        content = await self.llm.acompletion(prompt)

        print("\n" + "="*60)
        print("🔍 RAW LLM OUTPUT (FACTOR EXTRACTOR):")
        print(content)
        print("="*60 + "\n")

        try:
            data = self.llm.parse_json(content)
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
            return factors
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Factor parsing failed: {e}")
