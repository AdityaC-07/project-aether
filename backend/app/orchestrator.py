from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from app.agents.factor_advisor import FactorAdvisorAgent
from app.agents.factor_extractor import FactorExtractorAgent
from app.agents.opposition_agent import OppositionAgent
from app.agents.support_agent import SupportAgent
from app.agents.synthesizer_agent import SynthesizerAgent
from app.core.settings import get_settings
from app.evaluation.confidence import ConfidenceScorer
from app.evaluation.explainability import ContributionScorer, CounterfactualAnalyzer
from app.evaluation.tracker import PromptTracker
from app.history.store import HistoryStore
from app.prompts import PromptRegistry
from app.rag.metrics import RetrievalLogger
from app.rag.models import PdfDocument, RetrievalResult
from app.rag.retriever import RetrievalPipeline
from app.schemas.context import ReasoningContext
from app.schemas.debate import DebateTrace, OppositionCounterArguments, SupportArguments
from app.schemas.factor import Factor, FactorExtraction
from app.schemas.factor_advisor import FactorAdviseResponse
from app.schemas.final_report import FinalReport
from app.schemas.reasoning import ReasoningStep
from app.schemas.resilience import FallbackDecision, FallbackStrategy
from app.utils.llm_client import LLMClient
from app.utils.groq_errors import GroqErrorHandler
from app.utils.logger import ReasoningLogger, StructuredLogger
from app.utils.resilient_llm import LLMUnavailableError, ResilientLLMClient


