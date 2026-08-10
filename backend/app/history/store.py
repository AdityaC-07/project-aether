from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

_DEFAULT_DB = Path(__file__).resolve().parents[1] / "logs" / "aether_history.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    input_type TEXT NOT NULL DEFAULT 'text',
    narrative TEXT NOT NULL DEFAULT '',
    factors_json TEXT NOT NULL DEFAULT '[]',
    final_report_json TEXT NOT NULL DEFAULT '{}',
    confidence_score REAL NOT NULL DEFAULT 0.0,
    degraded INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'completed'
);

CREATE TABLE IF NOT EXISTS factor_scores (
    analysis_id TEXT NOT NULL,
    factor_id TEXT NOT NULL,
    factor_description TEXT NOT NULL,
    domain TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL DEFAULT 0,
    confidence REAL NOT NULL DEFAULT 0.0,
    agreement REAL NOT NULL DEFAULT 0.0,
    contribution REAL NOT NULL DEFAULT 0.0,
    PRIMARY KEY (analysis_id, factor_id)
);

CREATE INDEX IF NOT EXISTS idx_analyses_created_at ON analyses(created_at);
CREATE INDEX IF NOT EXISTS idx_factor_scores_analysis ON factor_scores(analysis_id);
CREATE INDEX IF NOT EXISTS idx_factor_scores_description ON factor_scores(factor_description);
"""


class HistoryStore:
    """SQLite-backed persistence for past analyses and per-factor scores.

    The orchestrator writes one ``analyses`` row plus one ``factor_scores`` row
    per analyzed factor after each completed run, which powers the history,
    comparison, trend, and consistently-important-factor views.
    """

    def __init__(self, db_path: Optional[Path | str] = None, *, enabled: bool = True) -> None:
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB
        self.enabled = enabled
        self._lock = threading.Lock()
        if self.enabled:
            self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)

    # -- writes -------------------------------------------------------------

    def save_analysis(self, payload: Dict[str, Any]) -> str:
        """Insert or replace an analysis record and its factor scores."""
        if not self.enabled:
            return ""
        analysis_id = str(payload.get("analysis_id") or payload.get("request_id") or "")
        if not analysis_id:
            raise ValueError("analysis_id is required")

        factors = payload.get("factors") or []
        factor_scores = payload.get("factor_scores") or []
        final_report = payload.get("final_report") or {}
        scores_by_factor = {str(entry.get("factor_id")): entry for entry in factor_scores}

        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO analyses (
                    id, request_id, created_at, input_type, narrative,
                    factors_json, final_report_json, confidence_score, degraded, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    analysis_id,
                    str(payload.get("request_id") or analysis_id),
                    str(payload.get("created_at") or ""),
                    str(payload.get("input_type") or "text"),
                    str(payload.get("narrative") or ""),
                    json.dumps(factors, ensure_ascii=False),
                    json.dumps(final_report, ensure_ascii=False),
                    float(payload.get("confidence_score") or 0.0),
                    1 if payload.get("degraded") else 0,
                    str(payload.get("status") or "completed"),
                ),
            )
            conn.execute("DELETE FROM factor_scores WHERE analysis_id = ?", (analysis_id,))
            for position, factor in enumerate(factors, 1):
                factor_id = str(factor.get("factor_id") or f"F{position}")
                scores = scores_by_factor.get(factor_id, {})
                conn.execute(
                    """
                    INSERT INTO factor_scores (
                        analysis_id, factor_id, factor_description, domain,
                        position, confidence, agreement, contribution
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        analysis_id,
                        factor_id,
                        str(factor.get("description") or ""),
                        str(factor.get("domain") or ""),
                        position,
                        float(scores.get("confidence") or 0.0),
                        float(scores.get("agreement") or 0.0),
                        float(scores.get("contribution") or 0.0),
                    ),
                )
        return analysis_id

    def delete_analysis(self, analysis_id: str) -> bool:
        if not self.enabled:
            return False
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM factor_scores WHERE analysis_id = ?", (analysis_id,))
            cursor = conn.execute("DELETE FROM analyses WHERE id = ?", (analysis_id,))
            return cursor.rowcount > 0

    # -- reads --------------------------------------------------------------

    def list_analyses(self, *, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        if not self.enabled:
            return {"analyses": [], "total": 0, "offset": offset, "limit": limit}
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS n FROM analyses").fetchone()["n"]
            rows = conn.execute(
                """
                SELECT id, request_id, created_at, input_type, narrative,
                       factors_json, confidence_score, degraded, status
                FROM analyses
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (int(limit), int(offset)),
            ).fetchall()
        analyses = [self._summarize(row) for row in rows]
        return {"analyses": analyses, "total": total, "offset": offset, "limit": limit}

    def get_analysis(self, analysis_id: str) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()
            if row is None:
                return None
            factor_rows = conn.execute(
                """
                SELECT factor_id, factor_description, domain, position,
                       confidence, agreement, contribution
                FROM factor_scores WHERE analysis_id = ? ORDER BY position
                """,
                (analysis_id,),
            ).fetchall()
        return self._full(row, factor_rows)

    def compare_analyses(self, ids: List[str]) -> List[Dict[str, Any]]:
        analyses: List[Dict[str, Any]] = []
        for analysis_id in ids:
            record = self.get_analysis(analysis_id)
            if record is not None:
                analyses.append(record)
        return analyses

    def timeline(self, *, limit: int = 100) -> List[Dict[str, Any]]:
        """Chronological conclusion evolution (oldest first)."""
        if not self.enabled:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, request_id, created_at, factors_json, final_report_json,
                       confidence_score, degraded
                FROM analyses WHERE status = 'completed'
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()

        timeline: List[Dict[str, Any]] = []
        for row in rows:
            final_report = self._loads(row["final_report_json"], {})
            factors = self._loads(row["factors_json"], [])
            timeline.append(
                {
                    "analysis_id": row["id"],
                    "request_id": row["request_id"],
                    "created_at": row["created_at"],
                    "confidence_score": round(float(row["confidence_score"] or 0.0), 2),
                    "degraded": bool(row["degraded"]),
                    "factor_count": len(factors),
                    "recommendation": final_report.get("recommendation", ""),
                    "synthesis": final_report.get("synthesis", ""),
                    "top_factors": final_report.get("top_factors", []),
                    "overall_confidence": (
                        final_report.get("confidence_report", {}).get("overall_confidence")
                        if isinstance(final_report.get("confidence_report"), dict)
                        else None
                    ),
                }
            )
        return timeline

    def consistent_factors(self, *, min_occurrences: int = 2) -> List[Dict[str, Any]]:
        """Aggregate per-factor scores across analyses, ranked by how often a
        factor description recurs and how much it shaped conclusions."""
        if not self.enabled:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT TRIM(factor_description) AS description,
                       GROUP_CONCAT(DISTINCT domain) AS domains,
                       COUNT(*) AS occurrences,
                       COUNT(DISTINCT analysis_id) AS analyses,
                       ROUND(AVG(confidence), 2) AS avg_confidence,
                       ROUND(AVG(agreement), 2) AS avg_agreement,
                       ROUND(AVG(contribution), 2) AS avg_contribution,
                       ROUND(AVG(ABS(contribution)), 2) AS avg_abs_contribution
                FROM factor_scores
                WHERE TRIM(factor_description) != ''
                GROUP BY LOWER(TRIM(factor_description))
                HAVING occurrences >= ?
                ORDER BY occurrences DESC, avg_abs_contribution DESC, avg_confidence DESC
                """,
                (int(min_occurrences),),
            ).fetchall()
        return [
            {
                "description": row["description"],
                "domains": [d for d in (row["domains"] or "").split(",") if d],
                "occurrences": row["occurrences"],
                "analyses": row["analyses"],
                "avg_confidence": row["avg_confidence"],
                "avg_agreement": row["avg_agreement"],
                "avg_contribution": row["avg_contribution"],
                "avg_abs_contribution": row["avg_abs_contribution"],
            }
            for row in rows
        ]

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _loads(raw: Optional[str], default: Any) -> Any:
        if not raw:
            return default
        try:
            return json.loads(raw)
        except Exception:
            return default

    @staticmethod
    def _summarize(row: sqlite3.Row) -> Dict[str, Any]:
        factors = HistoryStore._loads(row["factors_json"], [])
        return {
            "analysis_id": row["id"],
            "request_id": row["request_id"],
            "created_at": row["created_at"],
            "input_type": row["input_type"],
            "narrative_preview": (row["narrative"] or "")[:200],
            "factor_count": len(factors),
            "factors": [HistoryStore._factor_summary(f) for f in factors],
            "confidence_score": round(float(row["confidence_score"] or 0.0), 2),
            "degraded": bool(row["degraded"]),
            "status": row["status"],
        }

    @staticmethod
    def _factor_summary(factor: Any) -> Dict[str, Any]:
        if isinstance(factor, dict):
            return {
                "factor_id": factor.get("factor_id"),
                "description": factor.get("description"),
                "domain": factor.get("domain"),
            }
        return {"factor_id": None, "description": None, "domain": None}

    @staticmethod
    def _full(row: sqlite3.Row, factor_rows: List[sqlite3.Row]) -> Dict[str, Any]:
        record = HistoryStore._summarize(row)
        record["narrative"] = row["narrative"]
        record["final_report"] = HistoryStore._loads(row["final_report_json"], {})
        record["factor_scores"] = [
            {
                "factor_id": r["factor_id"],
                "description": r["factor_description"],
                "domain": r["domain"],
                "position": r["position"],
                "confidence": r["confidence"],
                "agreement": r["agreement"],
                "contribution": r["contribution"],
            }
            for r in factor_rows
        ]
        return record


_store: Optional[HistoryStore] = None
_store_lock = threading.Lock()


def get_history_store(db_path: Optional[Path | str] = None) -> HistoryStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = HistoryStore(db_path=db_path)
        return _store
