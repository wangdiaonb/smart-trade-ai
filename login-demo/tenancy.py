"""Resolve tenant identity from the signed session, never from request data."""

from dataclasses import dataclass

from fastapi import HTTPException, Request

from database import connection


@dataclass(frozen=True)
class TenantContext:
    user_id: int
    workspace_id: int
    email: str


def require_tenant(request: Request) -> TenantContext:
    user_id = request.session.get("user_id")
    if type(user_id) is not int:
        raise HTTPException(401, "Not logged in")
    with connection(request.app.state.db_path) as conn:
        row = conn.execute("""
            SELECT users.id, users.email, workspaces.id AS workspace_id
            FROM users JOIN workspaces ON workspaces.owner_user_id = users.id
            WHERE users.id = ?
        """, (user_id,)).fetchone()
    if row is None:
        request.session.clear()
        raise HTTPException(401, "Not logged in")
    declared_workspace = request.headers.get("X-Workspace-ID")
    if declared_workspace is not None and declared_workspace != str(row["workspace_id"]):
        raise HTTPException(404, "Workspace not found")
    return TenantContext(row["id"], row["workspace_id"], row["email"])

