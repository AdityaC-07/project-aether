from __future__ import annotations

from pathlib import Path
from typing import Any

from app.utils.llm_client import LLMClient


class BaseAgent:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm
        self.prompts_dir = Path(__file__).resolve().parents[1] / "prompts"

    def _read_prompt(self, filename: str) -> str:
        path = self.prompts_dir / filename
        return path.read_text(encoding="utf-8")
