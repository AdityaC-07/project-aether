from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from app.agents.factor_extractor import FactorExtractorAgent
from app.agents.support_agent import SupportAgent
from app.agents.opposition_agent import OppositionAgent
from app.agents.synthesizer_agent import SynthesizerAgent
from app.schemas.context import ReasoningContext
from app.schemas.factor import Factor
from app.schemas.debate import DebateTrace, SupportArguments, OppositionCounterArguments
from app.schemas.final_report import FinalReport
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
        self.logs_dir = Path(__file__).resolve().parents[1] / "logs"
        self.log_file = self.logs_dir / "reasoning_logs.json"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.status: Dict[str, Any] = {
            "phase": "idle",
            "message": "Idle",
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
        self.last_result: Dict[str, Any] | None = None
        self.last_narrative: str | None = None

    def _set_status(self, phase: str, message: str, **details: Any) -> None:
        self.status = {
            "phase": phase,
            "message": message,
            "updated_at": datetime.utcnow().isoformat() + "Z",
            **details,
        }

    def _calculate_confidence(self, debate_logs: List[DebateTrace], final_report: FinalReport) -> float:
        """Calculate confidence score based on debate analysis quality and balance."""
        if not debate_logs:
            return 0.0
        
        total_score = 0.0
        factors_count = len(debate_logs)
        
        for debate in debate_logs:
            support_count = len(debate.support.support_arguments)
            opposition_count = len(debate.opposition.counter_arguments)
            
            # Score based on argument richness (0-50 points)
            argument_richness = min((support_count + opposition_count) / 6 * 50, 50)
            
            # Score based on debate balance (0-30 points)
            if support_count > 0 and opposition_count > 0:
                balance_ratio = min(support_count, opposition_count) / max(support_count, opposition_count)
                balance_score = balance_ratio * 30
            else:
                balance_score = 0
            
            # Score based on argument depth (0-20 points)
            depth_score = 20 if support_count > 0 and opposition_count > 0 else 10
            
            total_score += argument_richness + balance_score + depth_score
        
        # Average and normalize to 0-100
        avg_score = (total_score / factors_count) if factors_count > 0 else 0
        return round(min(avg_score, 100), 1)

    async def analyze(self, context: ReasoningContext) -> Dict[str, Any]:
        try:
            # 1) Factor extraction
            self._set_status("extracting", "Extracting factors")
            print("\n[ORCHESTRATOR] Starting factor extraction...")
            factors: List[Factor] = await self.factor_extractor.extract_factors(context)
            print(f"[ORCHESTRATOR] Extracted {len(factors)} factors")
            await asyncio.sleep(2)  # Rate limit prevention

            # 2) For each factor → support then opposition
            debate_logs: List[DebateTrace] = []
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
                support: SupportArguments = await self.support_agent.generate_support(factor, context)
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
                opposition: OppositionCounterArguments = await self.opposition_agent.generate_counters(
                    factor, support
                )
                print(f"  → Opposition generated: {len(opposition.counter_arguments)} arguments")
                await asyncio.sleep(2)  # Rate limit prevention

                debate = DebateTrace(
                    factor_id=factor.factor_id,
                    factor=factor,
                    support=support,
                    opposition=opposition,
                )
                debate_logs.append(debate)

            # 3) Synthesis
            self._set_status("synthesizing", "Synthesizing final report")
            print("\n[ORCHESTRATOR] Starting synthesis...")
            final_report: FinalReport = await self.synthesizer_agent.generate_report(context, debate_logs)
            print("[ORCHESTRATOR] Synthesis complete")

            # Calculate confidence score based on debate balance
            confidence_score = self._calculate_confidence(debate_logs, final_report)
            final_report.confidence_score = confidence_score

            # 4) Persist logs (structured, readable)
            session_log: Dict[str, Any] = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "input_context": context.dict(),
                "factors": [f.dict() for f in factors],
                "debate_logs": [d.dict() for d in debate_logs],
                "final_report": final_report.dict(),
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
            }
            self.last_result = response_payload
            self.last_narrative = context.narrative

            # 5) API response
            return response_payload
        except Exception as exc:
            self._set_status("error", f"Error: {exc}")
            raise
