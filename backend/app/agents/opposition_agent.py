from __future__ import annotations

from fastapi import HTTPException

from app.agents.base_agent import BaseAgent
from app.schemas.debate import OppositionCounterArguments, SupportArguments
from app.schemas.factor import Factor
from app.rag.models import RetrievalResult


class OppositionAgent(BaseAgent):
    TOOL_NAMES = ["summarize_metric", "trend_analysis", "statistical_test", "fetch_external_data"]

    async def generate_counters(
        self,
        factor: Factor,
        support: SupportArguments,
        retrieval: RetrievalResult | None = None,
    ) -> OppositionCounterArguments:
        rendered = self._render_prompt(
            "opposition",
            domain=factor.domain,
            factor_json=factor.model_dump_json(),
            support_json=support.model_dump_json(),
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
                "factor": factor.model_dump_json(),
                "support": support.model_dump_json(),
                "retrieval": retrieval.model_dump() if retrieval is not None else None,
            },
            allowed_tools=self.TOOL_NAMES,
            agent_name="opposition",
        )

        context_text = f"{factor.model_dump_json()}\n{support.model_dump_json()}\n{retrieval_text}"

        try:
            data = self.llm.parse_json(content)
            reasoning = self._parse_reasoning(data)
            opposition = OppositionCounterArguments(**data)
            used_tool_names = sorted({call.display_name for call in tool_calls if call.success})
            if used_tool_names:
                for argument in opposition.counter_arguments:
                    if not argument.tool_citations:
                        argument.tool_citations = used_tool_names
            opposition.tool_usage = tool_calls

            self._finalize_run(
                context_text=context_text,
                expected_schema=OppositionCounterArguments,
                steps=reasoning,
                arguments=[c.model_dump() for c in opposition.counter_arguments],
            )
            return opposition
        except Exception as e:
            self._finalize_run(context_text=context_text)
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "Counter-arguments parsing failed",
                    "reason": str(e),
                    "llm_output": content,
                },
            )
