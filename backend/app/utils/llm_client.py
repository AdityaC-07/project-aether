from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, Dict, Optional

from google import genai


class LLMClient:
    """Gemini client using Vertex AI (OAuth / ADC)."""

    def __init__(self) -> None:
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
        
        # Use Vertex AI with ADC (Application Default Credentials)
        self.client = genai.Client(
            vertexai=True,
            project=os.getenv("GCP_PROJECT"),
            location=os.getenv("GCP_LOCATION", "us-central1"),
        )

    async def acompletion(self, prompt: str, system: Optional[str] = None) -> str:
        system_msg = system or (
            "You are a meticulous analysis assistant. Respond with JSON only."
        )

        full_prompt = f"{system_msg}\n\n{prompt}"

        response = await asyncio.to_thread(
            self.client.models.generate_content,
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
