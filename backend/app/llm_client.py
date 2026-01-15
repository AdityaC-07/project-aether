from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional

from google import genai


class LLMClient:
    """Gemini client using Vertex AI (OAuth / ADC)."""

    def __init__(self) -> None:
        self.model = os.getenv("AETHER_MODEL", "gemini-1.5-flash")

        self.client = genai.Client(
            vertexai=True,                    # 🔑 THIS IS REQUIRED
            project=os.getenv("GCP_PROJECT"), # optional but recommended
            location=os.getenv("GCP_LOCATION", "us-central1"),
        )

    async def acompletion(self, prompt: str, system: Optional[str] = None) -> str:
        system_msg = system or (
            "You are a meticulous analysis assistant. Respond with JSON only."
        )

        full_prompt = f"{system_msg}\n\n{prompt}"

        response = self.client.models.generate_content(
            model=self.model,
            contents=full_prompt,
            config={"temperature": 0.2},
        )

        return response.text or ""

    def parse_json(self, text: str) -> Dict[str, Any]:
        text = text.strip()

        try:
            return json.loads(text)
        except Exception:
            pass

        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            return json.loads(match.group(0))

        raise ValueError("No valid JSON object found in LLM output")