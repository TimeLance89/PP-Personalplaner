from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from fastapi import HTTPException

from .config import Settings
from .db import Database, json_load, utcnow
from .system_settings import get_all

FIELD_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,48}$")


def audit(db: Database, user_id: int | None, action: str, entity_type: str, entity_id: int | None, details: dict[str, Any] | None = None) -> None:
    db.execute(
        "INSERT INTO audit_log(user_id,action,entity_type,entity_id,details_json,created_at) VALUES (?,?,?,?,?,?)",
        (user_id, action, entity_type, entity_id, json.dumps(details or {}, ensure_ascii=False), utcnow()),
    )


def normalize_custom_data(db: Database, entity_type: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = payload or {}
    fields = db.all(
        "SELECT * FROM custom_fields WHERE entity_type=? AND active=1 ORDER BY sort_order,id",
        (entity_type,),
    )
    allowed = {field["field_key"]: field for field in fields}
    result: dict[str, Any] = {}
    for key, value in payload.items():
        if key not in allowed:
            continue
        field = allowed[key]
        if value in (None, ""):
            if field["required"]:
                raise HTTPException(status_code=422, detail=f"Pflichtfeld fehlt: {field['label']}")
            result[key] = value
            continue
        if field["field_type"] == "number":
            try:
                value = float(value)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=f"Ungültige Zahl: {field['label']}") from exc
        elif field["field_type"] == "boolean":
            value = bool(value)
        elif field["field_type"] == "select":
            options = json_load(field["options_json"], [])
            if str(value) not in options:
                raise HTTPException(status_code=422, detail=f"Ungültige Auswahl: {field['label']}")
            value = str(value)
        else:
            value = str(value).strip()
        result[key] = value
    for key, field in allowed.items():
        if field["required"] and key not in result:
            raise HTTPException(status_code=422, detail=f"Pflichtfeld fehlt: {field['label']}")
    return result


def active_assignment_sql(extra_where: str = "") -> str:
    return f"""
        SELECT a.*, d.name AS department_name, d.code AS department_code,
               w.first_name, w.last_name, w.employee_code, w.agency_id, w.start_date,
               w.status AS worker_status, w.notes AS worker_notes, w.custom_data,
               ag.name AS agency_name, ag.email AS agency_email
        FROM assignments a
        JOIN departments d ON d.id=a.department_id
        JOIN workers w ON w.id=a.worker_id
        JOIN agencies ag ON ag.id=w.agency_id
        WHERE w.status!='archived'
          AND date(a.assigned_from) <= date('now','localtime')
          AND (a.assigned_until IS NULL OR date(a.assigned_until) >= date('now','localtime'))
          {extra_where}
        ORDER BY w.last_name COLLATE NOCASE, w.first_name COLLATE NOCASE
    """


def active_assignment_for_worker(db: Database, worker_id: int, department_id: int | None = None) -> dict[str, Any] | None:
    extra = " AND a.worker_id=?"
    params: list[Any] = [worker_id]
    if department_id is not None:
        extra += " AND a.department_id=?"
        params.append(department_id)
    rows = db.all(active_assignment_sql(extra), tuple(params))
    return rows[0] if rows else None


class _SafeFormat(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def offboarding_message(settings: Settings, record: dict[str, Any], reason_label: str, requested_by: str) -> tuple[str, str]:
    db = Database(settings.data_dir / "personalplaner.sqlite3")
    values = get_all(db, settings)
    effective = record["effective_at"]
    try:
        effective = date.fromisoformat(effective).strftime("%d.%m.%Y")
    except ValueError:
        pass
    replacement = "Ja" if record["replacement_required"] else "Nein"
    employee_name = f"{record['first_name']} {record['last_name']}".strip()
    employee_code = str(record.get("employee_code") or "").strip()
    reason_text = str(record.get("reason_text") or "").strip()
    replacement_notes = str(record.get("replacement_notes") or "").strip()

    context = _SafeFormat(
        employee_name=employee_name,
        first_name=str(record.get("first_name") or ""),
        last_name=str(record.get("last_name") or ""),
        employee_code=employee_code,
        employee_code_line=f"Personal-/Kennnummer: {employee_code}\n" if employee_code else "",
        agency_name=str(record.get("agency_name") or ""),
        department_name=str(record.get("department_name") or ""),
        effective_date=effective,
        reason=reason_label,
        reason_text=reason_text,
        reason_text_line=f"Zusatz: {reason_text}\n" if reason_text else "",
        replacement=replacement,
        replacement_notes=replacement_notes,
        replacement_notes_line=f"Hinweis zum Ersatz: {replacement_notes}\n" if replacement_notes else "",
        requested_by=requested_by,
        company_name=str(values.get("company_name") or settings.company_name),
        company_contact=str(values.get("company_contact") or settings.company_contact),
        company_email=str(values.get("company_email") or ""),
        company_phone=str(values.get("company_phone") or ""),
        company_site=str(values.get("company_site") or ""),
    )
    subject_template = str(values.get("offboarding_subject_template") or "Abmeldung Zeitarbeit: {employee_name} zum {effective_date}")
    body_template = str(values.get("offboarding_body_template") or "")
    try:
        subject = subject_template.format_map(context).strip()
        body = body_template.format_map(context).strip()
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=500, detail=f"Abmelde-Mailvorlage ist ungültig: {exc}") from exc
    return subject, body
