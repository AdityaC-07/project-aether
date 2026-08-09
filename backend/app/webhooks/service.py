from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from typing import Any, Dict, List, Optional

import httpx

from app.core.settings import get_settings
from app.orchestrator import AetherOrchestrator
from app.schemas.context import ReasoningContext
from app.schemas.factor import Factor
from app.webhooks.store import WebhookStore, new_secret

EVENT_ANALYSIS_COMPLETED = "analysis.completed"
_SUPPORTED_EVENTS = [EVENT_ANALYSIS_COMPLETED]


class WebhookService:
    """Runs analyses in the background and delivers results to registered
    webhook URLs with HMAC-SHA256 signing and exponential-backoff retries."""

    def __init__(
        self,
        *,
        orchestrator: AetherOrchestrator,
        store: Optional[WebhookStore] = None,
    ) -> None:
        settings = get_settings()
        self.orchestrator = orchestrator
        self.store = store or WebhookStore(db_path=settings.webhook_db_path or None)
        self.max_attempts = max(1, settings.webhook_retry_max_attempts)
        self.base_delay = max(0.0, settings.webhook_retry_base_delay_seconds)
        self._background_lock = asyncio.Lock()

    # -- endpoint registration ---------------------------------------------

    def register_endpoint(
        self,
        *,
        url: str,
        description: str = "",
        secret: str = "",
        events: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        events = events or [EVENT_ANALYSIS_COMPLETED]
        unknown = [event for event in events if event not in _SUPPORTED_EVENTS]
        if unknown:
            raise ValueError(f"Unsupported webhook event(s): {', '.join(unknown)}")
        if secret == "auto":
            secret = new_secret()
        return self.store.create_endpoint(
            url=url, secret=secret, description=description, events=events
        )

    def delete_endpoint(self, webhook_id: str) -> bool:
        return self.store.set_endpoint_active(webhook_id, False)

    async def test_ping(self, webhook_id: str) -> Dict[str, Any]:
        endpoint = self.store.get_endpoint(webhook_id)
        if endpoint is None:
            raise KeyError(webhook_id)
        if not endpoint["active"]:
            raise ValueError("Webhook endpoint is inactive")
        payload = {
            "event": "ping",
            "webhook_id": webhook_id,
            "timestamp": self._now_iso(),
        }
        return await self._deliver(endpoint["url"], endpoint["secret"], "ping", payload)

    # -- async analysis ----------------------------------------------------

    async def submit_analysis(
        self,
        *,
        context: ReasoningContext,
        webhook_id: str = "",
        webhook_url: str = "",
        webhook_secret: str = "",
        factors: Optional[List[Factor]] = None,
        input_type: str = "text",
        max_attempts: Optional[int] = None,
    ) -> Dict[str, Any]:
        endpoint_url = ""
        secret = ""
        if webhook_id:
            endpoint = self.store.get_endpoint(webhook_id)
            if endpoint is None:
                raise KeyError(webhook_id)
            if not endpoint["active"]:
                raise ValueError("Webhook endpoint is inactive")
            endpoint_url = endpoint["url"]
            secret = endpoint["secret"]
        endpoint_url = webhook_url or endpoint_url
        secret = webhook_secret or secret
        if not endpoint_url:
            raise ValueError("A webhook_id or webhook_url is required")

        job = self.store.create_job(
            webhook_id=webhook_id,
            endpoint_url=endpoint_url,
            secret=secret,
            request_id="",
            max_attempts=max_attempts or self.max_attempts,
        )
        loop = asyncio.get_running_loop()
        loop.create_task(
            self._run_job(
                job_id=job["job_id"],
                context=context,
                factors=factors,
                input_type=input_type,
            )
        )
        return job

    # -- job introspection -------------------------------------------------

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        job = self.store.get_job(job_id)
        if job is not None:
            job["deliveries"] = self.store.list_deliveries(job_id)
        return job

    def list_jobs(self, *, webhook_id: str = "", status: str = "", limit: int = 50) -> Dict[str, Any]:
        jobs = self.store.list_jobs(webhook_id=webhook_id, status=status, limit=limit)
        return {"jobs": jobs, "count": len(jobs)}

    # -- internals ---------------------------------------------------------

    async def _run_job(
        self,
        *,
        job_id: str,
        context: ReasoningContext,
        factors: Optional[List[Factor]],
        input_type: str,
    ) -> None:
        try:
            async with self._background_lock:
                self.store.update_job(job_id, status="running", error="")
                try:
                    result = await self.orchestrator.analyze(
                        context,
                        factors=factors,
                        input_type=input_type,
                    )
                    self.store.update_job(job_id, status="completed", payload=result, error="")
                except Exception as exc:  # noqa: BLE001
                    self.store.update_job(
                        job_id,
                        status="failed",
                        payload={"error": {"type": type(exc).__name__, "message": str(exc)}},
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    return
        except Exception as exc:  # noqa: BLE001
            self.store.update_job(
                job_id,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
            return

        job = self.store.get_job(job_id)
        if job is None or job["status"] != "completed":
            return
        await self._deliver_with_retries(job)

    async def _deliver_with_retries(self, job: Dict[str, Any]) -> None:
        job_id = job["job_id"]
        payload = {
            "event": EVENT_ANALYSIS_COMPLETED,
            "job_id": job_id,
            "webhook_id": job["webhook_id"],
            "request_id": job["request_id"],
            "timestamp": self._now_iso(),
            "payload": job["payload"],
        }
        for attempt in range(1, job["max_attempts"] + 1):
            outcome = await self._deliver(
                job["endpoint_url"],
                self.store.get_job_secret(job_id),
                EVENT_ANALYSIS_COMPLETED,
                payload,
            )
            self.store.append_delivery(
                job_id=job_id,
                attempt=attempt,
                status_code=outcome.get("status_code"),
                error=outcome.get("error", ""),
            )
            if outcome["success"]:
                self.store.mark_delivery_attempt(job_id, attempts=attempt, delivered_at=self._now_iso())
                if job.get("webhook_id"):
                    self.store.record_delivery_result(job["webhook_id"], outcome["status_code"] or 200)
                return
            if attempt < job["max_attempts"]:
                delay = self.base_delay * (2 ** (attempt - 1))
                self.store.mark_delivery_attempt(
                    job_id, attempts=attempt, next_retry_at=self._now_iso_offset(delay)
                )
                await asyncio.sleep(delay)

        self.store.mark_delivery_attempt(job_id, attempts=job["max_attempts"])
        self.store.update_job(job_id, status="failed", error="delivery_failed: max retries exceeded")
        if job.get("webhook_id"):
            self.store.record_delivery_result(job["webhook_id"], 0)

    async def _deliver(self, url: str, secret: str, event: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "ProjectAETHER-Webhook/1.0",
            "X-Aether-Event": event,
            "X-Aether-Delivery": self._now_iso(),
        }
        if secret:
            signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
            headers["X-Aether-Signature"] = f"sha256={signature}"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, content=body, headers=headers)
            status_code = response.status_code
            if 200 <= status_code < 300:
                return {"success": True, "status_code": status_code}
            return {"success": False, "status_code": status_code, "error": f"http_{status_code}"}
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "status_code": None, "error": f"{type(exc).__name__}: {exc}"}

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _now_iso() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _now_iso_offset(seconds: float) -> str:
        from datetime import datetime, timedelta, timezone

        return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
