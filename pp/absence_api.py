from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from .absence_service import (
    absence_rows,
    assignment_allows_absence,
    build_monthly_report,
    ensure_absence_schema,
    get_stored_report,
    month_bounds,
    overlapping_absence,
    report_csv,
    store_monthly_report,
    working_days,
)
from .auth import current_user, require_admin, require_csrf
from .config import Settings
from .db import Database, utcnow
from .services import audit


class AbsenceBody(BaseModel):
    worker_id: int
    absence_type_id: int
    starts_on: str
    ends_on: str
    day_part: Literal["full", "morning", "afternoon"] = "full"
    note: str = Field(default="", max_length=1000)


class QuickSickBody(BaseModel):
    worker_id: int


class AbsenceTypeBody(BaseModel):
    label: str = Field(min_length=2, max_length=120)
    code: str = Field(min_length=2, max_length=50, pattern=r"^[a-z][a-z0-9_]*$")
    active: bool = True
    sort_order: int = 100


def build_absence_router(db: Database, settings: Settings) -> APIRouter:
    ensure_absence_schema(db)
    router = APIRouter(prefix="/api")

    def user_for(request: Request, *, mutate: bool = False) -> dict[str, Any]:
        user = current_user(db, request)
        if mutate:
            require_csrf(request, user)
        return user

    def scoped_department(user: dict[str, Any], requested: int | None = None) -> int | None:
        if user["role"] == "admin":
            return requested
        if not user.get("department_id"):
            raise HTTPException(status_code=403, detail="Dieser Bereichsleiter hat keine Abteilung")
        if requested is not None and int(requested) != int(user["department_id"]):
            raise HTTPException(status_code=403, detail="Kein Zugriff auf diese Abteilung")
        return int(user["department_id"])

    def absence_for_user(absence_id: int, user: dict[str, Any]) -> dict[str, Any]:
        row = db.one("SELECT * FROM absences WHERE id=?", (absence_id,))
        if not row:
            raise HTTPException(status_code=404, detail="Abwesenheit nicht gefunden")
        if user["role"] != "admin" and int(row["department_id"]) != int(user.get("department_id") or -1):
            raise HTTPException(status_code=403, detail="Kein Zugriff auf diese Abwesenheit")
        return row

    def active_assignment_for_quick_sick(worker_id: int, user: dict[str, Any]) -> dict[str, Any]:
        today = date.today().isoformat()
        params: list[Any] = [worker_id, today, today]
        filter_sql = ""
        if user["role"] != "admin":
            if not user.get("department_id"):
                raise HTTPException(status_code=403, detail="Dieser Bereichsleiter hat keine Abteilung")
            filter_sql = " AND a.department_id=?"
            params.append(int(user["department_id"]))
        row = db.one(
            f"""SELECT a.id,a.department_id,a.assigned_from,a.assigned_until
                FROM assignments a JOIN workers w ON w.id=a.worker_id
                WHERE a.worker_id=? AND w.status!='archived'
                  AND date(a.assigned_from)<=date(?)
                  AND (a.assigned_until IS NULL OR date(a.assigned_until)>=date(?))
                  {filter_sql}
                ORDER BY a.id DESC LIMIT 1""",
            tuple(params),
        )
        if not row:
            raise HTTPException(status_code=403 if user["role"] != "admin" else 422, detail="Für heute existiert keine passende Zuteilung")
        return row

    def validate_absence(body: AbsenceBody, user: dict[str, Any], *, exclude_id: int | None = None) -> tuple[date, date, int]:
        try:
            starts = date.fromisoformat(body.starts_on)
            ends = date.fromisoformat(body.ends_on)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Abwesenheitszeitraum ungültig") from exc
        if ends < starts:
            raise HTTPException(status_code=422, detail="Enddatum darf nicht vor dem Startdatum liegen")
        if (ends - starts).days > 366:
            raise HTTPException(status_code=422, detail="Eine einzelne Abwesenheit darf maximal 366 Kalendertage umfassen")
        if body.day_part != "full" and starts != ends:
            raise HTTPException(status_code=422, detail="Halbtägige Abwesenheiten müssen an einem einzelnen Tag liegen")
        if not db.one("SELECT id FROM workers WHERE id=? AND status!='archived'", (body.worker_id,)):
            raise HTTPException(status_code=404, detail="Zeitarbeiter nicht gefunden")
        absence_type = db.one("SELECT id FROM absence_types WHERE id=? AND active=1", (body.absence_type_id,))
        if not absence_type:
            raise HTTPException(status_code=422, detail="Abwesenheitsart ungültig")

        if user["role"] == "admin":
            assignments = db.all(
                """SELECT department_id FROM assignments WHERE worker_id=?
                   AND date(assigned_from)<=date(?) AND (assigned_until IS NULL OR date(assigned_until)>=date(?))
                   ORDER BY id DESC""",
                (body.worker_id, body.starts_on, body.ends_on),
            )
            if not assignments:
                raise HTTPException(status_code=422, detail="Für den gesamten Zeitraum existiert keine passende Zuteilung")
            department_id = int(assignments[0]["department_id"])
        else:
            department_id = int(user.get("department_id") or 0)
            if not department_id or not assignment_allows_absence(db, body.worker_id, department_id, body.starts_on, body.ends_on):
                raise HTTPException(status_code=403, detail="Der Zeitarbeiter war im gesamten angegebenen Zeitraum nicht Ihrer Abteilung zugeteilt")

        overlap = overlapping_absence(db, body.worker_id, body.starts_on, body.ends_on, exclude_id=exclude_id)
        if overlap:
            raise HTTPException(status_code=409, detail=f"Für diesen Zeitraum existiert bereits eine Abwesenheit ({overlap['label']})")
        return starts, ends, department_id

    @router.get("/absence-types")
    def absence_types(request: Request, include_inactive: bool = False) -> list[dict[str, Any]]:
        user = user_for(request)
        if include_inactive:
            require_admin(user)
            return db.all("SELECT * FROM absence_types ORDER BY active DESC,sort_order,id")
        return db.all("SELECT * FROM absence_types WHERE active=1 ORDER BY sort_order,id")

    @router.post("/absence-types")
    def create_absence_type(body: AbsenceTypeBody, request: Request) -> dict[str, Any]:
        user = user_for(request, mutate=True)
        require_admin(user)
        try:
            entity_id = db.execute(
                "INSERT INTO absence_types(label,code,active,sort_order,created_at) VALUES (?,?,?,?,?)",
                (body.label.strip(), body.code.strip(), int(body.active), body.sort_order, utcnow()),
            )
        except Exception as exc:
            raise HTTPException(status_code=409, detail="Bezeichnung oder Code ist bereits vorhanden") from exc
        audit(db, int(user["id"]), "absence_type_created", "absence_type", entity_id)
        return {"id": entity_id}

    @router.patch("/absence-types/{type_id}")
    def update_absence_type(type_id: int, body: AbsenceTypeBody, request: Request) -> dict[str, Any]:
        user = user_for(request, mutate=True)
        require_admin(user)
        if not db.one("SELECT id FROM absence_types WHERE id=?", (type_id,)):
            raise HTTPException(status_code=404, detail="Abwesenheitsart nicht gefunden")
        try:
            db.execute(
                "UPDATE absence_types SET label=?,code=?,active=?,sort_order=? WHERE id=?",
                (body.label.strip(), body.code.strip(), int(body.active), body.sort_order, type_id),
            )
        except Exception as exc:
            raise HTTPException(status_code=409, detail="Bezeichnung oder Code ist bereits vorhanden") from exc
        audit(db, int(user["id"]), "absence_type_updated", "absence_type", type_id)
        return {"ok": True}

    @router.get("/absences")
    def list_absences(request: Request, month: str | None = None, department_id: int | None = None) -> list[dict[str, Any]]:
        user = user_for(request)
        dep_id = scoped_department(user, department_id)
        if month:
            try:
                month_bounds(month)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        return absence_rows(db, department_id=dep_id, month=month)

    @router.post("/absences/quick-sick")
    def quick_sick(body: QuickSickBody, request: Request) -> dict[str, Any]:
        user = user_for(request, mutate=True)
        assignment = active_assignment_for_quick_sick(body.worker_id, user)
        today = date.today().isoformat()
        existing = overlapping_absence(db, body.worker_id, today, today)
        if existing:
            raise HTTPException(status_code=409, detail=f"Für heute existiert bereits eine Abwesenheit ({existing['label']})")
        sick = db.one("SELECT id FROM absence_types WHERE code='sick' AND active=1")
        if not sick:
            raise HTTPException(status_code=422, detail="Die Abwesenheitsart Krankheit ist nicht aktiv")
        entity_id = db.execute(
            """INSERT INTO absences(worker_id,department_id,absence_type_id,starts_on,ends_on,day_part,open_ended,note,recorded_by,created_at,updated_at)
               VALUES (?,?,?,?,?,'full',1,'',?,?,?)""",
            (body.worker_id, assignment["department_id"], sick["id"], today, today, user["id"], utcnow(), utcnow()),
        )
        audit(db, int(user["id"]), "sickness_started", "absence", entity_id, {"worker_id": body.worker_id, "starts_on": today})
        return {"id": entity_id, "starts_on": today, "open_ended": True}

    @router.post("/absences/{absence_id}/return")
    def return_from_absence(absence_id: int, request: Request) -> dict[str, Any]:
        user = user_for(request, mutate=True)
        row = absence_for_user(absence_id, user)
        if not bool(row.get("open_ended")):
            raise HTTPException(status_code=409, detail="Diese Abwesenheit ist bereits beendet")
        starts = date.fromisoformat(row["starts_on"])
        last_absent = max(starts, date.today() - timedelta(days=1))
        db.execute("UPDATE absences SET ends_on=?,open_ended=0,updated_at=? WHERE id=?", (last_absent.isoformat(), utcnow(), absence_id))
        audit(db, int(user["id"]), "sickness_returned", "absence", absence_id, {"last_absent_day": last_absent.isoformat()})
        return {"ok": True, "ends_on": last_absent.isoformat()}

    @router.post("/absences")
    def create_absence(body: AbsenceBody, request: Request) -> dict[str, Any]:
        user = user_for(request, mutate=True)
        starts, ends, department_id = validate_absence(body, user)
        entity_id = db.execute(
            """INSERT INTO absences(worker_id,department_id,absence_type_id,starts_on,ends_on,day_part,open_ended,note,recorded_by,created_at,updated_at)
               VALUES (?,?,?,?,?,?,0,?,?,?,?)""",
            (
                body.worker_id, department_id, body.absence_type_id, starts.isoformat(), ends.isoformat(), body.day_part,
                body.note.strip()[:1000], user["id"], utcnow(), utcnow(),
            ),
        )
        audit(
            db, int(user["id"]), "absence_recorded", "absence", entity_id,
            {"worker_id": body.worker_id, "department_id": department_id, "starts_on": starts.isoformat(), "ends_on": ends.isoformat()},
        )
        return {"id": entity_id, "working_days": working_days(starts, ends, body.day_part)}

    @router.patch("/absences/{absence_id}")
    def update_absence(absence_id: int, body: AbsenceBody, request: Request) -> dict[str, Any]:
        user = user_for(request, mutate=True)
        existing = absence_for_user(absence_id, user)
        starts, ends, department_id = validate_absence(body, user, exclude_id=absence_id)
        if user["role"] != "admin" and int(existing["department_id"]) != department_id:
            raise HTTPException(status_code=403, detail="Abwesenheiten dürfen nicht in einen anderen Bereich verschoben werden")
        db.execute(
            """UPDATE absences SET worker_id=?,department_id=?,absence_type_id=?,starts_on=?,ends_on=?,day_part=?,open_ended=0,note=?,updated_at=? WHERE id=?""",
            (
                body.worker_id, department_id, body.absence_type_id, starts.isoformat(), ends.isoformat(), body.day_part,
                body.note.strip()[:1000], utcnow(), absence_id,
            ),
        )
        audit(db, int(user["id"]), "absence_updated", "absence", absence_id)
        return {"ok": True, "working_days": working_days(starts, ends, body.day_part)}

    @router.delete("/absences/{absence_id}")
    def delete_absence(absence_id: int, request: Request) -> dict[str, Any]:
        user = user_for(request, mutate=True)
        absence_for_user(absence_id, user)
        db.execute("DELETE FROM absences WHERE id=?", (absence_id,))
        audit(db, int(user["id"]), "absence_deleted", "absence", absence_id)
        return {"ok": True}

    @router.get("/reports/absences/monthly")
    def monthly_report(request: Request, month: str, department_id: int | None = None, live: bool = False) -> dict[str, Any]:
        user = user_for(request)
        dep_id = scoped_department(user, department_id)
        try:
            month_start, _ = month_bounds(month)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not live and month_start < date.today().replace(day=1):
            stored = get_stored_report(db, month, dep_id)
            if stored:
                return stored
        report = build_monthly_report(db, month, dep_id)
        report["finalized"] = False
        return report

    @router.post("/reports/absences/monthly/finalize")
    def finalize_monthly_report(request: Request, month: str, department_id: int | None = None) -> dict[str, Any]:
        user = user_for(request, mutate=True)
        dep_id = scoped_department(user, department_id)
        try:
            month_bounds(month)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        report = store_monthly_report(db, month, dep_id)
        audit(db, int(user["id"]), "absence_monthly_report_refreshed", "department", dep_id, {"month": month})
        return report

    @router.get("/reports/absences/monthly.csv")
    def monthly_report_csv(request: Request, month: str, department_id: int | None = None) -> PlainTextResponse:
        user = user_for(request)
        dep_id = scoped_department(user, department_id)
        try:
            month_bounds(month)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        report = get_stored_report(db, month, dep_id) or build_monthly_report(db, month, dep_id)
        label = (report.get("department") or {}).get("code") or (report.get("department") or {}).get("name") or "gesamt"
        filename = f"PP-Abwesenheiten-{month}-{str(label).replace(' ', '_')}.csv"
        return PlainTextResponse(
            report_csv(report),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return router
