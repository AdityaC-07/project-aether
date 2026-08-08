from __future__ import annotations

from fastapi import HTTPException

from app.agents.base_agent import BaseAgent
from app.schemas.context import ReasoningContext
from app.schemas.debate import SupportArguments
from app.schemas.factor import Factor
from app.rag.models import RetrievalResult


class SupportAgent(BaseAgent):
    async def generate_support(
        self,
        factor: Factor,
        context: ReasoningContext,
        retrieval: RetrievalResult | None = None,
    ) -> SupportArguments:
        # Few-shot examples adapt to the factor's domain (sales, policy, ...)
        rendered = self._render_prompt(
            "support",
            domain=factor.domain,
            context_json=context.model_dump_json(),
            factor_json=factor.model_dump_json(),
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
                "factor": factor.model_dump_json(),
                "retrieval": retrieval.model_dump() if retrieval is not None else None,
            },
        )

        context_text = f"{context.model_dump_json()}\n{retrieval_text}"

        try:
            data = self.llm.parse_json(content)
            reasoning = self._parse_reasoning(data)
            support = SupportArguments(**data)

            self._finalize_run(
                context_text=context_text,
                expected_schema=SupportArguments,
                steps=reasoning,
                arguments=[a.model_dump() for a in support.support_arguments],
            )
            return support
        except Exception as e:
            self._finalize_run(context_text=context_text)
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "Support arguments parsing failed",
                    "reason": str(e),
                    "llm_output": content,
                },
            )
