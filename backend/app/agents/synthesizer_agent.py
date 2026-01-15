from __future__ import annotations

from fastapi import HTTPException

from app.agents.base_agent import BaseAgent
from app.schemas.context import ReasoningContext
from app.schemas.debate import DebateTrace
from app.schemas.final_report import FinalReport


class SynthesizerAgent(BaseAgent):
    async def generate_report(
        self, context: ReasoningContext, debates: list[DebateTrace]
    ) -> FinalReport:
        prompt_template = self._read_prompt("synthesis_prompt.txt")

        debates_json = "[" + ",".join(d.model_dump_json() for d in debates) + "]"

        prompt = (
            f"{prompt_template}\n\n"
            f"Context:\n{context.model_dump_json()}\n\n"
            f"Debate Traces:\n{debates_json}"
        )

        content = await self.llm.acompletion(prompt)

        try:
            data = self.llm.parse_json(content)
            return FinalReport(**data)
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "Final report parsing failed",
                    "reason": str(e),
                    "llm_output": content,
                },
            )
