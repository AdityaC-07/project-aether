from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from groq import APIConnectionError, APIStatusError, APITimeoutError, AsyncGroq

from app.core.settings import AppSettings, EnvironmentModelProfile, get_settings
from app.monitoring.telemetry import get_telemetry
from app.schemas.tooling import ToolInvocationRecord
from app.tools.registry import ToolRegistry

try:
    import tiktoken
except Exception:  # pragma: no cover - optional dependency
    tiktoken = None


@dataclass(slots=True)
class ToolCompletionResult:
    text: str
    tool_calls: List[ToolInvocationRecord]


@dataclass(slots=True)
class ModelRegistry:
    """Route agent types to Groq model names."""

    profiles: Dict[str, EnvironmentModelProfile] = field(default_factory=dict)
    environment: str = "development"
    default_model: str = "llama-3.1-70b-versatile"

    def resolve(self, agent_type: Optional[str] = None, *, explicit_model: Optional[str] = None) -> str:
        if explicit_model:
            return explicit_model
        profile = self.profiles.get(self.environment) or self.profiles.get("production")
        if profile is None and self.profiles:
            profile = next(iter(self.profiles.values()))
        if profile is None:
            return self.default_model
        agent = (agent_type or "").lower()
        if "factor" in agent:
            return profile.factor_extractor
        if "support" in agent:
            return profile.support
        if "opp" in agent:
            return profile.opposition
        if "synth" in agent:
            return profile.synthesis
        return self.default_model


