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

    async def acompletion(
        self,
        prompt: str,
        system: Optional[str] = None,
        *,
        json_mode: bool = False,
        config: Optional[Dict[str, Any]] = None,
    ) -> str:
        system_msg = system or (
            "You are a meticulous analysis assistant. Respond with JSON only."
        )

        full_prompt = f"{system_msg}\n\n{prompt}"

        gen_config: Dict[str, Any] = {"temperature": 0.2}
        if json_mode:
            # Vertex AI Gemini: hard-enforce a JSON-only response so the
            # reasoning + output contract always parses.
            gen_config["response_mime_type"] = "application/json"
        if config:
            gen_config.update(config)

        response = await asyncio.to_thread(
            self.client.models.generate_content,
            model=self.model,
            contents=full_prompt,
            config=gen_config,
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
