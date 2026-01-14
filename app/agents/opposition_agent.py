from __future__ import annotations

from fastapi import HTTPException

from app.agents.base_agent import BaseAgent
from app.schemas.factor import Factor
from app.schemas.debate import SupportArguments, OppositionCounterArguments


class OppositionAgent(BaseAgent):
    async def generate_counters(
        self, factor: Factor, support: SupportArguments
    ) -> OppositionCounterArguments:
        prompt_template = self._read_prompt("opposition_prompt.txt")
        prompt = prompt_template.format(
            factor_json=factor.json(),
            support_json=support.json(),
        )

        content = await self.llm.acompletion(prompt)
        try:
            data = self.llm.parse_json(content)
            return OppositionCounterArguments(**data)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Counter-arguments parsing failed: {e}")
