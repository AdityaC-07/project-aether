from __future__ import annotations

from fastapi import HTTPException

from app.agents.base_agent import BaseAgent
from app.schemas.context import ReasoningContext
from app.schemas.debate import DebateTrace
from app.schemas.final_report import FinalReport
from app.rag.models import RetrievalResult


class SynthesizerAgent(BaseAgent):
    async def generate_report(
        self,
        context: ReasoningContext,
        debates: list[DebateTrace],
        retrieval: RetrievalResult | None = None,
    ) -> FinalReport:
        debates_json = "[" + ",".join(d.model_dump_json() for d in debates) + "]"

        rendered = self._render_prompt(
            "synthesis",
            context_json=context.model_dump_json(),
            debates_json=debates_json,
        )

        retrieval_text = self._format_retrieval_context(retrieval)
        rendered = rendered.model_copy(
            update={
                "text": f"{rendered.text}\n\n## Retrieved Context\n{retrieval_text}",
            }
        )

        content = await self._complete(
            rendered,
            input_context={
                "context": context.model_dump_json(),
                "debates": debates_json,
                "retrieval": retrieval.model_dump() if retrieval is not None else None,
            },
        )

        context_text = f"{context.model_dump_json()}\n{debates_json}\n{retrieval_text}"

        try:
            data = self.llm.parse_json(content)
            reasoning = self._parse_reasoning(data)
            report = FinalReport(**data)

            self._finalize_run(
                context_text=context_text,
                expected_schema=FinalReport,
                steps=reasoning,
            )
            return report
        except Exception as e:
            self._finalize_run(context_text=context_text)
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "Final report parsing failed",
                    "reason": str(e),
                    "llm_output": content,
                },
            )
