from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel

from app.evaluation.reasoning_validator import ReasoningValidator
from app.evaluation.tracker import PromptRun, PromptTracker
from app.prompts import PromptRegistry, RenderedPrompt
from app.schemas.factor import DomainEnum
from app.schemas.reasoning import ReasoningStep
from app.schemas.tooling import ToolInvocationRecord
from app.rag.models import RetrievalContext, RetrievalResult
from app.utils.logger import StructuredLogger
from app.utils.llm_client import LLMClient
from app.utils.structured_parser import StructuredOutputParser, StructuredParseResult, default_audit
from app.tools.registry import ToolRegistry


class BaseAgent:
    """Base class: versioned prompt resolution + run tracking.

    Subclasses call ``self._render_prompt(name, domain=..., **variables)`` to
    resolve the deployed (or A/B-pinned) template version, then ``self._complete``
    to call the LLM and ``self._finalize_run`` once the output is parsed so the
    reasoning trace is validated and every step is persisted with the run.
    """

    def __init__(
        self,
        llm: LLMClient,
        registry: Optional[PromptRegistry] = None,
        tracker: Optional[PromptTracker] = None,
    ) -> None:
        self.llm = llm
        self.registry = registry or PromptRegistry()
        self.tracker = tracker or PromptTracker()
        self.prompts_dir = Path(__file__).resolve().parents[1] / "prompts"
        self.last_run: Optional[PromptRun] = None
        self.tool_registry = ToolRegistry()
        self._structured_parser: Optional[StructuredOutputParser] = None

    def _parser(self) -> StructuredOutputParser:
        """Shared structured-output parser bound to this agent's LLM client.

        Lazily created so agents that never parse (or tests that inject a stub
        LLM) pay no setup cost. Auditing goes to the module-wide
        ``default_audit`` so failure rates are comparable across agents.
        """
        if self._structured_parser is None:
            self._structured_parser = StructuredOutputParser(
                llm=self.llm,
                audit=default_audit,
            )
        return self._structured_parser

    async def _parse_structured(
        self,
        content: str,
        *,
        schema: Type[BaseModel],
        agent_name: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> StructuredParseResult:
        """Parse ``content`` against ``schema`` with retry + graceful fallback.

        Wraps :class:`StructuredOutputParser` so agents get: JSON extraction,
        validation against a Pydantic schema, up to 2 strict-JSON re-prompts,
        and a scaffolded fallback model when the model output is unusable.
        """
        return await self._parser().parse(
            content,
            schema=schema,
            agent=agent_name or "agent",
            config=config,
        )

    def _read_prompt(self, filename: str) -> str:
        """Legacy raw-prompt loader, kept for compatibility with old flows."""
        path = self.prompts_dir / filename
        return path.read_text(encoding="utf-8")

    def _render_prompt(
        self,
        name: str,
        domain: Optional[DomainEnum | str] = None,
        **variables: Any,
    ) -> RenderedPrompt:
        """Resolve the active (or A/B-pinned) template and render it."""
        template = self.registry.get(name)
        return template.render(domain=domain, **variables)

    async def _complete(
        self,
        rendered: RenderedPrompt,
        *,
        input_context: Optional[Dict[str, Any]] = None,
        json_mode: bool = True,
        trace: Optional[StructuredLogger] = None,
        agent_name: Optional[str] = None,
    ) -> str:
        """Call the LLM and stage a PromptRun. Returns the raw output text.

        The run is stored on ``self.last_run`` and only persisted once
        ``_finalize_run`` is called after parsing/validation.
        """
        if trace is not None:
            with trace.span(
                "llm.complete",
                attributes={
                    "prompt_name": rendered.name,
                    "prompt_version": rendered.version,
                    "json_mode": json_mode,
                    "model": getattr(self.llm, "model", None),
                },
            ) as span:
                content = await self.llm.acompletion(
                    rendered.text,
                    json_mode=json_mode,
                    agent_name=agent_name or rendered.name,
                )
                span.set_attribute("response_chars", len(content))
        else:
            content = await self.llm.acompletion(
                rendered.text,
                json_mode=json_mode,
                agent_name=agent_name or rendered.name,
            )

        self.last_run = PromptRun(
            prompt_name=rendered.name,
            prompt_version=rendered.version,
            domain=rendered.domain,
            input_context=input_context or {},
            rendered_prompt=rendered.text,
            raw_output=content,
        )
        return content

    def _append_tooling_section(self, rendered: RenderedPrompt, tool_names: Optional[List[str]] = None) -> RenderedPrompt:
        tool_text = self.tool_registry.describe(tool_names)
        if not tool_text:
            return rendered
        suffix = (
            "\n\n## Tool Calling\n"
            "If you need arithmetic, trends, statistical testing, or external data, call the relevant tool.\n"
            "When an argument depends on tool output, cite the tool name in tool_citations.\n\n"
            f"## Available Tools\n{tool_text}"
        )
        return rendered.model_copy(update={"text": f"{rendered.text}{suffix}"})

    async def _complete_with_tools(
        self,
        rendered: RenderedPrompt,
        *,
        input_context: Optional[Dict[str, Any]] = None,
        json_mode: bool = True,
        allowed_tools: Optional[List[str]] = None,
        agent_name: str = "agent",
        trace: Optional[StructuredLogger] = None,
    ) -> tuple[str, List[ToolInvocationRecord]]:
        if trace is not None:
            with trace.span(
                "llm.complete_with_tools",
                attributes={
                    "prompt_name": rendered.name,
                    "prompt_version": rendered.version,
                    "json_mode": json_mode,
                    "model": getattr(self.llm, "model", None),
                    "agent": agent_name,
                    "allowed_tools": allowed_tools or [],
                },
            ) as span:
                result = await self.llm.acompletion_with_tools(
                    rendered.text,
                    registry=self.tool_registry,
                    allowed_tools=allowed_tools,
                    json_mode=json_mode,
                    agent_name=agent_name,
                )
                span.set_attribute("tool_call_count", len(result.tool_calls))
                span.set_attribute("response_chars", len(result.text))
        else:
            result = await self.llm.acompletion_with_tools(
                rendered.text,
                registry=self.tool_registry,
                allowed_tools=allowed_tools,
                json_mode=json_mode,
                agent_name=agent_name,
            )

        self.last_run = PromptRun(
            prompt_name=rendered.name,
            prompt_version=rendered.version,
            domain=rendered.domain,
            input_context={
                **(input_context or {}),
                "allowed_tools": allowed_tools or [],
                "tool_calls": [call.model_dump() for call in result.tool_calls],
            },
            rendered_prompt=rendered.text,
            raw_output=result.text,
        )
        return result.text, result.tool_calls

    def _format_retrieval_context(
        self,
        retrieval: RetrievalContext | RetrievalResult | None,
        *,
        max_chars_per_chunk: int = 1200,
    ) -> str:
        if retrieval is None:
            return "No retrieved context was provided."

        matches = getattr(retrieval, "matches", None) or []
        if not matches:
            return "No retrieved context was available."

        sections: List[str] = []
        for index, match in enumerate(matches, 1):
            chunk = match.chunk
            text = chunk.text[:max_chars_per_chunk]
            header = (
                f"[Chunk {index}] similarity={match.similarity:.4f} "
                f"type={chunk.chunk_type} "
                f"pages={chunk.page_start or '?'}-{chunk.page_end or '?'} "
                f"id={chunk.chunk_id}"
            )
            if chunk.section_title:
                header += f" title={chunk.section_title}"
            sections.append(f"{header}\n{text}")

        return "\n\n".join(sections)

    def _finalize_run(
        self,
        *,
        context_text: Optional[str] = None,
        expected_schema: Optional[Type[BaseModel]] = None,
        steps: Optional[List[ReasoningStep]] = None,
        arguments: Optional[List[Dict[str, Any]]] = None,
    ) -> PromptRun:
        """Validate reasoning, score metrics, and persist the run.

        Args:
            context_text: Source text used to score relevance and step grounding.
            expected_schema: Pydantic model the output must match (format metric).
            steps: Parsed chain-of-thought steps, if the output carried any.
            arguments: Parsed structured arguments (with ``rationale``) used to
                check that each argument traces to a reasoning step.
        """
        run = self.last_run
        if run is None:
            raise RuntimeError("_complete must be called before _finalize_run")

        if steps is not None:
            run.validation = ReasoningValidator().validate_steps(
                steps, context_text or "", arguments=arguments
            )

        if context_text is not None or expected_schema is not None:
            run.evaluate(context_text=context_text, expected_schema=expected_schema)

        if self.tracker is not None:
            self.tracker.log(run)
        return run

    @staticmethod
    def _parse_reasoning(data: Dict[str, Any]) -> List[ReasoningStep]:
        """Extract reasoning steps from parsed LLM output, skipping malformed entries.

        Structural defects (gaps in step indices, missing fields) are surfaced
        by ReasoningValidator rather than raised here, so a single bad step
        never discards the rest of a run.
        """
        steps: List[ReasoningStep] = []
        for entry in data.get("reasoning") or []:
            if not isinstance(entry, dict):
                continue
            try:
                steps.append(ReasoningStep.model_validate(entry))
            except Exception:
                continue
        return steps
