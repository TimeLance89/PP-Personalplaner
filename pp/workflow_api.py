from __future__ import annotations

import json
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .auth import current_user, require_admin, require_csrf
from .config import Settings
from .db import Database, utcnow
from .services import audit
from .workflow_center import ensure_workflow_schema, generate_briefing_for_user, inbox_for_user

WORKFLOW_DEFAULTS: dict[str, Any] = {
    "workflow_assignment_review_enabled": True,
    "workflow_assignment_review_days": 7,
    "briefing_enabled": True,
    "briefing_hour": 6,
    "briefing_days_ahead": 7,
    "briefing_email_enabled": False,
}
WORKFLOW_BOOL_KEYS = {"workflow_assignment_review_enabled", "briefing_enabled", "briefing_email_enabled"}
WORKFLOW_INT_LIMITS = {
    "workflow_assignment_review_days": (1, 60),
    "briefing_hour": (0, 23),
    "briefing_days_ahead": (1, 30),
}


class NotificationBody(BaseModel):
    user_id: int
    email: str = Field(default="", max_length=240)
    briefing_email_enabled: bool = False


class ExtendAssignmentBody(BaseModel):
    assigned_until: str


class WorkflowConfigBody(BaseModel):
    values: dict[str, Any]


def _user_with_department(db: Database, user: dict[str, Any]) -> dict[str, Any]:
    result = dict(user)
    if user.get("department_id"):
        dep = db.one("SELECT name FROM departments WHERE id=?", (user["department_id"],))
        result["department_name"] = dep["name"] if dep else ""
    else:
        result["department_name"] = ""
    return result


def _read_workflow_config(db: Database) -> dict[str, Any]:
    config = dict(WORKFLOW_DEFAULTS)
    placeholders = ",".join("?" for _ in WORKFLOW_DEFAULTS)
    rows = db.all(f"SELECT key,value FROM system_settings WHERE key IN ({placeholders})", tuple(WORKFLOW_DEFAULTS.keys()))
    for row in rows:
        key = str(row["key"])
        raw = str(row["value"] or "")
        if key in WORKFLOW_BOOL_KEYS:
            config[key] = raw.strip().lower() in {"1", "true", "yes", "on"}
        elif key in WORKFLOW_INT_LIMITS:
            low, high = WORKFLOW_INT_LIMITS[key]
            try:
                config[key] = max(low, min(high, int(raw)))
            except ValueError:
                pass
    return config


