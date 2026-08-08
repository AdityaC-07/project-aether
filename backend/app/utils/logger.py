from __future__ import annotations

import json
import traceback
import uuid
from contextvars import ContextVar
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional


class ReasoningLogger:
    @staticmethod
    def save_session(session: Dict[str, Any], file_path: Path) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        if file_path.exists():
            try:
                data = json.loads(file_path.read_text(encoding="utf-8") or "[]")
                if not isinstance(data, list):
                    data = []
            except Exception:
                data = []
        else:
            data = []

        data.append(session)
        file_path.write_text(
            json.dumps(_json_safe(data), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat()


def _duration_ms(start: datetime, end: datetime) -> float:
    return max(0.0, (end - start).total_seconds() * 1000.0)


def _timestamp_ns(dt: datetime) -> int:
    return int(dt.timestamp() * 1_000_000_000)


def _otel_value(value: Any) -> Dict[str, Any]:
    if value is None:
        return {"stringValue": ""}
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int) and not isinstance(value, bool):
        return {"intValue": value}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, datetime):
        return {"stringValue": _to_iso(value) or ""}
    if isinstance(value, (list, tuple, set)):
        return {"arrayValue": {"values": [_otel_value(item) for item in value]}}
    if isinstance(value, dict):
        return {
            "kvlistValue": {
                "values": [{"key": str(key), "value": _otel_value(item)} for key, item in value.items()]
            }
        }
    return {"stringValue": str(value)}


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return _to_iso(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value


_ACTIVE_SPAN_ID: ContextVar[Optional[str]] = ContextVar("_ACTIVE_SPAN_ID", default=None)


@dataclass(slots=True)
class TraceContext:
    request_id: str
    parent_span_id: Optional[str] = None
    start_time: datetime = field(default_factory=_utc_now)


@dataclass(slots=True)
class TraceSpan:
    request_id: str
    span_id: str
    name: str
    start_time: datetime
    parent_span_id: Optional[str] = None
    end_time: Optional[datetime] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    status: str = "OK"
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    stack_trace: Optional[str] = None

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def mark_error(self, exc: BaseException) -> None:
        self.status = "ERROR"
        self.error_type = exc.__class__.__name__
        self.error_message = str(exc)
        self.stack_trace = traceback.format_exc()
        self.set_attribute("error.type", self.error_type)
        self.set_attribute("error.message", self.error_message)
        self.set_attribute("error.stack_trace", self.stack_trace)

    @property
    def duration_ms(self) -> float:
        if self.end_time is None:
            return 0.0
        return _duration_ms(self.start_time, self.end_time)

    def finish(self) -> None:
        if self.end_time is None:
            self.end_time = _utc_now()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "start_time": _to_iso(self.start_time),
            "end_time": _to_iso(self.end_time),
            "duration_ms": self.duration_ms,
            "status": self.status,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "stack_trace": self.stack_trace,
            "attributes": _json_safe(self.attributes),
        }

    def to_otel(self, trace_id: str) -> Dict[str, Any]:
        return {
            "traceId": trace_id,
            "spanId": self.span_id,
            "parentSpanId": self.parent_span_id,
            "name": self.name,
            "kind": "SPAN_KIND_INTERNAL",
            "startTimeUnixNano": _timestamp_ns(self.start_time),
            "endTimeUnixNano": _timestamp_ns(self.end_time or _utc_now()),
            "attributes": [
                {"key": key, "value": _otel_value(value)} for key, value in self.attributes.items()
            ],
            "status": {
                "code": "STATUS_CODE_ERROR" if self.status == "ERROR" else "STATUS_CODE_OK",
                "message": self.error_message or "",
            },
        }


