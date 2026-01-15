from __future__ import annotations

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
        # 1) Factor extraction
        factors: List[Factor] = await self.factor_extractor.extract_factors(context)

        # 2) For each factor → support then opposition
        debate_logs: List[DebateTrace] = []
        for factor in factors:
            support: SupportArguments = await self.support_agent.generate_support(factor, context)
            opposition: OppositionCounterArguments = await self.opposition_agent.generate_counters(
                factor, support
            )

            debate = DebateTrace(
                factor_id=factor.factor_id,
                factor=factor,
                support=support,
                opposition=opposition,
            )
            debate_logs.append(debate)

        # 3) Synthesis
        final_report: FinalReport = await self.synthesizer_agent.generate_report(context, debate_logs)

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

        # 5) API response
        return {
            "final_report": final_report.dict(),
            "factors": [f.dict() for f in factors],
            "debate_logs": [d.dict() for d in debate_logs],
        }