def _write_workflow_config(db: Database, values: dict[str, Any], user_id: int) -> dict[str, Any]:
    current = _read_workflow_config(db)
    clean: dict[str, Any] = {}
    for key, value in values.items():
        if key not in WORKFLOW_DEFAULTS:
            continue
        if key in WORKFLOW_BOOL_KEYS:
            clean[key] = bool(value)
        elif key in WORKFLOW_INT_LIMITS:
            low, high = WORKFLOW_INT_LIMITS[key]
            try:
                clean[key] = max(low, min(high, int(value)))
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=f"Ungültiger Wert für {key}") from exc
    with db.transaction() as conn:
        for key, value in clean.items():
            encoded = "1" if value is True else "" if value is False else str(value)
            conn.execute(
                """INSERT INTO system_settings(key,value,is_secret,updated_at,updated_by)
                   VALUES (?,?,0,?,?) ON CONFLICT(key) DO UPDATE SET
                   value=excluded.value,is_secret=0,updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                (key, encoded, utcnow(), user_id),
            )
            current[key] = value
    return current


def build_workflow_router(db: Database, settings: Settings) -> APIRouter:
    ensure_workflow_schema(db)
    router = APIRouter(prefix="/api")

    def user_for(request: Request, *, mutate: bool = False) -> dict[str, Any]:
        user = current_user(db, request)
        if mutate:
            require_csrf(request, user)
        return _user_with_department(db, user)

    def item_for_user(item_id: int, user: dict[str, Any]) -> dict[str, Any]:
        item = db.one("SELECT * FROM workflow_inbox WHERE id=?", (item_id,))
        if not item:
            raise HTTPException(status_code=404, detail="Inbox-Vorgang nicht gefunden")
        if user["role"] != "admin" and int(item.get("department_id") or -1) != int(user.get("department_id") or -2):
            raise HTTPException(status_code=403, detail="Kein Zugriff auf diesen Vorgang")
        return item

    @router.get("/workflow/inbox")
    def inbox(request: Request, include_done: bool = False) -> list[dict[str, Any]]:
        user = user_for(request)
        return inbox_for_user(db, user, include_done=include_done)

    @router.post("/workflow/inbox/{item_id}/resolve")
    def resolve(item_id: int, request: Request) -> dict[str, Any]:
        user = user_for(request, mutate=True)
        item_for_user(item_id, user)
        db.execute(
            "UPDATE workflow_inbox SET state='done',resolved_at=?,updated_at=? WHERE id=?",
            (utcnow(), utcnow(), item_id),
        )
        audit(db, int(user["id"]), "workflow_item_resolved", "workflow_inbox", item_id)
        return {"ok": True}

    @router.post("/workflow/inbox/{item_id}/extend-assignment")
    def extend_assignment(item_id: int, body: ExtendAssignmentBody, request: Request) -> dict[str, Any]:
        user = user_for(request, mutate=True)
        item = item_for_user(item_id, user)
        if item.get("entity_type") != "assignment" or not item.get("entity_id"):
            raise HTTPException(status_code=422, detail="Dieser Vorgang gehört zu keiner Zuteilung")
        try:
            new_date = date.fromisoformat(body.assigned_until)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Enddatum ungültig") from exc
        assignment = db.one("SELECT * FROM assignments WHERE id=?", (item["entity_id"],))
        if not assignment:
            raise HTTPException(status_code=404, detail="Zuteilung nicht gefunden")
        if user["role"] != "admin" and int(assignment["department_id"]) != int(user.get("department_id") or -1):
            raise HTTPException(status_code=403, detail="Kein Zugriff auf diese Zuteilung")
        start = date.fromisoformat(str(assignment["assigned_from"])[:10])
        if new_date < start:
            raise HTTPException(status_code=422, detail="Enddatum darf nicht vor dem Einsatzbeginn liegen")
        db.execute("UPDATE assignments SET assigned_until=? WHERE id=?", (new_date.isoformat(), assignment["id"]))
        db.execute(
            "UPDATE workflow_inbox SET state='done',resolved_at=?,updated_at=? WHERE id=?",
            (utcnow(), utcnow(), item_id),
        )
        audit(
            db,
            int(user["id"]),
            "assignment_extended_from_workflow",
            "assignment",
            int(assignment["id"]),
            {"assigned_until": new_date.isoformat()},
        )
        return {"ok": True, "assigned_until": new_date.isoformat()}

    @router.get("/workflow/briefings/latest")
    def latest_briefing(request: Request) -> dict[str, Any]:
        user = user_for(request)
        row = db.one("SELECT * FROM daily_briefings WHERE user_id=? ORDER BY briefing_date DESC,id DESC LIMIT 1", (user["id"],))
        if not row:
            return {"available": False}
        try:
            summary = json.loads(row.pop("summary_json", "{}"))
        except (TypeError, json.JSONDecodeError):
            summary = {}
        row["summary"] = summary
        row["available"] = True
        return row

    @router.get("/workflow/briefings")
    def briefings(request: Request) -> list[dict[str, Any]]:
        user = user_for(request)
        rows = db.all("SELECT * FROM daily_briefings WHERE user_id=? ORDER BY briefing_date DESC,id DESC LIMIT 31", (user["id"],))
        for row in rows:
            try:
                row["summary"] = json.loads(row.pop("summary_json", "{}"))
            except (TypeError, json.JSONDecodeError):
                row["summary"] = {}
        return rows

    @router.post("/workflow/briefings/generate")
    def generate_briefing(request: Request) -> dict[str, Any]:
        user = user_for(request, mutate=True)
        briefing = generate_briefing_for_user(db, settings, user, allow_email=False)
        audit(db, int(user["id"]), "briefing_generated_manually", "briefing", int(briefing["id"]))
        return briefing

    @router.get("/workflow/schedules")
    def schedules(request: Request) -> list[dict[str, Any]]:
        user = user_for(request)
        if user["role"] == "admin":
            return db.all(
                """SELECT s.*,d.name AS department_name FROM scheduled_actions s
                   LEFT JOIN departments d ON d.id=s.department_id ORDER BY s.scheduled_for DESC,s.id DESC LIMIT 100"""
            )
        return db.all(
            """SELECT s.*,d.name AS department_name FROM scheduled_actions s
               LEFT JOIN departments d ON d.id=s.department_id
               WHERE s.department_id=? ORDER BY s.scheduled_for DESC,s.id DESC LIMIT 100""",
            (user.get("department_id") or -1,),
        )

    @router.get("/admin/workflow/config")
    def workflow_config(request: Request) -> dict[str, Any]:
        user = user_for(request)
        require_admin(user)
        return _read_workflow_config(db)

    @router.put("/admin/workflow/config")
    def update_workflow_config(body: WorkflowConfigBody, request: Request) -> dict[str, Any]:
        user = user_for(request, mutate=True)
        require_admin(user)
        config = _write_workflow_config(db, body.values, int(user["id"]))
        audit(db, int(user["id"]), "workflow_config_updated", "system", None, {"keys": sorted(body.values.keys())})
        return config

    @router.get("/admin/workflow/notifications")
    def notifications(request: Request) -> list[dict[str, Any]]:
        user = user_for(request)
        require_admin(user)
        return db.all(
            """SELECT u.id AS user_id,u.display_name,u.username,u.role,u.department_id,d.name AS department_name,
                      COALESCE(n.email,'') AS email,COALESCE(n.briefing_email_enabled,0) AS briefing_email_enabled
               FROM users u LEFT JOIN departments d ON d.id=u.department_id
               LEFT JOIN user_notifications n ON n.user_id=u.id
               WHERE u.active=1 ORDER BY u.role,u.display_name COLLATE NOCASE"""
        )

    @router.put("/admin/workflow/notifications")
    def update_notification(body: NotificationBody, request: Request) -> dict[str, Any]:
        user = user_for(request, mutate=True)
        require_admin(user)
        if not db.one("SELECT id FROM users WHERE id=? AND active=1", (body.user_id,)):
            raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
        email = body.email.strip()
        if body.briefing_email_enabled and "@" not in email:
            raise HTTPException(status_code=422, detail="Für den E-Mail-Versand muss eine gültige E-Mail-Adresse hinterlegt sein")
        with db.transaction() as conn:
            conn.execute(
                """INSERT INTO user_notifications(user_id,email,briefing_email_enabled,updated_at)
                   VALUES (?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
                   email=excluded.email,briefing_email_enabled=excluded.briefing_email_enabled,updated_at=excluded.updated_at""",
                (body.user_id, email[:240], int(body.briefing_email_enabled), utcnow()),
            )
        audit(
            db,
            int(user["id"]),
            "workflow_notification_updated",
            "user",
            body.user_id,
            {"briefing_email_enabled": body.briefing_email_enabled},
        )
        return {"ok": True}

    return router
