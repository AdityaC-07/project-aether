from __future__ import annotations

import json
import threading
import time
from collections import Counter, defaultdict, deque
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

from app.core.settings import AppSettings, GroqPricing, get_settings


REQUEST_ID: ContextVar[Optional[str]] = ContextVar("REQUEST_ID", default=None)
TRACE_ID: ContextVar[Optional[str]] = ContextVar("TRACE_ID", default=None)
PATH_NAME: ContextVar[Optional[str]] = ContextVar("PATH_NAME", default=None)
METHOD_NAME: ContextVar[Optional[str]] = ContextVar("METHOD_NAME", default=None)


def set_request_context(request_id: str, trace_id: str, *, path: str | None = None, method: str | None = None) -> None:
    REQUEST_ID.set(request_id)
    TRACE_ID.set(trace_id)
    PATH_NAME.set(path)
    METHOD_NAME.set(method)


def clear_request_context() -> None:
    REQUEST_ID.set(None)
    TRACE_ID.set(None)
    PATH_NAME.set(None)
    METHOD_NAME.set(None)


def current_request_context() -> Dict[str, Optional[str]]:
    return {
        "request_id": REQUEST_ID.get(),
        "trace_id": TRACE_ID.get(),
        "path": PATH_NAME.get(),
        "method": METHOD_NAME.get(),
    }


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump())
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return value


@dataclass(slots=True)
class GroqCallEvent:
    timestamp: str
    request_id: Optional[str]
    trace_id: Optional[str]
    agent: str
    model: str
    tokens_in: int
    tokens_out: int
    latency_ms: float
    cost_usd: float
    cache_hit: bool = False
    status: str = "ok"
    error_code: Optional[str] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    recovery_action: Optional[str] = None
    queue_wait_ms: float = 0.0
    environment: str = "development"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "agent": self.agent,
            "model": self.model,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "latency_ms": self.latency_ms,
            "cost_usd": self.cost_usd,
            "cache_hit": self.cache_hit,
            "status": self.status,
            "error_code": self.error_code,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "recovery_action": self.recovery_action,
            "queue_wait_ms": self.queue_wait_ms,
            "environment": self.environment,
        }


@dataclass(slots=True)
class RequestEvent:
    timestamp: str
    request_id: str
    trace_id: str
    path: str
    method: str
    status_code: int
    latency_ms: float
    error_type: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "path": self.path,
            "method": self.method,
            "status_code": self.status_code,
            "latency_ms": self.latency_ms,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


@dataclass(slots=True)
class MetricSnapshot:
    window_seconds: int
    requests_per_minute: float
    active_requests: int
    error_rate: float
    error_counts: Dict[str, int]
    cache_hit_ratio: float
    cache_hits: int
    cache_misses: int
    cost_today_usd: float
    cost_per_request_today_usd: float
    model_latency_ms: Dict[str, Dict[str, float]]
    agent_latency_ms: Dict[str, Dict[str, float]]
    model_counts: Dict[str, int]
    agent_counts: Dict[str, int]
    alerts: List[str]
    requests_in_window: int
    errors_in_window: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "window_seconds": self.window_seconds,
            "requests_per_minute": self.requests_per_minute,
            "active_requests": self.active_requests,
            "error_rate": self.error_rate,
            "error_counts": self.error_counts,
            "cache_hit_ratio": self.cache_hit_ratio,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cost_today_usd": self.cost_today_usd,
            "cost_per_request_today_usd": self.cost_per_request_today_usd,
            "model_latency_ms": self.model_latency_ms,
            "agent_latency_ms": self.agent_latency_ms,
            "model_counts": self.model_counts,
            "agent_counts": self.agent_counts,
            "alerts": self.alerts,
            "requests_in_window": self.requests_in_window,
            "errors_in_window": self.errors_in_window,
        }


