from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

_DEFAULT_DB = Path(__file__).resolve().parents[1] / "logs" / "aether_webhooks.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS webhook_endpoints (
    webhook_id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    secret TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    events TEXT NOT NULL DEFAULT '["analysis.completed"]',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_delivery_at TEXT NOT NULL DEFAULT '',
    last_status_code INTEGER
);

CREATE TABLE IF NOT EXISTS webhook_jobs (
    job_id TEXT PRIMARY KEY,
    webhook_id TEXT NOT NULL DEFAULT '',
    endpoint_url TEXT NOT NULL DEFAULT '',
    secret TEXT NOT NULL DEFAULT '',
    request_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued',
    payload_json TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    next_retry_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    delivered_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS webhook_deliveries (
    job_id TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    status_code INTEGER,
    error TEXT NOT NULL DEFAULT '',
    delivered_at TEXT NOT NULL,
    PRIMARY KEY (job_id, attempt)
);

CREATE INDEX IF NOT EXISTS idx_webhook_jobs_status ON webhook_jobs(status);
CREATE INDEX IF NOT EXISTS idx_webhook_jobs_created ON webhook_jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_webhook_jobs_webhook ON webhook_jobs(webhook_id);
"""


def new_job_id() -> str:
    return f"job_{uuid.uuid4().hex}"


def new_webhook_id() -> str:
    return f"whk_{uuid.uuid4().hex}"


def new_secret() -> str:
    return secrets.token_urlsafe(32)


class WebhookStore:
    """SQLite-backed persistence for webhook endpoints, async jobs, and
    delivery attempts."""

    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)

    # -- endpoints ----------------------------------------------------------

    def create_endpoint(
        self, *, url: str, secret: str = "", description: str = "", events: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        webhook_id = new_webhook_id()
        events = events or ["analysis.completed"]
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO webhook_endpoints (
                    webhook_id, url, secret, description, events, active, created_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?)
                """,
                (webhook_id, url, secret, description, json.dumps(events), _now_iso()),
            )
        return self.get_endpoint(webhook_id)

    def get_endpoint(self, webhook_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM webhook_endpoints WHERE webhook_id = ?", (webhook_id,)
            ).fetchone()
        return self._endpoint_dict(row) if row else None

    def list_endpoints(self, *, active_only: bool = False) -> List[Dict[str, Any]]:
        query = "SELECT * FROM webhook_endpoints"
        if active_only:
            query += " WHERE active = 1"
        query += " ORDER BY created_at DESC"
        with self._connect() as conn:
            rows = conn.execute(query).fetchall()
        return [self._endpoint_dict(row) for row in rows]

    def set_endpoint_active(self, webhook_id: str, active: bool) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE webhook_endpoints SET active = ? WHERE webhook_id = ?",
                (1 if active else 0, webhook_id),
            )
            return cursor.rowcount > 0

    def record_delivery_result(self, webhook_id: str, status_code: int) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE webhook_endpoints
                SET last_delivery_at = ?, last_status_code = ?
                WHERE webhook_id = ?
                """,
                (_now_iso(), status_code, webhook_id),
            )

    # -- jobs ---------------------------------------------------------------

    def create_job(
        self,
        *,
        webhook_id: str = "",
        endpoint_url: str = "",
        secret: str = "",
        request_id: str = "",
        max_attempts: int = 5,
    ) -> Dict[str, Any]:
        job_id = new_job_id()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO webhook_jobs (
                    job_id, webhook_id, endpoint_url, secret, request_id,
                    status, max_attempts, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?)
                """,
                (job_id, webhook_id, endpoint_url, secret, request_id, max_attempts, _now_iso(), _now_iso()),
            )
        return self.get_job(job_id)

    def update_job(
        self,
        job_id: str,
        *,
        status: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        error: str = "",
    ) -> None:
        sets = ["updated_at = ?"]
        params: List[Any] = [_now_iso()]
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if payload is not None:
            sets.append("payload_json = ?")
            params.append(json.dumps(payload, ensure_ascii=False))
        if error is not None:
            sets.append("error = ?")
            params.append(error)
        params.append(job_id)
        with self._lock, self._connect() as conn:
            conn.execute(f"UPDATE webhook_jobs SET {', '.join(sets)} WHERE job_id = ?", params)

    def mark_delivery_attempt(self, job_id: str, *, attempts: int, next_retry_at: str = "", delivered_at: str = "") -> None:
        sets = ["updated_at = ?", "attempts = ?"]
        params: List[Any] = [_now_iso(), attempts]
        if next_retry_at:
            sets.append("next_retry_at = ?")
            params.append(next_retry_at)
        if delivered_at:
            sets.append("delivered_at = ?")
            params.append(delivered_at)
        params.append(job_id)
        with self._lock, self._connect() as conn:
            conn.execute(f"UPDATE webhook_jobs SET {', '.join(sets)} WHERE job_id = ?", params)

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM webhook_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._job_dict(row) if row else None

    def list_jobs(self, *, webhook_id: str = "", status: str = "", limit: int = 50) -> List[Dict[str, Any]]:
        query = "SELECT * FROM webhook_jobs WHERE 1=1"
        params: List[Any] = []
        if webhook_id:
            query += " AND webhook_id = ?"
            params.append(webhook_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._job_dict(row) for row in rows]

    def list_deliveries(self, job_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM webhook_deliveries WHERE job_id = ? ORDER BY attempt",
                (job_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_job_secret(self, job_id: str) -> str:
        """Internal: fetch the signing secret for a job without exposing it in API payloads."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT secret FROM webhook_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return row["secret"] if row else ""

    def append_delivery(self, *, job_id: str, attempt: int, status_code: Optional[int], error: str = "") -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO webhook_deliveries (job_id, attempt, status_code, error, delivered_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (job_id, attempt, status_code, error, _now_iso()),
            )

    def recover_stale_running_jobs(self) -> int:
        """Mark jobs that never finished (e.g. process restarted) as failed."""
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE webhook_jobs SET status = 'failed', error = 'interrupted: process restarted', updated_at = ? "
                "WHERE status IN ('queued', 'running')",
                (_now_iso(),),
            )
            return cursor.rowcount

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _endpoint_dict(row: sqlite3.Row) -> Dict[str, Any]:
        events = json.loads(row["events"]) if row["events"] else []
        return {
            "webhook_id": row["webhook_id"],
            "url": row["url"],
            "secret": row["secret"],
            "description": row["description"],
            "events": events,
            "active": bool(row["active"]),
            "created_at": row["created_at"],
            "last_delivery_at": row["last_delivery_at"],
            "last_status_code": row["last_status_code"],
        }

    @staticmethod
    def _job_dict(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "job_id": row["job_id"],
            "webhook_id": row["webhook_id"],
            "endpoint_url": row["endpoint_url"],
            "request_id": row["request_id"],
            "status": row["status"],
            "payload": json.loads(row["payload_json"]) if row["payload_json"] else {},
            "error": row["error"],
            "attempts": row["attempts"],
            "max_attempts": row["max_attempts"],
            "next_retry_at": row["next_retry_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "delivered_at": row["delivered_at"],
        }


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


_store: Optional[WebhookStore] = None
_store_lock = threading.Lock()


def get_webhook_store(db_path: Optional[Path | str] = None) -> WebhookStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = WebhookStore(db_path=db_path)
        return _store
