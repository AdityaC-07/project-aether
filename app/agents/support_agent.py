from __future__ import annotations

from fastapi import HTTPException

from app.agents.base_agent import BaseAgent
from app.schemas.context import ReasoningContext
from app.schemas.factor import Factor
from app.schemas.debate import SupportArguments


class SupportAgent(BaseAgent):
    async def generate_support(self, factor: Factor, context: ReasoningContext) -> SupportArguments:
        prompt_template = self._read_prompt("support_prompt.txt")

        prompt = (
            f"{prompt_template}\n\n"
            f"Context:\n{context.model_dump_json()}\n\n"
            f"Factor:\n{factor.model_dump_json()}"
        )

        content = await self.llm.acompletion(prompt)

        try:
            data = self.llm.parse_json(content)
            return SupportArguments(**data)
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "Support arguments parsing failed",
                    "reason": str(e),
                    "llm_output": content,
                },
            )
