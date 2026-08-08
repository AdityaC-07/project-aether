from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from google import genai
from google.genai import types

from app.schemas.tooling import ToolInvocationRecord
from app.tools.registry import ToolRegistry


@dataclass(slots=True)
class ToolCompletionResult:
    text: str
    tool_calls: List[ToolInvocationRecord]


class LLMClient:
    """Gemini client using Vertex AI (OAuth / ADC)."""

    def __init__(
        self,
        model: Optional[str] = None,
        project: Optional[str] = None,
        location: Optional[str] = None,
    ) -> None:
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
        
        # Use Vertex AI with ADC (Application Default Credentials)
        self.client = genai.Client(
            vertexai=True,
            project=project or os.getenv("GCP_PROJECT"),
            location=location or os.getenv("GCP_LOCATION", "us-central1"),
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

    async def acompletion_with_tools(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        registry: ToolRegistry,
        allowed_tools: Optional[Sequence[str]] = None,
        json_mode: bool = True,
        max_rounds: int = 4,
        agent_name: str = "agent",
        config: Optional[Dict[str, Any]] = None,
    ) -> ToolCompletionResult:
        system_msg = system or (
            "You are a meticulous analysis assistant. Respond with JSON only."
        )

        full_prompt = f"{system_msg}\n\n{prompt}"
        tool_declarations = registry.build_gemini_tools(allowed_tools)
        function_names = [tool.name for tool in registry.list_tools(allowed_tools)]

        gen_config: Dict[str, Any] = {"temperature": 0.2}
        if json_mode:
            gen_config["response_mime_type"] = "application/json"
        if tool_declarations:
            gen_config["tools"] = tool_declarations
            gen_config["tool_config"] = types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode=types.FunctionCallingConfigMode.AUTO,
                    allowed_function_names=function_names,
                )
            )
        if config:
            gen_config.update(config)

        contents: List[Any] = [full_prompt]
        tool_calls: List[ToolInvocationRecord] = []

        for _ in range(max_rounds):
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model,
                contents=contents,
                config=gen_config,
            )

            function_calls = list(getattr(response, "function_calls", None) or [])
            if not function_calls:
                return ToolCompletionResult(text=response.text or "", tool_calls=tool_calls)

            if not getattr(response, "candidates", None):
                raise RuntimeError("Gemini returned function calls without a candidate payload")

            contents.append(response.candidates[0].content)

            response_parts = []
            for call in function_calls:
                record = await registry.execute(
                    call.name,
                    dict(call.args or {}),
                    agent=agent_name,
                )
                tool_calls.append(record)
                response_parts.append(
                    types.Part.from_function_response(
                        name=call.name,
                        response={
                            "output": record.result if record.success else None,
                            "error": record.error,
                            "tool_name": record.tool_name,
                            "display_name": record.display_name,
                        },
                        id=getattr(call, "id", None),
                    )
                )

            contents.append(types.Content(role="tool", parts=response_parts))

        raise RuntimeError("Tool-calling loop exceeded the maximum number of rounds")

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
