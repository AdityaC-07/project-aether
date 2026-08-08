from __future__ import annotations

import asyncio
import os
import random
import time
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.schemas.resilience import FallbackDecision, FallbackStrategy, ModelTier
from app.utils.cache import ResponseCache
from app.utils.circuit_breaker import CircuitBreaker
from app.utils.llm_client import LLMClient


class LLMUnavailableError(RuntimeError):
    """Every configured model tier failed and no cached response was available."""


class CircuitOpenError(LLMUnavailableError):
    """The circuit breaker denied the call because the endpoint is unhealthy."""

    def __init__(self, model: str) -> None:
        super().__init__(f"Circuit breaker open for model {model!r}")
        self.model = model


def _error_status(exc: BaseException) -> Optional[int]:
    """Extract an HTTP-ish status code from a wide variety of exceptions."""
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(exc, "status", None)
    if status is None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def is_retryable_error(exc: BaseException) -> bool:
    """Decide whether a failure is transient (worth a retry).

    - HTTP 429 / 5xx: transient.
    - Other 4xx (400, 401, 422, ...): deterministic, do not retry.
    - Timeout / connection / rate-limit / transport families: transient.
    - Local value errors (bad JSON, type errors): never transient.
    - Unknown errors: assumed transient, bounded by the retry cap.
    """
    status = _error_status(exc)
    if status is not None:
        return status == 429 or status >= 500

    if isinstance(exc, (ValueError, TypeError, KeyError, AttributeError)):
        return False

    name = type(exc).__name__.lower()
    transient_hints = (
        "timeout",
        "connection",
        "reset",
        "unavailable",
        "ratelimit",
        "rate_limit",
        "quota",
        "transport",
        "network",
        "too many requests",
    )
    if any(hint in name for hint in transient_hints):
        return True
    message = str(exc).lower()
    if any(hint in message for hint in transient_hints):
        return True
    return True


def _env_fallback_models() -> List[str]:
    raw = os.getenv("GEMINI_FALLBACK_MODEL", "") or os.getenv("GEMINI_MODEL_TIERS", "")
    names = [name.strip() for name in raw.split(",") if name.strip()]
    return names or ["gemini-2.5-flash"]


