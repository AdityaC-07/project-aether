from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional

from openai import OpenAI


class LLMClient:
    """Thin wrapper around an OpenAI-compatible Chat Completions API."""

    def __init__(self) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL")
        self.model = os.getenv("AETHER_MODEL", "gpt-4o-mini")
        # OpenAI client supports custom base_url for compatible providers
        if base_url:
            self.client = OpenAI(api_key=api_key, base_url=base_url)
        else:
            self.client = OpenAI(api_key=api_key)

    async def acompletion(self, prompt: str, system: Optional[str] = None) -> str:
        system_msg = system or (
            "You are a meticulous analysis assistant. Respond with JSON only."
        )
        # The official client is sync; FastAPI can run this in threadpool implicitly when awaited via async dependency.
        # To keep code simple and dependency-light, we call sync client here.
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        return resp.choices[0].message.content or ""

    def parse_json(self, text: str) -> Dict[str, Any]:
        """Extract and parse JSON from model output robustly."""
        # If output contains code fences or extra text, extract first {...} block
        # Try direct parse first
        text = text.strip()
        try:
            return json.loads(text)
        except Exception:
            pass

        # Fallback: extract JSON object via regex
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            return json.loads(match.group(0))
        raise ValueError("No valid JSON object found in LLM output")
