from __future__ import annotations

from fastapi import HTTPException

from app.agents.base_agent import BaseAgent
from app.schemas.debate import OppositionCounterArguments, SupportArguments
from app.schemas.factor import Factor
from app.rag.models import RetrievalResult


class OppositionAgent(BaseAgent):
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
        rendered = rendered.model_copy(
            update={
                "text": f"{rendered.text}\n\n## Retrieved Context\n{retrieval_text}",
            }
        )

        content = await self._complete(
            rendered,
            input_context={
                "factor": factor.model_dump_json(),
                "support": support.model_dump_json(),
                "retrieval": retrieval.model_dump() if retrieval is not None else None,
            },
        )

        context_text = f"{factor.model_dump_json()}\n{support.model_dump_json()}\n{retrieval_text}"

        try:
            data = self.llm.parse_json(content)
            reasoning = self._parse_reasoning(data)
            opposition = OppositionCounterArguments(**data)

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