@dataclass(slots=True)
class RequestTrace:
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    service_name: str = "project-aether"
    start_time: datetime = field(default_factory=_utc_now)
    end_time: Optional[datetime] = None
    spans: List[TraceSpan] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)

    def record_span(self, span: TraceSpan) -> None:
        self.spans.append(span)
        self.spans.sort(key=lambda item: item.start_time)

    def finish(self) -> None:
        if self.end_time is None:
            self.end_time = _utc_now()

    @property
    def duration_ms(self) -> float:
        end = self.end_time or _utc_now()
        return _duration_ms(self.start_time, end)

    def summary(self) -> Dict[str, Any]:
        self.finish()
        total_spans = len(self.spans)
        failed_spans = [span for span in self.spans if span.status == "ERROR"]
        failure_modes = Counter(span.error_type or "unknown" for span in failed_spans)
        latency_by_span = {
            span.name: span.duration_ms for span in self.spans
        }
        latency_by_agent: Dict[str, List[float]] = defaultdict(list)
        for span in self.spans:
            agent = span.attributes.get("agent")
            if agent:
                latency_by_agent[str(agent)].append(span.duration_ms)

        agent_latency_summary = {
            agent: {
                "count": len(values),
                "total_ms": round(sum(values), 3),
                "avg_ms": round(sum(values) / len(values), 3) if values else 0.0,
                "max_ms": round(max(values), 3) if values else 0.0,
            }
            for agent, values in latency_by_agent.items()
        }

        return {
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "service_name": self.service_name,
            "span_count": total_spans,
            "error_count": len(failed_spans),
            "error_rate": round(len(failed_spans) / total_spans, 4) if total_spans else 0.0,
            "failure_modes": dict(failure_modes),
            "duration_ms": round(self.duration_ms, 3),
            "latency_by_span_ms": {key: round(value, 3) for key, value in latency_by_span.items()},
            "agent_latency_ms": agent_latency_summary,
            "started_at": _to_iso(self.start_time),
            "finished_at": _to_iso(self.end_time or _utc_now()),
        }

    def to_dict(self) -> Dict[str, Any]:
        self.finish()
        return {
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "service_name": self.service_name,
            "start_time": _to_iso(self.start_time),
            "end_time": _to_iso(self.end_time),
            "duration_ms": self.duration_ms,
            "attributes": _json_safe(self.attributes),
            "spans": [span.to_dict() for span in self.spans],
        }

    def to_otel(self) -> Dict[str, Any]:
        self.finish()
        return {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": self.service_name}},
                            {"key": "service.instance.id", "value": {"stringValue": self.request_id}},
                            {"key": "trace.request_id", "value": {"stringValue": self.request_id}},
                        ]
                    },
                    "scopeSpans": [
                        {
                            "scope": {
                                "name": "project-aether.observability",
                                "version": "1.0.0",
                            },
                            "spans": [span.to_otel(self.trace_id) for span in self.spans],
                        }
                    ],
                }
            ]
        }


class StructuredLogger:
    def __init__(
        self,
        request_trace: Optional[RequestTrace] = None,
        *,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        service_name: str = "project-aether",
    ) -> None:
        if request_trace is not None:
            self.request_trace = request_trace
        else:
            self.request_trace = RequestTrace(
                request_id=request_id or uuid.uuid4().hex,
                trace_id=trace_id or uuid.uuid4().hex,
                service_name=service_name,
            )

    @contextmanager
    def span(
        self,
        name: str,
        *,
        trace_context: Optional[TraceContext] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> Iterator[TraceSpan]:
        parent_span_id = trace_context.parent_span_id if trace_context else _ACTIVE_SPAN_ID.get()
        request_id = trace_context.request_id if trace_context else self.request_trace.request_id
        span = TraceSpan(
            request_id=request_id,
            span_id=uuid.uuid4().hex[:16],
            name=name,
            start_time=trace_context.start_time if trace_context else _utc_now(),
            parent_span_id=parent_span_id,
            attributes=dict(attributes or {}),
        )
        token = _ACTIVE_SPAN_ID.set(span.span_id)

        try:
            yield span
        except BaseException as exc:
            span.mark_error(exc)
            raise
        finally:
            span.finish()
            self.request_trace.record_span(span)
            _ACTIVE_SPAN_ID.reset(token)
