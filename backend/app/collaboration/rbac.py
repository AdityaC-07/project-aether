from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Depends, Header, HTTPException

from app.collaboration.store import TeamStore, get_team_store


def current_member(
    x_aether_user_email: str = Header(default=""),
    team_store: TeamStore = Depends(get_team_store),
) -> Optional[Dict[str, Any]]:
    """Resolve the acting team member from the identity header. Returns None
    for anonymous (read-only) access."""
    email = (x_aether_user_email or "").strip()
    if not email:
        return None
    member = team_store.get_member_by_email(email)
    if member is None:
        raise HTTPException(
            status_code=404,
            detail=f"No team member found for '{email}'. Ask an admin to add you.",
        )
    return member


def require_editor(member: Optional[Dict[str, Any]] = Depends(current_member)) -> Dict[str, Any]:
    if member is None or member["role"] not in ("editor", "admin"):
        raise HTTPException(status_code=403, detail="editor or admin role required")
    return member


def require_admin(member: Optional[Dict[str, Any]] = Depends(current_member)) -> Dict[str, Any]:
    if member is None or member["role"] != "admin":
        raise HTTPException(status_code=403, detail="admin role required")
    return member


def analysis_write_role(
    *,
    team_store: TeamStore,
    analysis_id: str,
    member: Optional[Dict[str, Any]],
) -> bool:
    """Effective write permission on one analysis.

    Admins always pass. A share with role 'viewer' downgrades the member to
    read-only on that analysis. Otherwise editor (global or via share) can write.
    """
    if member is None:
        return False
    if member["role"] == "admin":
        return True
    share_role = team_store.get_share_role(analysis_id, member["member_id"])
    if share_role == "viewer":
        return False
    if share_role == "editor":
        return True
    return member["role"] == "editor"


def analysis_editor(
    analysis_id: str,
    member: Optional[Dict[str, Any]] = Depends(current_member),
    team_store: TeamStore = Depends(get_team_store),
) -> Dict[str, Any]:
    """Dependency: the acting member may edit a specific analysis.

    Allowed for admins, global editors (unless downgraded to viewer on this
    analysis), and viewers who hold an editor share on this analysis.
    ``analysis_id`` is injected from the route path by FastAPI.
    """
    if member is None:
        raise HTTPException(status_code=403, detail="authentication required")
    if member["role"] == "admin":
        return member
    share_role = team_store.get_share_role(analysis_id, member["member_id"])
    if share_role == "editor":
        return member
    if member["role"] == "editor" and share_role != "viewer":
        return member
    raise HTTPException(
        status_code=403, detail="editor access required on this analysis"
    )
