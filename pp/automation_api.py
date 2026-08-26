from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .auth import current_user, require_admin, require_csrf
from .automation_engine import ensure_automation_schema, run_once
from .config import Settings
from .db import Database, utcnow
from .services import audit
from .system_settings import get_all, set_values
from .workflow_center import run_workflow_cycle

VALID_MODES = {"manual", "assist", "rules", "autopilot"}


def _decode_summary(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}


def build_automation_router(db: Database, settings: Settings) -> APIRouter:
    ensure_automation_schema(db)
    router = APIRouter(prefix="/api/admin/automation")

    def admin(request: Request, *, mutate: bool = False) -> dict[str, Any]:
        user = current_user(db, request)
        require_admin(user)
        if mutate:
            require_csrf(request, user)
        return user

    @router.get("/status")
    def status(request: Request) -> dict[str, Any]:
        admin(request)
        values = get_all(db, settings)
        mode = str(values.get("autonomy_mode", "manual") or "manual").lower()
        if mode not in VALID_MODES:
            mode = "manual"
        last = db.one("SELECT * FROM automation_runs ORDER BY id DESC LIMIT 1")
        if last:
            last["summary"] = _decode_summary(last.pop("summary_json", "{}"))
        events = db.all(
            """SELECT id,category,severity,title,detail,entity_type,entity_id,state,first_seen_at,last_seen_at,resolved_at
               FROM automation_events
               ORDER BY CASE state WHEN 'open' THEN 0 ELSE 1 END,id DESC LIMIT 80"""
        )
        open_counts = {"danger": 0, "warning": 0, "info": 0, "total": 0}
        for event in events:
            if event["state"] == "open":
                open_counts["total"] += 1
                severity = str(event["severity"])
                if severity in open_counts:
                    open_counts[severity] += 1
        return {
            "mode": mode,
            "emergency_stop": bool(values.get("automation_emergency_stop", False)),
            "interval_minutes": int(values.get("automation_interval_minutes", 5) or 5),
            "rules": {
                "retry_failed_mail": bool(values.get("automation_retry_failed_mail", True)),
                "retry_after_minutes": int(values.get("automation_retry_after_minutes", 15) or 15),
                "retry_max_attempts": int(values.get("automation_retry_max_attempts", 5) or 5),
                "watch_upcoming": bool(values.get("automation_watch_upcoming", True)),
                "upcoming_days": int(values.get("automation_upcoming_days", 7) or 7),
                "watch_unassigned": bool(values.get("automation_watch_unassigned", True)),
                "watch_assignment_end": bool(values.get("automation_watch_assignment_end", True)),
                "assignment_end_days": int(values.get("automation_assignment_end_days", 3) or 3),
                "housekeeping": bool(values.get("automation_housekeeping", False)),
            },
            "open_counts": open_counts,
            "last_run": last,
            "events": events,
        }

    @router.post("/run")
    def run_now(request: Request) -> dict[str, Any]:
        user = admin(request, mutate=True)
        result = run_once(db, settings, trigger="manual")
        if not result.get("skipped"):
            mode = str(result.get("mode") or "assist")
            result["workflow"] = run_workflow_cycle(db, settings, mode=mode)
        audit(db, int(user["id"]), "automation_run_requested", "system", None, result)
        return result

    @router.post("/events/{event_id}/resolve")
    def resolve_event(event_id: int, request: Request) -> dict[str, Any]:
        user = admin(request, mutate=True)
        existing = db.one("SELECT id,state FROM automation_events WHERE id=?", (event_id,))
        if not existing:
            raise HTTPException(status_code=404, detail="Automation-Ereignis nicht gefunden")
        db.execute(
            "UPDATE automation_events SET state='resolved',resolved_at=?,last_seen_at=? WHERE id=?",
            (utcnow(), utcnow(), event_id),
        )
        audit(db, int(user["id"]), "automation_event_resolved", "automation_event", event_id)
        return {"ok": True}

    @router.post("/emergency-stop")
    def emergency_stop(request: Request) -> dict[str, Any]:
        user = admin(request, mutate=True)
        set_values(db, {"automation_emergency_stop": True}, int(user["id"]))
        audit(db, int(user["id"]), "automation_emergency_stop", "system", None)
        return {"ok": True}

    @router.post("/resume")
    def resume(request: Request) -> dict[str, Any]:
        user = admin(request, mutate=True)
        set_values(db, {"automation_emergency_stop": False}, int(user["id"]))
        audit(db, int(user["id"]), "automation_resumed", "system", None)
        return {"ok": True}

    return router
