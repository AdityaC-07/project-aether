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

        prompt = (
            f"{prompt_template}\n\n"
            f"Factor:\n{factor.model_dump_json()}\n\n"
            f"Support Output:\n{support.model_dump_json()}"
        )

        content = await self.llm.acompletion(prompt)

        try:
            data = self.llm.parse_json(content)
            return OppositionCounterArguments(**data)
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "Counter-arguments parsing failed",
                    "reason": str(e),
                    "llm_output": content,
                },
            )
