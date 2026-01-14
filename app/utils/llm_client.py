from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional

from google import genai


class LLMClient:
    """Thin wrapper around the Gemini API using google-genai."""

    def __init__(self) -> None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set in environment")

        self.model = os.getenv("AETHER_MODEL", "gemini-1.5-flash")

        # google-genai client (new SDK)
        self.client = genai.Client(api_key=api_key)

    async def acompletion(self, prompt: str, system: Optional[str] = None) -> str:
        system_msg = system or (
            "You are a meticulous analysis assistant. Respond with JSON only."
        )

        # Gemini has no system/user roles → merge prompt
        full_prompt = f"{system_msg}\n\n{prompt}"

        response = self.client.models.generate_content(
            model=self.model,
            contents=full_prompt,
            config={
                "temperature": 0.2,
            },
        )

        return response.text or ""

    def parse_json(self, text: str) -> Dict[str, Any]:
        """Extract and parse JSON from model output robustly."""
        text = text.strip()

        try:
            return json.loads(text)
        except Exception:
            pass

        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            return json.loads(match.group(0))

        raise ValueError("No valid JSON object found in LLM output")