class AetherOrchestrator:
    """Central controller that enforces program flow and logging."""

    def __init__(
        self,
        *,
        llm: LLMClient | None = None,
        prompt_registry: PromptRegistry | None = None,
        prompt_tracker: PromptTracker | None = None,
        allow_degraded: bool | None = None,
    ) -> None:
        self.llm = llm or ResilientLLMClient()
        self.allow_degraded = (
            allow_degraded
            if allow_degraded is not None
            else os.getenv("AETHER_DEGRADED_MODE", "1").lower() in ("1", "true", "yes", "on")
        )
        self.resilience_log: List[FallbackDecision] = getattr(self.llm, "log", [])
        self._resilience_start = 0
        self._degraded_steps: List[Dict[str, Any]] = []
        self.synthesis_degraded = False
        self.prompt_registry = prompt_registry or PromptRegistry()
        self.prompt_tracker = prompt_tracker or PromptTracker()
        self.factor_extractor = FactorExtractorAgent(
            self.llm,
            registry=self.prompt_registry,
            tracker=self.prompt_tracker,
        )
        self.factor_advisor = FactorAdvisorAgent(
            self.llm,
            registry=self.prompt_registry,
            tracker=self.prompt_tracker,
        )
        self.support_agent = SupportAgent(
            self.llm,
            registry=self.prompt_registry,
            tracker=self.prompt_tracker,
        )
        self.opposition_agent = OppositionAgent(
            self.llm,
            registry=self.prompt_registry,
            tracker=self.prompt_tracker,
        )
        self.synthesizer_agent = SynthesizerAgent(
            self.llm,
            registry=self.prompt_registry,
            tracker=self.prompt_tracker,
        )
        self.confidence_scorer = ConfidenceScorer()
        self.contribution_scorer = ContributionScorer()
        self.counterfactual_analyzer = CounterfactualAnalyzer()
        self.max_counterfactual_reruns: int | None = None
        self.logs_dir = Path(__file__).resolve().parents[1] / "logs"
        self.log_file = self.logs_dir / "reasoning_logs.json"
        self.retrieval_log_file = self.logs_dir / "retrieval_logs.jsonl"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        _settings = get_settings()
        self.history_store = HistoryStore(
            db_path=_settings.history_db_path or None,
            enabled=_settings.history_enabled,
        )
        self.status: Dict[str, Any] = {
            "phase": "idle",
            "message": "Idle",
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
        self.last_result: Dict[str, Any] | None = None
        self.last_narrative: str | None = None
        self.last_retrieval_metrics: List[Dict[str, Any]] = []
        self.last_trace: Dict[str, Any] | None = None
        self.error_handler = GroqErrorHandler()

    def refresh_prompt_registry(self) -> None:
        """Reload prompt templates + active versions from disk and rewire all
        agents so a deploy takes effect without restarting the service."""
        self.prompt_registry = PromptRegistry()
        for agent in (
            self.factor_extractor,
            self.factor_advisor,
            self.support_agent,
            self.opposition_agent,
            self.synthesizer_agent,
        ):
            agent.registry = self.prompt_registry
        return self.prompt_registry

    def _set_status(self, phase: str, message: str, **details: Any) -> None:
        self.status = {
            "phase": phase,
            "message": message,
            "updated_at": datetime.utcnow().isoformat() + "Z",
            **details,
        }

    def _record_skip(
        self,
        agent: str,
        factor_id: Optional[str],
        detail: str,
        *,
        error_code: Optional[str] = None,
        user_message: Optional[str] = None,
    ) -> None:
        """Record an agent-level skip and flip the degraded flag."""
        self.synthesis_degraded = self.synthesis_degraded or agent == "synthesis"
        self.resilience_log.append(
            FallbackDecision(
                call_id=uuid.uuid4().hex[:12],
                agent=agent,
                strategy=FallbackStrategy.SKIP_AGENT,
                reason="Agent skipped in degraded mode",
                error_message=detail,
                error_code=error_code,
                recovery_action="skip_agent",
                user_message=user_message or "The request could not be completed for this step.",
            )
        )
        self._degraded_steps.append({"agent": agent, "factor_id": factor_id, "reason": detail})

    async def _safe_agent_call(
        self,
        agent: str,
        factor_id: Optional[str],
        coro,
        fallback_factory,
        *,
        reason_prefix: str = "Agent failed",
    ):
        """Run an agent step; in degraded mode skip it instead of failing."""
        try:
            result = await coro
            return result, False
        except Exception as exc:
            info = self.error_handler.classify(exc)
            detail = f"{reason_prefix}: {info.error_code}"
            self._record_skip(
                agent,
                factor_id,
                detail,
                error_code=info.error_code,
                user_message=info.user_message,
            )
            if not self.allow_degraded:
                raise HTTPException(status_code=503, detail=info.user_message)
            print(f"  [DEGRADED] Skipping {agent} ({info.error_code})")
            return fallback_factory(), True

    def _degraded_synthesis(self, debates: List[DebateTrace]) -> FinalReport:
        """Build a report without the LLM when synthesis is unavailable."""
        total_support = sum(len(d.support.support_arguments) for d in debates)
        total_opposition = sum(len(d.opposition.counter_arguments) for d in debates)
        factor_lines = "\n".join(
            f"- {d.factor_id} ({d.factor.domain.value}): "
            f"{len(d.support.support_arguments)} supporting, "
            f"{len(d.opposition.counter_arguments)} counter-argument(s)"
            for d in debates
        )
        if total_support == 0 and total_opposition == 0:
            recommendation = (
                "Insufficient evidence: the debate agents were unavailable during an "
                "LLM outage, so no arguments could be generated."
            )
        elif total_support >= total_opposition:
            recommendation = (
                "Supportive evidence outweighs counter-arguments across the analyzed factors."
            )
        else:
            recommendation = (
                "Counter-arguments outweigh supportive evidence across the analyzed factors."
            )
        return FinalReport(
            what_worked="Factor extraction and any available debate arguments were retained.",
            what_failed="The synthesis LLM call failed after all fallback strategies were exhausted.",
            why_it_happened="LLM API outage or rate limiting prevented synthesis; degraded mode compiled the report locally.",
            how_to_improve="Retry the analysis once the LLM API is available to get a full synthesis.",
            synthesis=(
                "Degraded synthesis: the LLM API was unavailable, so this report was "
                "compiled directly from the extracted factors and debate arguments.\n\n"
                f"{factor_lines}"
            ),
            recommendation=recommendation,
            reasoning=[
                ReasoningStep(
                    step_index=1,
                    thought="The synthesis LLM was unavailable, so a full analysis could not be generated.",
                    evidence="All LLM model tiers failed after retries and fallbacks.",
                    conclusion="A degraded report was assembled from the available debate arguments.",
                )
            ],
        )

    async def advise(
        self,
        context: ReasoningContext,
        custom_factors: Optional[List[Factor]] = None,
    ) -> FactorAdviseResponse:
        """Two-phase workflow step: extract + validate factors and suggest related ones.

        Extraction degrades to no factors when the LLM is unavailable; custom
        factors the user provided are always validated (with a deterministic
        heuristic fallback when the LLM is down).
        """
        extracted: List[Factor] = []
        custom = list(custom_factors or [])
        if context.narrative.strip():
            try:
                extraction = await self.factor_extractor.extract_factors(context)
                extracted = extraction.factors
            except Exception:
                extracted = []
        candidates = [*custom, *extracted]
        validations = await self.factor_advisor.validate_factors(context, candidates)
        suggestions = await self.factor_advisor.suggest_factors(context, candidates)
        return FactorAdviseResponse(
            narrative=context.narrative,
            context=context,
            extracted_factors=extracted,
            custom_factors=custom,
            validations=validations,
            suggestions=suggestions,
        )

    @staticmethod
    def _normalize_factors(factors: List[Factor]) -> List[Factor]:
        """Dedupe by description and renumber to F1..Fn in selection order."""
        seen: set[str] = set()
        normalized: List[Factor] = []
        for factor in factors:
            description = (factor.description or "").strip()
            key = description.lower()
            if not description or key in seen:
                continue
            seen.add(key)
            normalized.append(
                Factor(
                    factor_id=f"F{len(normalized) + 1}",
                    description=description,
                    domain=factor.domain,
                )
            )
        return normalized

    def _history_payload(
        self,
        *,
        request_id: str,
        input_type: str,
        context: ReasoningContext,
        factors: List[Factor],
        final_report: FinalReport,
        debate_logs: List[DebateTrace],
        status: str,
    ) -> Dict[str, Any]:
        factor_scores = []
        for debate in debate_logs:
            confidence_data = debate.confidence_data
            factor_scores.append(
                {
                    "factor_id": debate.factor_id,
                    "factor_description": debate.factor.description,
                    "domain": debate.factor.domain.value,
                    "confidence": confidence_data.confidence if confidence_data else 0.0,
                    "agreement": confidence_data.support_opposition_agreement
                    if confidence_data
                    else 0.0,
                    "contribution": final_report.factor_contribution_scores.get(
                        debate.factor_id, 0.0
                    ),
                }
            )
        return {
            "analysis_id": request_id,
            "request_id": request_id,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "input_type": input_type,
            "narrative": context.narrative,
            "factors": [factor.dict() for factor in factors],
            "final_report": final_report.dict(),
            "confidence_score": final_report.confidence_score,
            "degraded": bool(self._degraded_steps),
            "factor_scores": factor_scores,
            "status": status,
        }

    def _persist_history(self, payload: Dict[str, Any]) -> None:
        try:
            self.history_store.save_analysis(payload)
        except Exception as exc:
            print(f"[HISTORY] Failed to persist analysis: {exc}")

    async def analyze(
        self,
        context: ReasoningContext,
        *,
        source_document: Dict[str, Any] | None = None,
        factors: Optional[List[Factor]] = None,
        input_type: str = "text",
    ) -> Dict[str, Any]:
        request_id = uuid.uuid4().hex
        trace_logger = StructuredLogger(request_id=request_id, service_name="project-aether")
        retrieval_pipeline = RetrievalPipeline(logger=RetrievalLogger(self.retrieval_log_file))
        extraction: FactorExtraction | None = None
        debate_logs: List[DebateTrace] = []
        retrieval_logs: List[Dict[str, Any]] = []
        synthesis_retrieval: RetrievalResult | None = None
        final_report: FinalReport | None = None
        counterfactuals: List[Any] = []
        total_factors = 0
        self._resilience_start = len(self.resilience_log)
        self._degraded_steps = []
        self.synthesis_degraded = False

        session_log: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "request_id": request_id,
            "input_context": context.dict(),
            "source_document": source_document,
        }

        try:
            with trace_logger.span(
                "orchestrator.analyze",
                attributes={
                    "agent": "orchestrator",
                    "request_id": request_id,
                    "narrative_length": len(context.narrative),
                    "has_source_document": source_document is not None,
                },
            ) as root_span:
                document_payload = source_document or {"text": context.narrative}
                pdf_document = PdfDocument.model_validate(document_payload)
                with trace_logger.span(
                    "retrieval.ingest_document",
                    attributes={
                        "agent": "retrieval",
                        "document_type": pdf_document.__class__.__name__,
                    },
                ) as span:
                    await retrieval_pipeline.ingest_document(pdf_document)
                    span.set_attribute("document_text_length", len(getattr(pdf_document, "text", "") or ""))

                if factors is not None and len(factors) > 0:
                    factors = self._normalize_factors(factors)
                    extraction = None
                    total_factors = len(factors)
                    root_span.set_attribute("factor_count", total_factors)
                    self._set_status(
                        "support",
                        f"Preparing {total_factors} selected factors",
                        factor_total=total_factors,
                        request_id=request_id,
                    )
                    print(f"[ORCHESTRATOR] Using {total_factors} user-selected factors")
                else:
                    self._set_status("extracting", "Extracting factors", request_id=request_id)
                    print("\n[ORCHESTRATOR] Starting factor extraction...")
                    try:
                        extraction = await self.factor_extractor.extract_factors(context, trace=trace_logger)
                    except LLMUnavailableError as exc:
                        info = self.error_handler.classify(exc)
                        self._record_skip("factor_extraction", None, f"Factor extraction skipped: {info.error_code}", error_code=info.error_code, user_message=info.user_message)
                        self._set_status(
                            "extracting",
                            "Factor extraction skipped; continuing in degraded mode",
                            request_id=request_id,
                        )
                        extraction = FactorExtraction(reasoning=[], factors=[])
                    factors = extraction.factors
                    total_factors = len(factors)
                    root_span.set_attribute("factor_count", total_factors)
                    print(f"[ORCHESTRATOR] Extracted {len(factors)} factors")
                    await asyncio.sleep(2)

                for i, factor in enumerate(factors, 1):
                    print(f"\n[ORCHESTRATOR] Processing factor {i}/{total_factors}: {factor.factor_id}")

                    self._set_status(
                        "support",
                        f"Generating support for {factor.factor_id}",
                        factor_index=i,
                        factor_total=total_factors,
                        factor_id=factor.factor_id,
                        request_id=request_id,
                    )
                    print("  -> Generating support arguments...")
                    support_query = (
                        f"{factor.description}\n"
                        f"Domain: {factor.domain.value}\n"
                        "Focus: supporting evidence and quantified details from the document."
                    )
                    with trace_logger.span(
                        "retrieval.support",
                        attributes={
                            "agent": "retrieval",
                            "factor_id": factor.factor_id,
                            "top_k": 4,
                            "query_type": "support",
                        },
                    ) as span:
                        support_retrieval: RetrievalResult = await retrieval_pipeline.retrieve(
                            support_query,
                            top_k=4,
                        )
                        support_matches = getattr(support_retrieval, "matches", []) or []
                        span.set_attribute("match_count", len(support_matches))
                        if support_matches:
                            span.set_attribute("best_similarity", support_matches[0].similarity)
                    support, support_degraded = await self._safe_agent_call(
                        "support",
                        factor.factor_id,
                        self.support_agent.generate_support(
                            factor,
                            context,
                            retrieval=support_retrieval,
                            trace=trace_logger,
                        ),
                        fallback_factory=lambda: SupportArguments(
                            support_arguments=[], reasoning=[]
                        ),
                        reason_prefix="Support generation failed",
                    )
                    print(f"  -> Support generated: {len(support.support_arguments)} arguments")
                    await asyncio.sleep(2)

                    self._set_status(
                        "opposition",
                        f"Generating opposition for {factor.factor_id}",
                        factor_index=i,
                        factor_total=total_factors,
                        factor_id=factor.factor_id,
                        request_id=request_id,
                    )
                    print("  -> Generating opposition arguments...")
                    opposition_query = (
                        f"{factor.description}\n"
                        f"Domain: {factor.domain.value}\n"
                        f"Support claims: {'; '.join(arg.claim for arg in support.support_arguments)}"
                    )
                    with trace_logger.span(
                        "retrieval.opposition",
                        attributes={
                            "agent": "retrieval",
                            "factor_id": factor.factor_id,
                            "top_k": 4,
                            "query_type": "opposition",
                        },
                    ) as span:
                        opposition_retrieval: RetrievalResult = await retrieval_pipeline.retrieve(
                            opposition_query,
                            top_k=4,
                        )
                        opposition_matches = getattr(opposition_retrieval, "matches", []) or []
                        span.set_attribute("match_count", len(opposition_matches))
                        if opposition_matches:
                            span.set_attribute("best_similarity", opposition_matches[0].similarity)
                    opposition, opposition_degraded = await self._safe_agent_call(
                        "opposition",
                        factor.factor_id,
                        self.opposition_agent.generate_counters(
                            factor,
                            support,
                            retrieval=opposition_retrieval,
                            trace=trace_logger,
                        ),
                        fallback_factory=lambda: OppositionCounterArguments(
                            counter_arguments=[], reasoning=[]
                        ),
                        reason_prefix="Opposition generation failed",
                    )
                    print(f"  -> Opposition generated: {len(opposition.counter_arguments)} arguments")
                    await asyncio.sleep(2)

                    debate = DebateTrace(
                        factor_id=factor.factor_id,
                        factor=factor,
                        support=support,
                        opposition=opposition,
                        tool_usage=[*support.tool_usage, *opposition.tool_usage],
                        degraded=support_degraded or opposition_degraded,
                        degraded_reason=(
                            "; ".join(
                                step["reason"]
                                for step in self._degraded_steps
                                if step["factor_id"] == factor.factor_id
                            )
                            if (support_degraded or opposition_degraded)
                            else None
                        ),
                    )
                    debate.confidence_data = self.confidence_scorer.score_debate(
                        debate, context.narrative
                    )
                    debate_logs.append(debate)
                    retrieval_logs.append(
                        {
                            "factor_id": factor.factor_id,
                            "support": support_retrieval.model_dump(),
                            "opposition": opposition_retrieval.model_dump(),
                        }
                    )

                self._set_status("synthesizing", "Synthesizing final report", request_id=request_id)
                print("\n[ORCHESTRATOR] Starting synthesis...")
                synthesis_query = "\n".join(f"{factor.factor_id}: {factor.description}" for factor in factors)
                synthesis_top_k = min(8, max(4, len(factors) * 2))
                with trace_logger.span(
                    "retrieval.synthesis",
                    attributes={
                        "agent": "retrieval",
                        "query_type": "synthesis",
                        "top_k": synthesis_top_k,
                    },
                ) as span:
                    synthesis_retrieval = await retrieval_pipeline.retrieve(
                        synthesis_query,
                        top_k=synthesis_top_k,
                    )
                    synthesis_matches = getattr(synthesis_retrieval, "matches", []) or []
                    span.set_attribute("match_count", len(synthesis_matches))
                    if synthesis_matches:
                        span.set_attribute("best_similarity", synthesis_matches[0].similarity)
                try:
                    final_report = await self.synthesizer_agent.generate_report(
                        context,
                        debate_logs,
                        retrieval=synthesis_retrieval,
                        trace=trace_logger,
                    )
                    print("[ORCHESTRATOR] Synthesis complete")
                except Exception as exc:
                    if not self.allow_degraded:
                        raise
                    print(f"  [DEGRADED] Synthesis unavailable ({type(exc).__name__}); compiling local report")
                    self._record_skip("synthesis", None, f"Synthesis unavailable: {type(exc).__name__}: {exc}")
                    self.synthesis_degraded = True
                    final_report = self._degraded_synthesis(debate_logs)

                final_report.confidence_report = self.confidence_scorer.build_report(
                    debate_logs,
                    synthesis_validation=(
                        self.synthesizer_agent.last_run.validation
                        if self.synthesizer_agent.last_run is not None
                        else None
                    ),
                )
                final_report.confidence_score = final_report.confidence_report.overall_confidence

                self._set_status(
                    "explaining",
                    "Measuring factor contributions via counterfactual synthesis",
                    request_id=request_id,
                )
                print("\n[ORCHESTRATOR] Running counterfactual synthesis...")
                if self.synthesis_degraded:
                    self._record_skip(
                        "explainability",
                        None,
                        "Counterfactual analysis skipped because synthesis ran in degraded mode",
                    )
                else:
                    with trace_logger.span(
                        "explain.counterfactuals",
                        attributes={
                            "agent": "explainability",
                            "factor_count": len(debate_logs),
                        },
                    ) as span:
                        try:
                            counterfactuals = await self.counterfactual_analyzer.analyze(
                                debates=debate_logs,
                                context=context,
                                full_report=final_report,
                                synth_fn=lambda subset: self.synthesizer_agent.generate_report(
                                    context,
                                    subset,
                                    retrieval=synthesis_retrieval,
                                    trace=trace_logger,
                                ),
                                max_reruns=self.max_counterfactual_reruns,
                            )
                            span.set_attribute("counterfactual_count", len(counterfactuals))
                        except Exception as exc:
                            if not self.allow_degraded:
                                raise
                            self._record_skip(
                                "explainability",
                                None,
                                f"Counterfactual analysis skipped: {type(exc).__name__}: {exc}",
                            )
                            counterfactuals = []

                    if counterfactuals:
                        importance = self.contribution_scorer.score(
                            debate_logs, final_report, counterfactuals
                        )
                        final_report.factor_contribution_scores = {
                            entry.factor_id: entry.contribution for entry in importance.rankings
                        }
                        final_report.top_factors = [entry.factor_id for entry in importance.rankings]
                        final_report.feature_importance = importance
                        final_report.counterfactuals = counterfactuals
                        print(f"[ORCHESTRATOR] Counterfactuals: {len(counterfactuals)} factors analyzed")

            trace_summary = trace_logger.request_trace.summary()
            trace_dict = trace_logger.request_trace.to_dict()
            otel_trace = trace_logger.request_trace.to_otel()
            session_log.update(
                {
                    "factor_extraction": extraction.dict() if extraction is not None else None,
                    "factors": [f.dict() for f in factors],
                    "debate_logs": [d.dict() for d in debate_logs],
                    "final_report": final_report.dict(),
                    "retrieval_logs": retrieval_logs,
                    "synthesis_retrieval": synthesis_retrieval.model_dump()
                    if synthesis_retrieval is not None
                    else None,
                    "counterfactuals": [
                        cf.model_dump() if hasattr(cf, "model_dump") else cf for cf in counterfactuals
                    ],
                    "request_trace": trace_dict,
                    "trace_summary": trace_summary,
                    "otel_trace": otel_trace,
                    "resilience": {
                        "degraded": bool(self._degraded_steps),
                        "decisions": [
                            d.dict() for d in self.resilience_log[self._resilience_start:]
                        ],
                        "degraded_steps": self._degraded_steps,
                    },
                }
            )
            ReasoningLogger.save_session(session_log, self.log_file)

            self._set_status(
                "done",
                "Analysis complete",
                factor_total=total_factors,
                request_id=request_id,
            )

            response_payload = {
                "request_id": request_id,
                "final_report": final_report.dict(),
                "factors": [f.dict() for f in factors],
                "debate_logs": [d.dict() for d in debate_logs],
                "retrieval_logs": {
                    "per_factor": retrieval_logs,
                    "synthesis": synthesis_retrieval.model_dump()
                    if synthesis_retrieval is not None
                    else None,
                },
                "trace_summary": trace_summary,
                "request_trace": trace_dict,
                "otel_trace": otel_trace,
                "resilience": {
                    "degraded": bool(self._degraded_steps),
                    "decisions": [
                        d.dict() for d in self.resilience_log[self._resilience_start:]
                    ],
                    "degraded_steps": self._degraded_steps,
                },
                "reasoning_traces": {
                    "factor_extraction": [s.dict() for s in extraction.reasoning]
                    if extraction is not None
                    else [],
                    "debates": {
                        d.factor_id: {
                            "support": [s.dict() for s in d.support.reasoning],
                            "opposition": [s.dict() for s in d.opposition.reasoning],
                        }
                        for d in debate_logs
                    },
                    "synthesis": [s.dict() for s in final_report.reasoning],
                },
            }
            self.last_result = response_payload
            self.last_narrative = context.narrative
            self.last_retrieval_metrics = retrieval_logs
            self.last_trace = trace_dict
            self._persist_history(
                self._history_payload(
                    request_id=request_id,
                    input_type=input_type,
                    context=context,
                    factors=factors,
                    final_report=final_report,
                    debate_logs=debate_logs,
                    status="completed",
                )
            )
            return response_payload
        except Exception as exc:
            self._set_status("error", f"Error: {exc}", request_id=request_id)
            session_log.update(
                {
                    "status": "error",
                    "error": {
                        "type": exc.__class__.__name__,
                        "message": str(exc),
                    },
                    "factor_extraction": extraction.dict() if extraction is not None else None,
                    "factors": [f.dict() for f in factors],
                    "debate_logs": [d.dict() for d in debate_logs],
                    "final_report": final_report.dict() if final_report is not None else None,
                    "retrieval_logs": retrieval_logs,
                    "synthesis_retrieval": synthesis_retrieval.model_dump()
                    if synthesis_retrieval is not None
                    else None,
                    "counterfactuals": [
                        cf.model_dump() if hasattr(cf, "model_dump") else cf for cf in counterfactuals
                    ],
                    "request_trace": trace_logger.request_trace.to_dict(),
                    "trace_summary": trace_logger.request_trace.summary(),
                    "otel_trace": trace_logger.request_trace.to_otel(),
                    "resilience": {
                        "degraded": bool(self._degraded_steps),
                        "decisions": [
                            d.dict() for d in self.resilience_log[self._resilience_start:]
                        ],
                        "degraded_steps": self._degraded_steps,
                    },
                }
            )
            ReasoningLogger.save_session(session_log, self.log_file)
            self.last_trace = trace_logger.request_trace.to_dict()
            if final_report is not None:
                self._persist_history(
                    self._history_payload(
                        request_id=request_id,
                        input_type=input_type,
                        context=context,
                        factors=factors,
                        final_report=final_report,
                        debate_logs=debate_logs,
                        status="error",
                    )
                )
            raise