class GroqLLMClient:
    """Async Groq client with per-agent model routing and structured output helpers."""

    def __init__(
        self,
        model: Optional[str] = None,
        *,
        model_registry: Optional[ModelRegistry] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: int = 0,
        max_concurrency: int = 8,
        backoff_base_seconds: float = 0.5,
        backoff_max_seconds: float = 8.0,
    ) -> None:
        self.settings = get_settings()
        self.model_registry = model_registry or ModelRegistry(
            profiles=self.settings.model_profiles,
            environment=self.settings.environment,
            default_model=self.settings.profile_for().synthesis,
        )
        self.forced_model = model or os.getenv("GROQ_MODEL") or None
        self.model = self.forced_model or self.model_registry.default_model
        self.api_key = api_key or self.settings.groq_api_key or os.getenv("GROQ_API_KEY")
        self.base_url = base_url or self.settings.groq_base_url or os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
        self.client = AsyncGroq(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=timeout or self.settings.groq_timeout_seconds,
            max_retries=max_retries,
        )
        self._semaphore = asyncio.Semaphore(max_concurrency or self.settings.groq_max_concurrency)
        self._inflight: Dict[str, asyncio.Future[Any]] = {}
        self._cache: Dict[str, Any] = {}
        self._cache_lock = asyncio.Lock()
        self.backoff_base_seconds = backoff_base_seconds
        self.backoff_max_seconds = backoff_max_seconds
        self._tokenizer_name = os.getenv("GROQ_TOKENIZER", "cl100k_base")
        self.telemetry = get_telemetry()

    def resolve_model(self, agent_name: Optional[str] = None, *, explicit_model: Optional[str] = None) -> str:
        if explicit_model:
            return explicit_model
        if self.forced_model:
            return self.forced_model
        return self.model_registry.resolve(agent_name)

    # ------------------------------------------------------------------ tokens

    def count_tokens(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        agent_name: Optional[str] = None,
    ) -> int:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.count_message_tokens(messages, agent_name=agent_name)

    def count_message_tokens(
        self,
        messages: Sequence[Dict[str, Any]],
        *,
        agent_name: Optional[str] = None,
    ) -> int:
        model_name = self.resolve_model(agent_name)
        try:
            if tiktoken is None:
                raise RuntimeError("tiktoken is not installed")
            try:
                encoding = tiktoken.encoding_for_model(model_name)
            except Exception:
                encoding = tiktoken.get_encoding(self._tokenizer_name)
            total = 0
            for message in messages:
                total += 4
                for key, value in message.items():
                    total += len(encoding.encode(str(key)))
                    total += len(encoding.encode(self._json_to_text(value)))
            return total + 2
        except Exception:
            return sum(max(1, len(self._json_to_text(message)) // 4) for message in messages)

    @staticmethod
    def _json_to_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        except Exception:
            return str(value)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _canonical(value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return GroqLLMClient._canonical(value.model_dump())
        if isinstance(value, dict):
            return {str(key): GroqLLMClient._canonical(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [GroqLLMClient._canonical(item) for item in value]
        if isinstance(value, set):
            return sorted(GroqLLMClient._canonical(item) for item in value)
        return value

    def _fingerprint(
        self,
        *,
        model: str,
        messages: Sequence[Dict[str, Any]],
        config: Optional[Dict[str, Any]] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> str:
        payload = {
            "model": model,
            "messages": self._canonical(messages),
            "config": self._canonical(config or {}),
            "extra": self._canonical(extra or {}),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _response_format(self, json_mode: bool, config: Dict[str, Any]) -> Dict[str, Any]:
        if "response_format" in config:
            return config
        if json_mode:
            config["response_format"] = {"type": "json_object"}
        return config

    async def _with_cache(self, key: str, producer):
        async with self._cache_lock:
            cached = self._cache.get(key)
            if cached is not None:
                self.telemetry.record_cache_hit()
                return cached
            self.telemetry.record_cache_miss()
            future = self._inflight.get(key)
            if future is None:
                loop = asyncio.get_running_loop()
                future = loop.create_future()
                self._inflight[key] = future
                should_produce = True
            else:
                should_produce = False

        if not should_produce:
            return await future

        try:
            result = await producer()
        except Exception as exc:
            async with self._cache_lock:
                inflight = self._inflight.pop(key, None)
                if inflight is not None and not inflight.done():
                    inflight.set_exception(exc)
            raise

        async with self._cache_lock:
            self._cache[key] = result
            inflight = self._inflight.pop(key, None)
            if inflight is not None and not inflight.done():
                inflight.set_result(result)
        return result

    def _retry_delay(self, attempt: int, *, retry_after: Optional[float] = None) -> float:
        if retry_after is not None and retry_after > 0:
            return min(retry_after, self.backoff_max_seconds)
        delay = self.backoff_base_seconds * (2**attempt)
        jitter = random.uniform(0.0, 0.25)
        return min(delay + jitter, self.backoff_max_seconds)

    @staticmethod
    def _status_code(exc: BaseException) -> Optional[int]:
        status = getattr(exc, "status_code", None)
        if status is None:
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None)
        try:
            return int(status) if status is not None else None
        except Exception:
            return None

    @staticmethod
    def _retry_after_seconds(exc: BaseException) -> Optional[float]:
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None) or {}
        retry_after = headers.get("retry-after") or headers.get("Retry-After")
        try:
            return float(retry_after) if retry_after is not None else None
        except Exception:
            return None

    @classmethod
    def _is_retryable(cls, exc: BaseException) -> bool:
        if isinstance(exc, (APITimeoutError, APIConnectionError)):
            return True
        status = cls._status_code(exc)
        return status in {429, 500, 502, 503, 504}

    async def _chat_completion(
        self,
        *,
        model: str,
        messages: Sequence[Dict[str, Any]],
        config: Optional[Dict[str, Any]] = None,
        agent_name: Optional[str] = None,
    ) -> Any:
        config = dict(config or {})
        config.pop("agent_name", None)
        config = self._response_format(bool(config.pop("_json_mode", False)), config)
        started = time.perf_counter()
        queue_started = time.perf_counter()
        await self._semaphore.acquire()
        queue_wait_ms = (time.perf_counter() - queue_started) * 1000.0
        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=list(messages),
                **config,
            )
            latency_ms = (time.perf_counter() - started) * 1000.0
            usage = getattr(response, "usage", None)
            tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0)
            tokens_out = int(getattr(usage, "completion_tokens", 0) or 0)
            self.telemetry.record_api_call(
                agent=agent_name or "unknown",
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                latency_ms=latency_ms,
                cache_hit=False,
                status="ok",
                queue_wait_ms=queue_wait_ms,
            )
            return response
        except Exception as exc:
            latency_ms = (time.perf_counter() - started) * 1000.0
            status_code = self._status_code(exc)
            error_code = f"groq_http_{status_code}" if status_code is not None else type(exc).__name__.lower()
            self.telemetry.record_api_call(
                agent=agent_name or "unknown",
                model=model,
                tokens_in=self.count_message_tokens(messages, agent_name=agent_name),
                tokens_out=0,
                latency_ms=latency_ms,
                cache_hit=False,
                status="error",
                error_code=error_code,
                error_type=type(exc).__name__,
                error_message=str(exc),
                recovery_action="retry",
                queue_wait_ms=queue_wait_ms,
            )
            raise
        finally:
            self._semaphore.release()

    # ------------------------------------------------------------------ public

    async def acompletion(
        self,
        prompt: str,
        system: Optional[str] = None,
        *,
        json_mode: bool = False,
        config: Optional[Dict[str, Any]] = None,
        agent_name: Optional[str] = None,
    ) -> str:
        model = self.resolve_model(agent_name)
        messages: List[Dict[str, Any]] = []
        messages.append(
            {
                "role": "system",
                "content": system or "You are a meticulous analysis assistant. Respond with JSON only.",
            }
        )
        messages.append({"role": "user", "content": prompt})

        request_config = dict(config or {})
        request_config["_json_mode"] = json_mode
        request_key = self._fingerprint(
            model=model,
            messages=messages,
            config=request_config,
            extra={"agent_name": agent_name, "mode": "text"},
        )
        async def produce() -> Any:
            return await self._chat_completion(
                model=model,
                messages=messages,
                config=request_config,
                agent_name=agent_name,
            )

        completion = await self._with_cache(request_key, produce)
        return completion.choices[0].message.content or ""

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
        model = self.resolve_model(agent_name)
        messages: List[Dict[str, Any]] = [
            {
                "role": "system",
                "content": system or "You are a meticulous analysis assistant. Respond with JSON only.",
            },
            {"role": "user", "content": prompt},
        ]
        tool_schema = registry.build_openai_tools(allowed_tools)
        tool_calls: List[ToolInvocationRecord] = []
        request_config = dict(config or {})
        request_config["_json_mode"] = json_mode
        if tool_schema:
            request_config["tools"] = tool_schema
            request_config["tool_choice"] = "auto"
        request_config.setdefault("temperature", 0.2)
        request_key = self._fingerprint(
            model=model,
            messages=messages,
            config=request_config,
            extra={"agent_name": agent_name, "mode": "tools"},
        )

        async def produce() -> ToolCompletionResult:
            local_messages = list(messages)
            for _ in range(max_rounds):
                completion = await self._chat_completion(
                    model=model,
                    messages=local_messages,
                    config=request_config,
                    agent_name=agent_name,
                )
                choice = completion.choices[0]
                message = choice.message
                if getattr(message, "tool_calls", None):
                    local_messages.append(message.model_dump(exclude_none=True))
                    response_messages = []
                    for tool_call in message.tool_calls:
                        arguments_text = getattr(tool_call.function, "arguments", "{}") or "{}"
                        try:
                            parsed_arguments = json.loads(arguments_text)
                        except Exception:
                            parsed_arguments = {}
                        record = await registry.execute(
                            tool_call.function.name,
                            parsed_arguments,
                            agent=agent_name,
                        )
                        tool_calls.append(record)
                        response_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": tool_call.function.name,
                                "content": json.dumps(
                                    {
                                        "output": record.result if record.success else None,
                                        "error": record.error,
                                        "tool_name": record.tool_name,
                                        "display_name": record.display_name,
                                    },
                                    ensure_ascii=False,
                                ),
                            }
                        )
                    local_messages.extend(response_messages)
                    continue

                return ToolCompletionResult(text=message.content or "", tool_calls=tool_calls)

            raise RuntimeError("Tool-calling loop exceeded the maximum number of rounds")

        return await self._with_cache(request_key, produce)

    async def abatch_acompletion(
        self,
        prompts: Sequence[str],
        *,
        system: Optional[str] = None,
        json_mode: bool = False,
        agent_name: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        tasks = [
            self.acompletion(
                prompt,
                system=system,
                json_mode=json_mode,
                config=config,
                agent_name=agent_name,
            )
            for prompt in prompts
        ]
        return list(await asyncio.gather(*tasks))

    async def abatch_acompletion_with_tools(
        self,
        prompts: Sequence[str],
        *,
        system: Optional[str] = None,
        registry: ToolRegistry,
        allowed_tools: Optional[Sequence[str]] = None,
        json_mode: bool = True,
        agent_name: str = "agent",
        config: Optional[Dict[str, Any]] = None,
    ) -> List[ToolCompletionResult]:
        tasks = [
            self.acompletion_with_tools(
                prompt,
                system=system,
                registry=registry,
                allowed_tools=allowed_tools,
                json_mode=json_mode,
                agent_name=agent_name,
                config=config,
            )
            for prompt in prompts
        ]
        return list(await asyncio.gather(*tasks))

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


# Backward-compatible alias used across the codebase.
LLMClient = GroqLLMClient