class ResilientLLMClient:
    """Drop-in replacement for ``LLMClient`` with resilience built in.

    Adds, transparently to the agents:
        * retry with exponential backoff (and jitter) for transient errors
        * fallback to cheaper/faster model tiers when the primary fails
        * a circuit breaker per model to avoid hammering unhealthy endpoints
        * a TTL response cache so repeated queries skip the API entirely

    Every fallback decision is recorded on ``self.log`` as a
    ``FallbackDecision`` so operators can audit behavior under load/outage.
    """

    def __init__(
        self,
        *,
        primary: Optional[LLMClient] = None,
        fallback_models: Optional[Sequence[str]] = None,
        fallback_clients: Optional[Sequence[LLMClient]] = None,
        cache: Optional[ResponseCache] = None,
        max_retries: int = 2,
        base_backoff_seconds: float = 1.0,
        max_backoff_seconds: float = 8.0,
        use_cache: bool = True,
        breaker_failure_threshold: int = 5,
        breaker_cooldown_seconds: float = 30.0,
        log: Optional[List[FallbackDecision]] = None,
    ) -> None:
        self.primary: LLMClient = primary or LLMClient()
        self.fallback: List[LLMClient] = []

        if fallback_clients is not None:
            self.fallback.extend(fallback_clients)
        else:
            for name in list(fallback_models or _env_fallback_models()):
                if name == getattr(self.primary, "model", None):
                    continue
                self.fallback.append(LLMClient(model=name))

        self.cache = cache or ResponseCache()
        self.max_retries = max_retries
        self.base_backoff_seconds = base_backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self.use_cache = use_cache
        self.breaker_failure_threshold = breaker_failure_threshold
        self.breaker_cooldown_seconds = breaker_cooldown_seconds
        self.breakers: Dict[str, CircuitBreaker] = {}
        self.log: List[FallbackDecision] = log if log is not None else []

    @property
    def model(self) -> str:
        """Name of the primary model (agents report this in traces)."""
        return getattr(self.primary, "model", "unknown")

    # ------------------------------------------------------------------ API

    async def acompletion(
        self,
        prompt: str,
        system: Optional[str] = None,
        *,
        json_mode: bool = False,
        config: Optional[Dict[str, Any]] = None,
    ) -> str:
        config = dict(config or {})
        use_cache = bool(config.pop("use_cache", self.use_cache))
        call_id = uuid.uuid4().hex[:12]

        cache_key = self.cache.make_key(
            self.model, prompt, system, {"json_mode": json_mode, **config}
        )
        if use_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                self._record(
                    call_id, "unknown", FallbackStrategy.USE_CACHE,
                    ModelTier.PRIMARY, self.model, 0,
                    reason="Cache hit; served without calling the API", cached=True,
                )
                return cached

        result = await self._execute(
            call_id,
            "unknown",
            self._tiers(),
            lambda client, cfg=config: client.acompletion(
                prompt, system=system, json_mode=json_mode, config=cfg
            ),
        )
        if use_cache:
            self.cache.set(cache_key, result)
        return result

    async def acompletion_with_tools(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        registry,
        allowed_tools: Optional[Sequence[str]] = None,
        json_mode: bool = True,
        max_rounds: int = 4,
        agent_name: str = "agent",
        config: Optional[Dict[str, Any]] = None,
    ):
        call_id = uuid.uuid4().hex[:12]
        return await self._execute(
            call_id,
            agent_name,
            self._tiers(),
            lambda client, cfg=config: client.acompletion_with_tools(
                prompt,
                system=system,
                registry=registry,
                allowed_tools=allowed_tools,
                json_mode=json_mode,
                max_rounds=max_rounds,
                agent_name=agent_name,
                config=cfg,
            ),
        )

    def parse_json(self, text: str) -> Dict[str, Any]:
        return self.primary.parse_json(text)

    def stats(self) -> Dict[str, Any]:
        return {
            "cache": self.cache.stats(),
            "circuit_breakers": {
                name: breaker.stats() for name, breaker in self.breakers.items()
            },
            "fallback_decisions": len(self.log),
            "models": [getattr(client, "model", "?") for client in self._tiers()],
        }

    # -------------------------------------------------------------- internal

    def _tiers(self) -> List[Tuple[ModelTier, LLMClient]]:
        tiers: List[Tuple[ModelTier, LLMClient]] = [(ModelTier.PRIMARY, self.primary)]
        tiers.extend((ModelTier.FALLBACK, client) for client in self.fallback)
        return tiers

    def _breaker_for(self, model_name: str) -> CircuitBreaker:
        breaker = self.breakers.get(model_name)
        if breaker is None:
            breaker = CircuitBreaker(
                name=model_name,
                failure_threshold=self.breaker_failure_threshold,
                cooldown_seconds=self.breaker_cooldown_seconds,
            )
            self.breakers[model_name] = breaker
        return breaker

    def _backoff(self, attempt: int) -> float:
        delay = self.base_backoff_seconds * (2 ** attempt)
        delay = min(delay, self.max_backoff_seconds)
        return delay + random.uniform(0.0, 0.25)

    def _record(
        self,
        call_id: str,
        agent: str,
        strategy: FallbackStrategy,
        tier: ModelTier,
        model: str,
        attempt: int,
        *,
        reason: str = "",
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        retry_after_ms: float = 0.0,
        elapsed_ms: float = 0.0,
        cached: bool = False,
    ) -> FallbackDecision:
        decision = FallbackDecision(
            call_id=call_id,
            agent=agent,
            strategy=strategy,
            tier=tier,
            model=model,
            attempt=attempt,
            reason=reason,
            error_type=error_type,
            error_message=error_message,
            retry_after_ms=retry_after_ms,
            elapsed_ms=elapsed_ms,
            cached=cached,
        )
        self.log.append(decision)
        return decision

    async def _execute(
        self,
        call_id: str,
        agent: str,
        tiers: List[Tuple[ModelTier, LLMClient]],
        invoke,
    ):
        """Try each model tier with retries, backoff, and circuit protection."""
        last_error: Optional[BaseException] = None
        last_non_retryable: Optional[BaseException] = None

        for index, (tier, client) in enumerate(tiers):
            model_name = getattr(client, "model", "unknown")
            breaker = self._breaker_for(model_name)
            is_last_tier = index == len(tiers) - 1

            if not breaker.allow_request():
                self._record(
                    call_id, agent, FallbackStrategy.RETRY, tier, model_name, 0,
                    reason=f"Circuit open for {model_name}; skipping to next tier",
                    error_type="CircuitOpenError",
                )
                last_error = CircuitOpenError(model_name)
                continue

            for attempt in range(self.max_retries + 1):
                started = time.perf_counter()
                try:
                    result = await invoke(client)
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    breaker.record_success()
                    if attempt > 0:
                        strategy = FallbackStrategy.RETRY
                        reason = "ok after retry"
                    elif index > 0:
                        strategy = FallbackStrategy.USE_CHEAPER_MODEL
                        reason = "ok on cheaper model tier"
                    else:
                        strategy = None
                        reason = ""
                    if strategy is not None:
                        self._record(
                            call_id, agent, strategy, tier, model_name, attempt,
                            reason=reason, elapsed_ms=elapsed_ms,
                        )
                    return result
                except Exception as exc:
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    breaker.record_failure()
                    last_error = exc

                    if is_retryable_error(exc) and attempt < self.max_retries:
                        delay = self._backoff(attempt)
                        self._record(
                            call_id, agent, FallbackStrategy.RETRY, tier, model_name, attempt,
                            reason=f"Transient failure ({type(exc).__name__}); retrying in {delay:.2f}s",
                            error_type=type(exc).__name__,
                            error_message=str(exc),
                            retry_after_ms=delay * 1000,
                            elapsed_ms=elapsed_ms,
                        )
                        await asyncio.sleep(delay)
                        continue

                    if not is_last_tier:
                        if is_retryable_error(exc):
                            fallback_reason = f"Exhausted retries for {model_name}; falling back to cheaper model"
                        else:
                            fallback_reason = f"Non-retryable error on {model_name}; trying cheaper model"
                        self._record(
                            call_id, agent, FallbackStrategy.USE_CHEAPER_MODEL, tier, model_name, attempt,
                            reason=fallback_reason,
                            error_type=type(exc).__name__,
                            error_message=str(exc),
                            elapsed_ms=elapsed_ms,
                        )
                        break

                    self._record(
                        call_id, agent, FallbackStrategy.SKIP_AGENT, tier, model_name, attempt,
                        reason="All model tiers exhausted",
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                        elapsed_ms=elapsed_ms,
                    )
                    if not is_retryable_error(exc):
                        last_non_retryable = exc
                    break

        if last_non_retryable is not None:
            raise last_non_retryable
        if isinstance(last_error, CircuitOpenError):
            raise last_error
        raise LLMUnavailableError(f"All LLM model tiers failed for call {call_id}") from last_error
