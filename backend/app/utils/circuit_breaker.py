from __future__ import annotations

import time
from collections import deque
from enum import Enum
from threading import RLock
from typing import Any, Deque, Dict, Optional


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Per-endpoint failure tracker that stops hammering an unhealthy API.

    States:
        CLOSED    requests flow; failures in a sliding window push to OPEN.
        OPEN      requests are denied for ``cooldown_seconds``, then HALF_OPEN.
        HALF_OPEN a limited number of probe requests is allowed; success
                  re-closes the circuit, failure re-opens it.
    """

    def __init__(
        self,
        name: str = "llm",
        failure_threshold: int = 5,
        cooldown_seconds: float = 30.0,
        half_open_max_probes: int = 1,
        window_seconds: float = 60.0,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.half_open_max_probes = half_open_max_probes
        self.window_seconds = window_seconds
        self._state = CircuitState.CLOSED
        self._failures: Deque[float] = deque()
        self._opened_at: Optional[float] = None
        self._half_open_probes = 0
        self._total_successes = 0
        self._total_failures = 0
        self._lock = RLock()

    @property
    def state(self) -> CircuitState:
        """Current state; lazily transitions OPEN -> HALF_OPEN after cooldown."""
        with self._lock:
            if (
                self._state == CircuitState.OPEN
                and self._opened_at is not None
                and (time.monotonic() - self._opened_at) >= self.cooldown_seconds
            ):
                self._state = CircuitState.HALF_OPEN
                self._half_open_probes = 0
            return self._state

    def _prune(self) -> None:
        cutoff = time.monotonic() - self.window_seconds
        while self._failures and self._failures[0] < cutoff:
            self._failures.popleft()

    def allow_request(self) -> bool:
        """True if a request may proceed right now."""
        state = self.state
        if state == CircuitState.OPEN:
            return False
        if state == CircuitState.HALF_OPEN:
            with self._lock:
                if self._half_open_probes < self.half_open_max_probes:
                    self._half_open_probes += 1
                    return True
                return False
        return True

    def record_success(self) -> None:
        with self._lock:
            self._total_successes += 1
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.CLOSED
                self._failures.clear()
                self._opened_at = None
                self._half_open_probes = 0

    def record_failure(self) -> None:
        now = time.monotonic()
        with self._lock:
            self._total_failures += 1
            self._failures.append(now)
            self._prune()
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                self._opened_at = now
                self._half_open_probes = 0
            elif self._state == CircuitState.CLOSED and len(self._failures) >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._opened_at = now

    def reset(self) -> None:
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failures.clear()
            self._opened_at = None
            self._half_open_probes = 0

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            state = self.state
            return {
                "name": self.name,
                "state": state.value,
                "failures_in_window": len(self._failures),
                "failure_threshold": self.failure_threshold,
                "cooldown_seconds": self.cooldown_seconds,
                "half_open_max_probes": self.half_open_max_probes,
                "total_successes": self._total_successes,
                "total_failures": self._total_failures,
                "opened_at": self._opened_at,
            }
