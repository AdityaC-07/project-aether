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
