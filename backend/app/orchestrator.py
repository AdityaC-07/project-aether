from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from app.agents.factor_extractor import FactorExtractorAgent
from app.agents.support_agent import SupportAgent
from app.agents.opposition_agent import OppositionAgent
from app.agents.synthesizer_agent import SynthesizerAgent
from app.evaluation.confidence import ConfidenceScorer
from app.schemas.context import ReasoningContext
from app.schemas.factor import Factor, FactorExtraction
from app.schemas.debate import DebateTrace, SupportArguments, OppositionCounterArguments
from app.schemas.final_report import FinalReport
from app.rag.metrics import RetrievalLogger
from app.rag.models import PdfDocument, RetrievalResult
from app.rag.retriever import RetrievalPipeline
from app.utils.logger import ReasoningLogger
from app.utils.llm_client import LLMClient


class AetherOrchestrator:
    """Central controller that enforces program flow and logging."""

    def __init__(self) -> None:
        self.llm = LLMClient()
        self.factor_extractor = FactorExtractorAgent(self.llm)
        self.support_agent = SupportAgent(self.llm)
        self.opposition_agent = OppositionAgent(self.llm)
        self.synthesizer_agent = SynthesizerAgent(self.llm)
        self.confidence_scorer = ConfidenceScorer()
        self.logs_dir = Path(__file__).resolve().parents[1] / "logs"
        self.log_file = self.logs_dir / "reasoning_logs.json"
        self.retrieval_log_file = self.logs_dir / "retrieval_logs.jsonl"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.status: Dict[str, Any] = {
            "phase": "idle",
            "message": "Idle",
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
        self.last_result: Dict[str, Any] | None = None
        self.last_narrative: str | None = None
        self.last_retrieval_metrics: List[Dict[str, Any]] = []

    def _set_status(self, phase: str, message: str, **details: Any) -> None:
        self.status = {
            "phase": phase,
            "message": message,
            "updated_at": datetime.utcnow().isoformat() + "Z",
            **details,
        }

    async def analyze(self, context: ReasoningContext, *, source_document: Dict[str, Any] | None = None) -> Dict[str, Any]:
        try:
            retrieval_pipeline = RetrievalPipeline(logger=RetrievalLogger(self.retrieval_log_file))
            document_payload = source_document or {"text": context.narrative}
            pdf_document = PdfDocument.model_validate(document_payload)
            await retrieval_pipeline.ingest_document(pdf_document)

            # 1) Factor extraction (with chain-of-thought)
            self._set_status("extracting", "Extracting factors")
            print("\n[ORCHESTRATOR] Starting factor extraction...")
            extraction: FactorExtraction = await self.factor_extractor.extract_factors(context)
            factors: List[Factor] = extraction.factors
            print(f"[ORCHESTRATOR] Extracted {len(factors)} factors")
            await asyncio.sleep(2)  # Rate limit prevention

            # 2) For each factor → support then opposition
            debate_logs: List[DebateTrace] = []
            retrieval_logs: List[Dict[str, Any]] = []
            total_factors = len(factors)
            for i, factor in enumerate(factors, 1):
                print(f"\n[ORCHESTRATOR] Processing factor {i}/{total_factors}: {factor.factor_id}")

                self._set_status(
                    "support",
                    f"Generating support for {factor.factor_id}",
                    factor_index=i,
                    factor_total=total_factors,
                    factor_id=factor.factor_id,
                )
                print(f"  → Generating support arguments...")
                support_query = (
                    f"{factor.description}\n"
                    f"Domain: {factor.domain.value}\n"
                    "Focus: supporting evidence and quantified details from the document."
                )
                support_retrieval: RetrievalResult = await retrieval_pipeline.retrieve(
                    support_query,
                    top_k=4,
                )
                support: SupportArguments = await self.support_agent.generate_support(
                    factor,
                    context,
                    retrieval=support_retrieval,
                )
                print(f"  → Support generated: {len(support.support_arguments)} arguments")
                await asyncio.sleep(2)  # Rate limit prevention

                self._set_status(
                    "opposition",
                    f"Generating opposition for {factor.factor_id}",
                    factor_index=i,
                    factor_total=total_factors,
                    factor_id=factor.factor_id,
                )
                print(f"  → Generating opposition arguments...")
                opposition_query = (
                    f"{factor.description}\n"
                    f"Domain: {factor.domain.value}\n"
                    f"Support claims: {'; '.join(arg.claim for arg in support.support_arguments)}"
                )
                opposition_retrieval: RetrievalResult = await retrieval_pipeline.retrieve(
                    opposition_query,
                    top_k=4,
                )
                opposition: OppositionCounterArguments = await self.opposition_agent.generate_counters(
                    factor,
                    support,
                    retrieval=opposition_retrieval,
                )
                print(f"  → Opposition generated: {len(opposition.counter_arguments)} arguments")
                await asyncio.sleep(2)  # Rate limit prevention

                debate = DebateTrace(
                    factor_id=factor.factor_id,
                    factor=factor,
                    support=support,
                    opposition=opposition,
                    tool_usage=[*support.tool_usage, *opposition.tool_usage],
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

            # 3) Synthesis
            self._set_status("synthesizing", "Synthesizing final report")
            print("\n[ORCHESTRATOR] Starting synthesis...")
            synthesis_query = "\n".join(f"{factor.factor_id}: {factor.description}" for factor in factors)
            synthesis_retrieval: RetrievalResult = await retrieval_pipeline.retrieve(
                synthesis_query,
                top_k=min(8, max(4, len(factors) * 2)),
            )
            final_report: FinalReport = await self.synthesizer_agent.generate_report(
                context,
                debate_logs,
                retrieval=synthesis_retrieval,
            )
            print("[ORCHESTRATOR] Synthesis complete")

            # Nuanced confidence surface: per-factor certainty, agreement,
            # uncertainty breakdown, and synthesizer confidence.
            final_report.confidence_report = self.confidence_scorer.build_report(
                debate_logs,
                synthesis_validation=(
                    self.synthesizer_agent.last_run.validation
                    if self.synthesizer_agent.last_run is not None
                    else None
                ),
            )
            final_report.confidence_score = final_report.confidence_report.overall_confidence

            # 4) Persist logs (structured, readable)
            session_log: Dict[str, Any] = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "input_context": context.dict(),
                "factor_extraction": extraction.dict(),
                "factors": [f.dict() for f in factors],
                "debate_logs": [d.dict() for d in debate_logs],
                "final_report": final_report.dict(),
                "retrieval_logs": retrieval_logs,
                "synthesis_retrieval": synthesis_retrieval.model_dump(),
            }
            ReasoningLogger.save_session(session_log, self.log_file)

            self._set_status(
                "done",
                "Analysis complete",
                factor_total=total_factors,
            )

            response_payload = {
                "final_report": final_report.dict(),
                "factors": [f.dict() for f in factors],
                "debate_logs": [d.dict() for d in debate_logs],
                "retrieval_logs": {
                    "per_factor": retrieval_logs,
                    "synthesis": synthesis_retrieval.model_dump(),
                },
                # Full reasoning traces explaining WHY each output was produced
                "reasoning_traces": {
                    "factor_extraction": [s.dict() for s in extraction.reasoning],
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

            # 5) API response
            return response_payload
        except Exception as exc:
            self._set_status("error", f"Error: {exc}")
            raise
