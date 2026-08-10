from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_DEFAULT_DB = Path(__file__).resolve().parents[1] / "logs" / "aether_team.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS team_members (
    member_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL CHECK (role IN ('viewer', 'editor', 'admin')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analysis_shares (
    analysis_id TEXT NOT NULL,
    member_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('viewer', 'editor')),
    created_at TEXT NOT NULL,
    PRIMARY KEY (analysis_id, member_id)
);

CREATE TABLE IF NOT EXISTS annotations (
    annotation_id TEXT PRIMARY KEY,
    analysis_id TEXT NOT NULL,
    anchor TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    member_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS comments (
    comment_id TEXT PRIMARY KEY,
    analysis_id TEXT NOT NULL,
    anchor TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL,
    member_id TEXT NOT NULL,
    parent_id TEXT NOT NULL DEFAULT '',
    resolved INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_shares_analysis ON analysis_shares(analysis_id);
CREATE INDEX IF NOT EXISTS idx_annotations_analysis ON annotations(analysis_id);
CREATE INDEX IF NOT EXISTS idx_comments_analysis ON comments(analysis_id);
"""

ROLES = ("viewer", "editor", "admin")
SHARE_ROLES = ("viewer", "editor")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TeamStore:
    """SQLite-backed team members, analysis shares, annotations, and comments."""

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

    # -- members -----------------------------------------------------------

    def add_member(self, *, name: str, email: str, role: str = "viewer") -> Dict[str, Any]:
        role = role if role in ROLES else "viewer"
        member_id = new_id("mbr")
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO team_members (member_id, name, email, role, created_at) VALUES (?, ?, ?, ?, ?)",
                (member_id, name, email.lower().strip(), role, _now_iso()),
            )
            row = conn.execute(
                "SELECT * FROM team_members WHERE email = ?", (email.lower().strip(),)
            ).fetchone()
        return dict(row)

    def get_member_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        email = (email or "").strip().lower()
        if not email:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM team_members WHERE email = ?", (email,)
            ).fetchone()
        return dict(row) if row else None

    def get_member(self, member_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM team_members WHERE member_id = ?", (member_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_members(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM team_members ORDER BY role = 'admin' DESC, created_at ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    def update_role(self, member_id: str, role: str) -> Optional[Dict[str, Any]]:
        if role not in ROLES:
            raise ValueError(f"invalid role '{role}'")
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE team_members SET role = ? WHERE member_id = ?", (role, member_id)
            )
            if cursor.rowcount == 0:
                return None
        return self.get_member(member_id)

    def remove_member(self, member_id: str) -> bool:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM analysis_shares WHERE member_id = ?", (member_id,))
            conn.execute("DELETE FROM annotations WHERE member_id = ?", (member_id,))
            conn.execute("DELETE FROM comments WHERE member_id = ?", (member_id,))
            cursor = conn.execute("DELETE FROM team_members WHERE member_id = ?", (member_id,))
            return cursor.rowcount > 0

    # -- shares ------------------------------------------------------------

    def share_analysis(self, *, analysis_id: str, member_id: str, role: str = "viewer") -> Dict[str, Any]:
        role = role if role in SHARE_ROLES else "viewer"
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO analysis_shares (analysis_id, member_id, role, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (analysis_id, member_id, role, _now_iso()),
            )
        return {"analysis_id": analysis_id, "member_id": member_id, "role": role}

    def list_shares(self, analysis_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT s.analysis_id, s.role, s.created_at,
                       m.member_id, m.name, m.email
                FROM analysis_shares s
                JOIN team_members m ON m.member_id = s.member_id
                WHERE s.analysis_id = ?
                ORDER BY s.created_at ASC
                """,
                (analysis_id,),
            ).fetchall()
        return [
            {
                "analysis_id": row["analysis_id"],
                "member_id": row["member_id"],
                "name": row["name"],
                "email": row["email"],
                "role": row["role"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def get_share_role(self, analysis_id: str, member_id: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT role FROM analysis_shares WHERE analysis_id = ? AND member_id = ?",
                (analysis_id, member_id),
            ).fetchone()
        return row["role"] if row else None

    def update_share(self, analysis_id: str, member_id: str, role: str) -> bool:
        if role not in SHARE_ROLES:
            raise ValueError(f"invalid share role '{role}'")
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE analysis_shares SET role = ? WHERE analysis_id = ? AND member_id = ?",
                (role, analysis_id, member_id),
            )
            return cursor.rowcount > 0

    def remove_share(self, analysis_id: str, member_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM analysis_shares WHERE analysis_id = ? AND member_id = ?",
                (analysis_id, member_id),
            )
            return cursor.rowcount > 0

    # -- annotations -------------------------------------------------------

    def add_annotation(self, *, analysis_id: str, anchor: str, content: str, member_id: str) -> Dict[str, Any]:
        annotation_id = new_id("ann")
        now = _now_iso()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO annotations (annotation_id, analysis_id, anchor, content, member_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (annotation_id, analysis_id, anchor, content, member_id, now, now),
            )
        return self.get_annotation(annotation_id)

    def get_annotation(self, annotation_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM annotations WHERE annotation_id = ?", (annotation_id,)
            ).fetchone()
        return self._annotation_dict(row) if row else None

    def list_annotations(self, analysis_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT a.*, m.name AS member_name, m.email AS member_email
                FROM annotations a
                LEFT JOIN team_members m ON m.member_id = a.member_id
                WHERE a.analysis_id = ? ORDER BY a.created_at ASC
                """,
                (analysis_id,),
            ).fetchall()
        return [self._annotation_dict(row) for row in rows]

    def update_annotation(self, annotation_id: str, content: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE annotations SET content = ?, updated_at = ? WHERE annotation_id = ?",
                (content, _now_iso(), annotation_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_annotation(annotation_id)

    def delete_annotation(self, annotation_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM annotations WHERE annotation_id = ?", (annotation_id,)
            )
            return cursor.rowcount > 0

    @staticmethod
    def _annotation_dict(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "annotation_id": row["annotation_id"],
            "analysis_id": row["analysis_id"],
            "anchor": row["anchor"],
            "content": row["content"],
            "member_id": row["member_id"],
            "member_name": row["member_name"] if "member_name" in row.keys() else None,
            "member_email": row["member_email"] if "member_email" in row.keys() else None,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # -- comments ----------------------------------------------------------

    def add_comment(
        self, *, analysis_id: str, anchor: str, body: str, member_id: str, parent_id: str = ""
    ) -> Dict[str, Any]:
        comment_id = new_id("cmt")
        now = _now_iso()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO comments (comment_id, analysis_id, anchor, body, member_id, parent_id, resolved, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (comment_id, analysis_id, anchor, body, member_id, parent_id, now, now),
            )
        return self.get_comment(comment_id)

    def get_comment(self, comment_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM comments WHERE comment_id = ?", (comment_id,)
            ).fetchone()
        return self._comment_dict(row) if row else None

    def list_comments(self, analysis_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT c.*, m.name AS member_name, m.email AS member_email
                FROM comments c
                LEFT JOIN team_members m ON m.member_id = c.member_id
                WHERE c.analysis_id = ? ORDER BY c.created_at ASC
                """,
                (analysis_id,),
            ).fetchall()
        return [self._comment_dict(row) for row in rows]

    def set_comment_resolved(self, comment_id: str, resolved: bool) -> Optional[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE comments SET resolved = ?, updated_at = ? WHERE comment_id = ?",
                (1 if resolved else 0, _now_iso(), comment_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_comment(comment_id)

    def delete_comment(self, comment_id: str) -> bool:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM comments WHERE parent_id = ?", (comment_id,))
            cursor = conn.execute("DELETE FROM comments WHERE comment_id = ?", (comment_id,))
            return cursor.rowcount > 0

    @staticmethod
    def _comment_dict(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "comment_id": row["comment_id"],
            "analysis_id": row["analysis_id"],
            "anchor": row["anchor"],
            "body": row["body"],
            "member_id": row["member_id"],
            "member_name": row["member_name"] if "member_name" in row.keys() else None,
            "member_email": row["member_email"] if "member_email" in row.keys() else None,
            "parent_id": row["parent_id"],
            "resolved": bool(row["resolved"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


_store: Optional[TeamStore] = None
_store_lock = threading.Lock()


def get_team_store(db_path: Optional[Path | str] = None) -> TeamStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = TeamStore(db_path=db_path)
        return _store
