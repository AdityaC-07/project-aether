from __future__ import annotations

from contextlib import nullcontext

from fastapi import HTTPException

from app.agents.base_agent import BaseAgent
from app.schemas.context import ReasoningContext
from app.schemas.debate import DebateTrace
from app.schemas.final_report import FinalReport
from app.rag.models import RetrievalResult
from app.utils.logger import StructuredLogger


class SynthesizerAgent(BaseAgent):
    TOOL_NAMES = ["summarize_metric", "trend_analysis", "statistical_test", "fetch_external_data"]

    async def generate_report(
        self,
        context: ReasoningContext,
        debates: list[DebateTrace],
        retrieval: RetrievalResult | None = None,
        *,
        trace: StructuredLogger | None = None,
    ) -> FinalReport:
        span_context = (
            trace.span(
                "synthesizer.generate_report",
                attributes={
                    "agent": "synthesizer",
                    "debate_count": len(debates),
                    "model": getattr(self.llm, "model", None),
                },
            )
            if trace is not None
            else nullcontext()
        )

        with span_context as span:
            debates_json = "[" + ",".join(d.model_dump_json() for d in debates) + "]"

            rendered = self._render_prompt(
                "synthesis",
                context_json=context.model_dump_json(),
                debates_json=debates_json,
            )

            retrieval_text = self._format_retrieval_context(retrieval)
            rendered = self._append_tooling_section(rendered, self.TOOL_NAMES)
            rendered = rendered.model_copy(
                update={
                    "text": f"{rendered.text}\n\n## Retrieved Context\n{retrieval_text}",
                }
            )

            content, tool_calls = await self._complete_with_tools(
                rendered,
                input_context={
                    "context": context.model_dump_json(),
                    "debates": debates_json,
                    "retrieval": retrieval.model_dump() if retrieval is not None else None,
                },
                allowed_tools=self.TOOL_NAMES,
                agent_name="synthesis",
                trace=trace,
            )

            context_text = f"{context.model_dump_json()}\n{debates_json}\n{retrieval_text}"

            try:
                data = self.llm.parse_json(content)
                reasoning = self._parse_reasoning(data)
                report = FinalReport(**data)

                if span is not None:
                    span.set_attribute("retrieval_match_count", len(getattr(retrieval, "matches", []) or []))
                    span.set_attribute("tool_count", len(tool_calls))
                    span.set_attribute("argument_count", 0)

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
