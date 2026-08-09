from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.evaluation.tracker import PromptRun, PromptTracker
from app.prompts import PromptRegistry

_DEFAULT_DB = Path(__file__).resolve().parents[1] / "logs" / "aether_prompts.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prompt_votes (
    prompt_name TEXT NOT NULL,
    member_email TEXT NOT NULL,
    version TEXT NOT NULL,
    score INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (prompt_name, member_email)
);

CREATE TABLE IF NOT EXISTS prompt_deploys (
    deploy_id TEXT PRIMARY KEY,
    prompt_name TEXT NOT NULL,
    from_version TEXT NOT NULL,
    to_version TEXT NOT NULL,
    member_email TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_prompt_deploys_name ON prompt_deploys(prompt_name);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PromptOpsStore:
    """SQLite-backed votes and deploy history for prompt versions."""

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

    # -- votes -------------------------------------------------------------

    def vote(self, *, prompt_name: str, version: str, member_email: str, score: int) -> Dict[str, Any]:
        score = max(-1, min(1, score))
        now = _now_iso()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO prompt_votes (prompt_name, member_email, version, score, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(prompt_name, member_email)
                DO UPDATE SET version = excluded.version, score = excluded.score, updated_at = excluded.updated_at
                """,
                (prompt_name, member_email, version, score, now, now),
            )
        return {"prompt_name": prompt_name, "member_email": member_email, "version": version, "score": score}

    def my_vote(self, *, prompt_name: str, member_email: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT version, score FROM prompt_votes WHERE prompt_name = ? AND member_email = ?",
                (prompt_name, member_email),
            ).fetchone()
        return dict(row) if row else None

    def votes(self, prompt_name: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT version, COUNT(*) AS count, SUM(score) AS score, "
                "SUM(CASE WHEN score > 0 THEN 1 ELSE 0 END) AS upvotes, "
                "SUM(CASE WHEN score < 0 THEN 1 ELSE 0 END) AS downvotes "
                "FROM prompt_votes WHERE prompt_name = ? GROUP BY version",
                (prompt_name,),
            ).fetchall()
        return [
            {
                "version": row["version"],
                "count": row["count"],
                "score": row["score"] or 0,
                "upvotes": row["upvotes"] or 0,
                "downvotes": row["downvotes"] or 0,
            }
            for row in rows
        ]

    # -- deploys -----------------------------------------------------------

    def record_deploy(self, *, prompt_name: str, from_version: str, to_version: str, member_email: str = "") -> Dict[str, Any]:
        deploy_id = uuid.uuid4().hex
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO prompt_deploys (deploy_id, prompt_name, from_version, to_version, member_email, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (deploy_id, prompt_name, from_version, to_version, member_email, _now_iso()),
            )
        return {"deploy_id": deploy_id, "prompt_name": prompt_name, "from_version": from_version, "to_version": to_version}

    def deploy_history(self, prompt_name: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        query = "SELECT * FROM prompt_deploys"
        params: List[Any] = []
        if prompt_name:
            query += " WHERE prompt_name = ?"
            params.append(prompt_name)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


# --------------------------------------------------------------------------
# Metrics aggregation over PromptTracker JSONL
# --------------------------------------------------------------------------

_METRIC_FIELDS = (
    "overall_score",
    "relevance_score",
    "format_adherence",
    "argument_strength",
    "hallucination_risk",
)


def aggregate_metrics(runs: List[PromptRun]) -> Dict[str, Any]:
    """Aggregate a list of runs into per-version metric summaries."""
    by_version: Dict[str, Dict[str, Any]] = {}
    for run in runs:
        entry = by_version.setdefault(run.prompt_version, {"runs": [], "last_run_at": ""})
        entry["runs"].append(run)
        created = run.created_at.isoformat()
        if not entry["last_run_at"] or created > entry["last_run_at"]:
            entry["last_run_at"] = created

    summary: Dict[str, Any] = {}
    for version, entry in by_version.items():
        runs_list = entry["runs"]
        n = len(runs_list)
        metric_sums: Dict[str, float] = {}
        for field in _METRIC_FIELDS:
            values = [
                (getattr(run.metrics, field) if run.metrics is not None else None)
                for run in runs_list
            ]
            valid = [v for v in values if v is not None]
            metric_sums[field] = round(sum(valid) / len(valid), 4) if valid else None
        format_scores = [
            (getattr(run.metrics, "format_adherence") if run.metrics is not None else None)
            for run in runs_list
        ]
        summary[version] = {
            "run_count": n,
            "last_run_at": entry["last_run_at"],
            **metric_sums,
            "format_success_rate": round(
                sum(1 for v in format_scores if v is not None and v >= 1.0) / n, 4
            )
            if n
            else 0.0,
        }
    return summary


def prompt_catalog(
    *,
    registry: PromptRegistry,
    tracker: Optional[PromptTracker] = None,
    ops_store: Optional[PromptOpsStore] = None,
    member_email: str = "",
) -> List[Dict[str, Any]]:
    """Build the full prompt catalog with deployed version, metrics, and votes."""
    tracker = tracker or PromptTracker()
    ops_store = ops_store or PromptOpsStore()
    catalog: List[Dict[str, Any]] = []

    for name in registry.names():
        templates = registry.versions(name)
        try:
            deployed = registry.get(name)
            deployed_version = deployed.version
        except Exception:
            deployed_version = None

        runs = tracker.load_runs(name)
        metrics_by_version = aggregate_metrics(runs)
        votes_by_version = {v["version"]: v for v in ops_store.votes(name)}
        my_vote = ops_store.my_vote(prompt_name=name, member_email=member_email)

        versions: List[Dict[str, Any]] = []
        for template in templates:
            metrics = metrics_by_version.get(template.version, {})
            versions.append(
                {
                    "version": template.version,
                    "status": template.status,
                    "description": template.description,
                    "created_at": template.created_at.isoformat() if template.created_at else None,
                    "metrics": {
                        **metrics,
                        "has_runs": bool(metrics.get("run_count")),
                    },
                    "votes": votes_by_version.get(template.version, {"count": 0, "score": 0}),
                    "deployed": template.version == deployed_version,
                }
            )

        catalog.append(
            {
                "name": name,
                "deployed_version": deployed_version,
                "version_count": len(versions),
                "versions": versions,
                "my_vote": my_vote,
                "deploy_history": ops_store.deploy_history(name, limit=10),
            }
        )

    return sorted(catalog, key=lambda entry: entry["name"])


def deploy_version(
    *,
    registry: PromptRegistry,
    ops_store: PromptOpsStore,
    active_versions_file: Path,
    name: str,
    version: str,
    member_email: str = "",
) -> Dict[str, Any]:
    """Pin a prompt version as the deployed default and record the change."""
    template = registry.get(name, version=version)
    if template.status == "archived":
        raise ValueError(f"Cannot deploy archived version {version} of '{name}'")

    overrides: Dict[str, str] = {}
    if active_versions_file.exists():
        try:
            raw = json.loads(active_versions_file.read_text(encoding="utf-8"))
            overrides = raw if isinstance(raw, dict) else {}
        except Exception:
            overrides = {}

    old = overrides.get(name)
    overrides[name] = version
    tmp = active_versions_file.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(overrides, indent=2) + "\n", encoding="utf-8"
    )
    tmp.replace(active_versions_file)

    ops_store.record_deploy(
        prompt_name=name,
        from_version=old or "",
        to_version=version,
        member_email=member_email,
    )
    return {"name": name, "from_version": old or "", "to_version": version}


_ops_store: Optional[PromptOpsStore] = None
_ops_lock = threading.Lock()


def get_prompt_ops_store(db_path: Optional[Path | str] = None) -> PromptOpsStore:
    global _ops_store
    with _ops_lock:
        if _ops_store is None:
            _ops_store = PromptOpsStore(db_path=db_path)
        return _ops_store
