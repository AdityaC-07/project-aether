from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from groq import APIConnectionError, APIStatusError, APITimeoutError


@dataclass(slots=True)
class GroqErrorInfo:
    error_code: str
    error_message: str
    status_code: Optional[int]
    retryable: bool
    retry_after_seconds: float = 0.0
    recovery_action: str = "fail_request"
    user_message: str = "A model request failed. Please try again."


class GroqErrorHandler:
    """Translate Groq exceptions into safe actions and structured logs.

    Error flow:
      API error -> classify -> choose retry / fallback / skip / fail
      -> log sanitized details -> surface generic user message
    """

    RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

    def classify(self, exc: BaseException) -> GroqErrorInfo:
        status_code = self._status_code(exc)
        retry_after = self._retry_after_seconds(exc)
        error_code = self._error_code(exc, status_code)
        message = self._safe_message(exc)

        if isinstance(exc, APITimeoutError):
            return GroqErrorInfo(
                error_code=error_code,
                error_message=message,
                status_code=status_code,
                retryable=True,
                retry_after_seconds=retry_after,
                recovery_action="retry",
                user_message="The model took too long to respond. The request will be retried or skipped.",
            )

        if isinstance(exc, APIConnectionError):
            return GroqErrorInfo(
                error_code=error_code,
                error_message=message,
                status_code=status_code,
                retryable=True,
                retry_after_seconds=retry_after,
                recovery_action="retry",
                user_message="The model connection was interrupted. The request will be retried or skipped.",
            )

        if status_code == 429:
            return GroqErrorInfo(
                error_code=error_code,
                error_message=message,
                status_code=status_code,
                retryable=True,
                retry_after_seconds=retry_after,
                recovery_action="retry",
                user_message="The model is busy right now. Retrying shortly.",
            )

        if status_code in {500, 502, 503, 504}:
            return GroqErrorInfo(
                error_code=error_code,
                error_message=message,
                status_code=status_code,
                retryable=True,
                retry_after_seconds=retry_after,
                recovery_action="retry",
                user_message="The model service is temporarily unavailable. Retrying shortly.",
            )

        if status_code == 400:
            return GroqErrorInfo(
                error_code=error_code,
                error_message=message,
                status_code=status_code,
                retryable=False,
                retry_after_seconds=0.0,
                recovery_action="fail_request",
                user_message="The request could not be processed. The system will skip this step and continue if possible.",
            )

        return GroqErrorInfo(
            error_code=error_code,
            error_message=message,
            status_code=status_code,
            retryable=False,
            retry_after_seconds=retry_after,
            recovery_action="fail_request",
            user_message="A model request failed. The system will continue if it can.",
        )

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
    def _retry_after_seconds(exc: BaseException) -> float:
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None) or {}
        retry_after = headers.get("retry-after") or headers.get("Retry-After")
        try:
            return float(retry_after) if retry_after is not None else 0.0
        except Exception:
            return 0.0

    @staticmethod
    def _error_code(exc: BaseException, status_code: Optional[int]) -> str:
        if status_code is not None:
            return f"groq_http_{status_code}"
        return type(exc).__name__.lower()

    @staticmethod
    def _safe_message(exc: BaseException) -> str:
        return str(exc).strip().replace("\n", " ")[:512]

