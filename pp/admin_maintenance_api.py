from __future__ import annotations

from fastapi import APIRouter, Request

from .auth import current_user, require_admin, require_csrf
from .config import Settings
from .db import Database
from .services import audit
from .system_settings import get_all


def build_admin_maintenance_router(db: Database, settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/admin")

    def admin(request: Request) -> dict:
        user = current_user(db, request)
        require_admin(user)
        require_csrf(request, user)
        return user

    @router.post("/sessions/revoke-others")
    def revoke_other_sessions(request: Request) -> dict:
        user = admin(request)
        with db.transaction() as conn:
            cursor = conn.execute("DELETE FROM sessions WHERE id<>?", (user["session_id"],))
            deleted = int(cursor.rowcount or 0)
        audit(db, int(user["id"]), "other_sessions_revoked", "system", None, {"deleted": deleted})
        return {"ok": True, "deleted": deleted}

    @router.post("/audit/prune")
    def prune_audit(request: Request) -> dict:
        user = admin(request)
        values = get_all(db, settings)
        days = max(30, min(36500, int(values.get("audit_retention_days", 3650) or 3650)))
        with db.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM audit_log WHERE datetime(created_at) < datetime('now', ?)",
                (f"-{days} days",),
            )
            deleted = int(cursor.rowcount or 0)
        audit(db, int(user["id"]), "audit_pruned", "system", None, {"deleted": deleted, "retention_days": days})
        return {"ok": True, "deleted": deleted, "retention_days": days}

    return router
