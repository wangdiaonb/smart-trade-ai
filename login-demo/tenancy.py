"""Resolve tenant identity from the signed session, never from request data."""

from dataclasses import dataclass

from fastapi import HTTPException, Request

from database import connection


@dataclass(frozen=True)
class TenantContext:
    user_id: int
    workspace_id: int
    email: str
    company_id: int | None = None


def require_tenant(request: Request) -> TenantContext:
    user_id = request.session.get("user_id")
    if type(user_id) is not int:
        raise HTTPException(401, "Not logged in")
    with connection(request.app.state.db_path) as conn:
        row = conn.execute("""
            SELECT users.id, users.email, workspaces.id AS workspace_id,
                   (SELECT companies.id FROM companies
                    WHERE companies.workspace_id=workspaces.id
                    ORDER BY companies.id LIMIT 1) AS company_id
            FROM users JOIN workspaces ON workspaces.owner_user_id = users.id
            WHERE users.id = ?
        """, (user_id,)).fetchone()
    if row is None:
        request.session.clear()
        raise HTTPException(401, "Not logged in")
    declared_workspace = request.headers.get("X-Workspace-ID")
    if declared_workspace is not None and declared_workspace != str(row["workspace_id"]):
        raise HTTPException(404, "Workspace not found")
    company_id = row['company_id']
    selected = request.session.get('active_company_id')
    if type(selected) is int:
        with connection(request.app.state.db_path) as conn:
            valid = conn.execute(
                'SELECT 1 FROM companies WHERE id=? AND workspace_id=?',
                (selected, row['workspace_id']),
            ).fetchone()
        if valid:
            company_id = selected
    if company_id is not None:
        request.session['active_company_id'] = company_id
    return TenantContext(row["id"], row["workspace_id"], row["email"], company_id)