class TelemetryStore:
    """In-memory production telemetry plus structured JSONL export."""

    def __init__(self, settings: Optional[AppSettings] = None) -> None:
        self.settings = settings or get_settings()
        self._lock = threading.RLock()
        self._request_times: Deque[float] = deque()
        self._error_times: Deque[float] = deque()
        self._api_events: Deque[GroqCallEvent] = deque(maxlen=20000)
        self._request_events: Deque[RequestEvent] = deque(maxlen=20000)
        self._cache_hits = 0
        self._cache_misses = 0
        self._active_requests = 0
        self._daily_costs: Dict[str, float] = defaultdict(float)
        self._model_latency_sum: Dict[str, float] = defaultdict(float)
        self._model_latency_count: Dict[str, int] = defaultdict(int)
        self._agent_latency_sum: Dict[str, float] = defaultdict(float)
        self._agent_latency_count: Dict[str, int] = defaultdict(int)
        self._model_counts: Counter[str] = Counter()
        self._agent_counts: Counter[str] = Counter()
        self._error_counts: Counter[str] = Counter()
        self._model_error_counts: Counter[str] = Counter()
        self._write_lock = threading.RLock()
        self.logs_dir = Path(__file__).resolve().parents[2] / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.api_log_file = self.logs_dir / "groq_api_calls.jsonl"
        self.request_log_file = self.logs_dir / "request_logs.jsonl"

    # ---- request context -------------------------------------------------

    def begin_request(self, request_id: str, trace_id: str, *, path: str, method: str) -> None:
        with self._lock:
            self._active_requests += 1
            self._request_times.append(time.monotonic())
            self._prune_locked()
        set_request_context(request_id, trace_id, path=path, method=method)

    def end_request(
        self,
        *,
        request_id: str,
        trace_id: str,
        path: str,
        method: str,
        status_code: int,
        latency_ms: float,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        event = RequestEvent(
            timestamp=_utc_iso(),
            request_id=request_id,
            trace_id=trace_id,
            path=path,
            method=method,
            status_code=status_code,
            latency_ms=latency_ms,
            error_type=error_type,
            error_message=error_message,
        )
        with self._lock:
            self._active_requests = max(0, self._active_requests - 1)
            if status_code >= 400:
                self._error_times.append(time.monotonic())
                if error_type:
                    self._error_counts[error_type] += 1
            self._request_events.append(event)
        self._append_jsonl(self.request_log_file, event.to_dict())

    # ---- cache -----------------------------------------------------------

    def record_cache_hit(self) -> None:
        with self._lock:
            self._cache_hits += 1

    def record_cache_miss(self) -> None:
        with self._lock:
            self._cache_misses += 1

    # ---- Groq calls ------------------------------------------------------

    def estimate_cost(self, model: str, tokens_in: int, tokens_out: int) -> float:
        pricing: GroqPricing = self.settings.pricing_for(model)
        return round(
            (tokens_in / 1_000_000.0) * pricing.input_per_1m
            + (tokens_out / 1_000_000.0) * pricing.output_per_1m,
            8,
        )

    def record_api_call(
        self,
        *,
        agent: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: float,
        cache_hit: bool = False,
        status: str = "ok",
        error_code: Optional[str] = None,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        recovery_action: Optional[str] = None,
        queue_wait_ms: float = 0.0,
    ) -> GroqCallEvent:
        context = current_request_context()
        event = GroqCallEvent(
            timestamp=_utc_iso(),
            request_id=context.get("request_id"),
            trace_id=context.get("trace_id"),
            agent=agent,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=round(latency_ms, 3),
            cost_usd=self.estimate_cost(model, tokens_in, tokens_out),
            cache_hit=cache_hit,
            status=status,
            error_code=error_code,
            error_type=error_type,
            error_message=error_message,
            recovery_action=recovery_action,
            queue_wait_ms=round(queue_wait_ms, 3),
            environment=self.settings.environment,
        )
        with self._lock:
            self._api_events.append(event)
            self._model_counts[model] += 1
            self._agent_counts[agent] += 1
            self._model_latency_sum[model] += event.latency_ms
            self._model_latency_count[model] += 1
            self._agent_latency_sum[agent] += event.latency_ms
            self._agent_latency_count[agent] += 1
            self._daily_costs[datetime.now(timezone.utc).date().isoformat()] += event.cost_usd
            if status != "ok":
                self._error_times.append(time.monotonic())
                if error_code:
                    self._error_counts[error_code] += 1
                if error_type:
                    self._error_counts[error_type] += 1
                self._model_error_counts[model] += 1
        self._append_jsonl(self.api_log_file, event.to_dict())
        return event

    def record_error(
        self,
        *,
        agent: str,
        model: str,
        error_code: str,
        error_type: str,
        error_message: str,
        recovery_action: str,
    ) -> None:
        self.record_api_call(
            agent=agent,
            model=model,
            tokens_in=0,
            tokens_out=0,
            latency_ms=0.0,
            cache_hit=False,
            status="error",
            error_code=error_code,
            error_type=error_type,
            error_message=error_message,
            recovery_action=recovery_action,
        )

    def record_cache_access(self, hit: bool) -> None:
        if hit:
            self.record_cache_hit()
        else:
            self.record_cache_miss()

    # ---- snapshots -------------------------------------------------------

    def _prune_locked(self, window_seconds: int = 60) -> None:
        cutoff = time.monotonic() - window_seconds
        while self._request_times and self._request_times[0] < cutoff:
            self._request_times.popleft()
        while self._error_times and self._error_times[0] < cutoff:
            self._error_times.popleft()

    def snapshot(self, window_seconds: int = 60) -> MetricSnapshot:
        with self._lock:
            self._prune_locked(window_seconds)
            requests = len(self._request_times)
            errors = len(self._error_times)
            cache_total = self._cache_hits + self._cache_misses
            cache_ratio = self._cache_hits / cache_total if cache_total else 0.0
            error_rate = errors / requests if requests else 0.0
            alerts: List[str] = []
            if requests >= int(self.settings.request_rate_limit_rpm * self.settings.request_rate_limit_alert_threshold):
                alerts.append("request_rate_approaching_limit")
            if error_rate >= self.settings.error_rate_alert_threshold:
                alerts.append("error_rate_high")
            if cache_total and cache_ratio <= self.settings.cache_hit_alert_floor:
                alerts.append("cache_hit_ratio_low")
            cost_today = self._daily_costs.get(datetime.now(timezone.utc).date().isoformat(), 0.0)
            avg_request_cost = cost_today / len(self._api_events) if self._api_events else 0.0
            return MetricSnapshot(
                window_seconds=window_seconds,
                requests_per_minute=round(requests / max(window_seconds / 60.0, 1e-9), 3),
                active_requests=self._active_requests,
                error_rate=round(error_rate, 4),
                error_counts=dict(self._error_counts),
                cache_hit_ratio=round(cache_ratio, 4),
                cache_hits=self._cache_hits,
                cache_misses=self._cache_misses,
                cost_today_usd=round(cost_today, 8),
                cost_per_request_today_usd=round(avg_request_cost, 8),
                model_latency_ms=self._latency_summary(self._model_latency_sum, self._model_latency_count),
                agent_latency_ms=self._latency_summary(self._agent_latency_sum, self._agent_latency_count),
                model_counts=dict(self._model_counts),
                agent_counts=dict(self._agent_counts),
                alerts=alerts,
                requests_in_window=requests,
                errors_in_window=errors,
            )

    def health(self) -> Dict[str, Any]:
        snapshot = self.snapshot()
        degraded = bool(snapshot.alerts) or snapshot.error_rate >= self.settings.health_error_rate_threshold
        return {
            "status": "degraded" if degraded else "ok",
            "environment": self.settings.environment,
            "rate_limit_rpm": self.settings.request_rate_limit_rpm,
            "rate_limit_alert_threshold": self.settings.request_rate_limit_alert_threshold,
            "health_error_rate_threshold": self.settings.health_error_rate_threshold,
            "recent_requests_per_minute": snapshot.requests_per_minute,
            "error_rate": snapshot.error_rate,
            "cache_hit_ratio": snapshot.cache_hit_ratio,
            "cost_today_usd": snapshot.cost_today_usd,
            "alerts": snapshot.alerts,
            "circuit_breakers": {},
            "models": self._model_counts.most_common(),
        }

    def _latency_summary(
        self,
        sums: Dict[str, float],
        counts: Dict[str, int],
    ) -> Dict[str, Dict[str, float]]:
        out: Dict[str, Dict[str, float]] = {}
        for key, total in sums.items():
            count = counts.get(key, 0)
            out[key] = {
                "count": count,
                "avg_ms": round(total / count, 3) if count else 0.0,
                "total_ms": round(total, 3),
            }
        return out

    @staticmethod
    def _append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
        if not hasattr(TelemetryStore, "_global_write_lock"):
            TelemetryStore._global_write_lock = threading.RLock()  # type: ignore[attr-defined]
        with TelemetryStore._global_write_lock:  # type: ignore[attr-defined]
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(_json_safe(payload), ensure_ascii=False) + "\n")


_STORE: Optional[TelemetryStore] = None


def get_telemetry() -> TelemetryStore:
    global _STORE
    if _STORE is None:
        _STORE = TelemetryStore()
    return _STORE
