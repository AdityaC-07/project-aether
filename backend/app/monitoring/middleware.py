from __future__ import annotations

import time
import uuid
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.monitoring.telemetry import clear_request_context, get_telemetry


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Stamp request/trace ids and record request-level metrics.

    Flow:
      request enters -> assign request_id/trace_id -> app runs
      -> record latency/status -> emit JSON log line -> return response
    """

    async def dispatch(self, request: Request, call_next: Callable[[Request], Response]) -> Response:
        telemetry = get_telemetry()
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        trace_id = request.headers.get("x-trace-id") or uuid.uuid4().hex
        request.state.request_id = request_id
        request.state.trace_id = trace_id

        telemetry.begin_request(request_id, trace_id, path=str(request.url.path), method=request.method)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            latency_ms = (time.perf_counter() - started) * 1000.0
            telemetry.end_request(
                request_id=request_id,
                trace_id=trace_id,
                path=str(request.url.path),
                method=request.method,
                status_code=500,
                latency_ms=latency_ms,
                error_type="UnhandledException",
                error_message="Unhandled request failure",
            )
            clear_request_context()
            raise

        latency_ms = (time.perf_counter() - started) * 1000.0
        telemetry.end_request(
            request_id=request_id,
            trace_id=trace_id,
            path=str(request.url.path),
            method=request.method,
            status_code=status_code,
            latency_ms=latency_ms,
        )
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Trace-ID"] = trace_id
        clear_request_context()
        return response

