from __future__ import annotations

import csv
import io
import json
from calendar import monthrange
from datetime import date, timedelta
from typing import Any

from .db import Database, utcnow


DEFAULT_ABSENCE_TYPES = [
    ("Krankheit", "sick", 10),
    ("Urlaub", "vacation", 20),
    ("Unentschuldigt", "unexcused", 30),
    ("Arzttermin / sonstige Abwesenheit", "other", 40),
]


def ensure_absence_schema(db: Database) -> None:
    with db.transaction() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS absence_types (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL UNIQUE,
                code TEXT NOT NULL UNIQUE,
                active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 100,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS absences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_id INTEGER NOT NULL REFERENCES workers(id),
                department_id INTEGER NOT NULL REFERENCES departments(id),
                absence_type_id INTEGER NOT NULL REFERENCES absence_types(id),
                starts_on TEXT NOT NULL,
                ends_on TEXT NOT NULL,
                day_part TEXT NOT NULL DEFAULT 'full' CHECK(day_part IN ('full','morning','afternoon')),
                note TEXT NOT NULL DEFAULT '',
                recorded_by INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_absences_worker_dates ON absences(worker_id,starts_on,ends_on);
            CREATE INDEX IF NOT EXISTS idx_absences_department_dates ON absences(department_id,starts_on,ends_on);

            CREATE TABLE IF NOT EXISTS monthly_absence_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_month TEXT NOT NULL,
                department_id INTEGER REFERENCES departments(id),
                scope_key TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                UNIQUE(report_month, scope_key)
            );
            CREATE INDEX IF NOT EXISTS idx_monthly_absence_reports_month ON monthly_absence_reports(report_month);
            """
        )
        count = conn.execute("SELECT COUNT(*) FROM absence_types").fetchone()[0]
        if count == 0:
            conn.executemany(
                "INSERT INTO absence_types(label,code,active,sort_order,created_at) VALUES (?,?,1,?,?)",
                [(label, code, order, utcnow()) for label, code, order in DEFAULT_ABSENCE_TYPES],
            )


def month_bounds(month: str) -> tuple[date, date]:
    try:
        year_s, month_s = month.split("-", 1)
        year, number = int(year_s), int(month_s)
        if number < 1 or number > 12:
            raise ValueError
    except (ValueError, AttributeError) as exc:
        raise ValueError("Monat muss YYYY-MM entsprechen") from exc
    last = monthrange(year, number)[1]
    return date(year, number, 1), date(year, number, last)


def working_days(start: date, end: date, day_part: str = "full") -> float:
    if end < start:
        return 0.0
    factor = 0.5 if day_part in {"morning", "afternoon"} else 1.0
    total = 0.0
    current = start
    while current <= end:
        if current.weekday() < 5:
            total += factor
        current += timedelta(days=1)
    return total


def clipped_working_days(starts_on: str, ends_on: str, month: str, day_part: str = "full") -> float:
    month_start, month_end = month_bounds(month)
    start = max(date.fromisoformat(starts_on), month_start)
    end = min(date.fromisoformat(ends_on), month_end)
    return working_days(start, end, day_part) if start <= end else 0.0


def assignment_allows_absence(db: Database, worker_id: int, department_id: int, starts_on: str, ends_on: str) -> bool:
    row = db.one(
        """SELECT id FROM assignments
           WHERE worker_id=? AND department_id=?
             AND date(assigned_from)<=date(?)
             AND (assigned_until IS NULL OR date(assigned_until)>=date(?))
           ORDER BY id DESC LIMIT 1""",
        (worker_id, department_id, ends_on, starts_on),
    )
    return bool(row)


def overlapping_absence(db: Database, worker_id: int, starts_on: str, ends_on: str, exclude_id: int | None = None) -> dict[str, Any] | None:
    sql = """SELECT a.id,t.label FROM absences a JOIN absence_types t ON t.id=a.absence_type_id
             WHERE a.worker_id=? AND date(a.starts_on)<=date(?) AND date(a.ends_on)>=date(?)"""
    params: tuple[Any, ...] = (worker_id, ends_on, starts_on)
    if exclude_id is not None:
        sql += " AND a.id!=?"
        params += (exclude_id,)
    sql += " ORDER BY a.id LIMIT 1"
    return db.one(sql, params)


def absence_rows(db: Database, *, department_id: int | None = None, month: str | None = None) -> list[dict[str, Any]]:
    where = ["1=1"]
    params: list[Any] = []
    if department_id is not None:
        where.append("a.department_id=?")
        params.append(department_id)
    if month:
        start, end = month_bounds(month)
        where.append("date(a.starts_on)<=date(?) AND date(a.ends_on)>=date(?)")
        params.extend([end.isoformat(), start.isoformat()])
    rows = db.all(
        f"""SELECT a.*,t.label AS absence_type,t.code AS absence_code,
                   w.first_name,w.last_name,w.employee_code,ag.name AS agency_name,d.name AS department_name,
                   u.display_name AS recorded_by_name
            FROM absences a
            JOIN absence_types t ON t.id=a.absence_type_id
            JOIN workers w ON w.id=a.worker_id
            JOIN agencies ag ON ag.id=w.agency_id
            JOIN departments d ON d.id=a.department_id
            LEFT JOIN users u ON u.id=a.recorded_by
            WHERE {' AND '.join(where)}
            ORDER BY date(a.starts_on) DESC,a.id DESC""",
        tuple(params),
    )
    for row in rows:
        row["working_days"] = (
            clipped_working_days(row["starts_on"], row["ends_on"], month, row["day_part"])
            if month
            else working_days(date.fromisoformat(row["starts_on"]), date.fromisoformat(row["ends_on"]), row["day_part"])
        )
    return rows


def build_monthly_report(db: Database, month: str, department_id: int | None = None) -> dict[str, Any]:
    month_start, month_end = month_bounds(month)
    rows = absence_rows(db, department_id=department_id, month=month)
    department = db.one("SELECT id,name,code FROM departments WHERE id=?", (department_id,)) if department_id else None

    by_worker: dict[int, dict[str, Any]] = {}
    by_type: dict[str, float] = {}
    total_days = 0.0
    sick_days = 0.0

    for row in rows:
        days = float(row["working_days"])
        if days <= 0:
            continue
        total_days += days
        if row["absence_code"] == "sick":
            sick_days += days
        by_type[row["absence_type"]] = by_type.get(row["absence_type"], 0.0) + days
        worker = by_worker.setdefault(
            int(row["worker_id"]),
            {
                "worker_id": int(row["worker_id"]),
                "name": f"{row['first_name']} {row['last_name']}",
                "employee_code": row.get("employee_code") or "",
                "agency_name": row.get("agency_name") or "",
                "department_name": row.get("department_name") or "",
                "total_days": 0.0,
                "sick_days": 0.0,
                "types": {},
            },
        )
        worker["total_days"] += days
        if row["absence_code"] == "sick":
            worker["sick_days"] += days
        worker["types"][row["absence_type"]] = worker["types"].get(row["absence_type"], 0.0) + days

    workers = sorted(by_worker.values(), key=lambda x: (-x["total_days"], x["name"].casefold()))
    return {
        "month": month,
        "period_start": month_start.isoformat(),
        "period_end": month_end.isoformat(),
        "department": department,
        "summary": {
            "absence_entries": len(rows),
            "affected_workers": len(workers),
            "absence_days": round(total_days, 2),
            "sick_days": round(sick_days, 2),
        },
        "by_type": [{"label": key, "days": round(value, 2)} for key, value in sorted(by_type.items())],
        "workers": workers,
        "entries": [
            {
                "id": row["id"],
                "worker_id": row["worker_id"],
                "name": f"{row['first_name']} {row['last_name']}",
                "employee_code": row.get("employee_code") or "",
                "agency_name": row.get("agency_name") or "",
                "department_name": row.get("department_name") or "",
                "absence_type": row["absence_type"],
                "absence_code": row["absence_code"],
                "starts_on": row["starts_on"],
                "ends_on": row["ends_on"],
                "day_part": row["day_part"],
                "days_in_month": round(float(row["working_days"]), 2),
            }
            for row in rows
        ],
    }


def store_monthly_report(db: Database, month: str, department_id: int | None = None) -> dict[str, Any]:
    report = build_monthly_report(db, month, department_id)
    scope_key = f"department:{department_id}" if department_id is not None else "company"
    now = utcnow()
    with db.transaction() as conn:
        conn.execute(
            """INSERT INTO monthly_absence_reports(report_month,department_id,scope_key,payload_json,generated_at)
               VALUES (?,?,?,?,?) ON CONFLICT(report_month,scope_key) DO UPDATE SET
               department_id=excluded.department_id,payload_json=excluded.payload_json,generated_at=excluded.generated_at""",
            (month, department_id, scope_key, json.dumps(report, ensure_ascii=False), now),
        )
    report["generated_at"] = now
    report["finalized"] = True
    return report


def get_stored_report(db: Database, month: str, department_id: int | None = None) -> dict[str, Any] | None:
    scope_key = f"department:{department_id}" if department_id is not None else "company"
    row = db.one("SELECT payload_json,generated_at FROM monthly_absence_reports WHERE report_month=? AND scope_key=?", (month, scope_key))
    if not row:
        return None
    try:
        report = json.loads(row["payload_json"])
    except (TypeError, json.JSONDecodeError):
        return None
    report["generated_at"] = row["generated_at"]
    report["finalized"] = True
    return report


def ensure_previous_month_reports(db: Database) -> int:
    today = date.today()
    first_this = today.replace(day=1)
    previous_last = first_this - timedelta(days=1)
    month = previous_last.strftime("%Y-%m")
    generated = 0
    if not get_stored_report(db, month, None):
        store_monthly_report(db, month, None)
        generated += 1
    for dep in db.all("SELECT id FROM departments WHERE active=1"):
        dep_id = int(dep["id"])
        if not get_stored_report(db, month, dep_id):
            store_monthly_report(db, month, dep_id)
            generated += 1
    return generated


def report_csv(report: dict[str, Any]) -> str:
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["PP Personalplaner – Abwesenheitsbericht", report["month"]])
    writer.writerow(["Bereich", (report.get("department") or {}).get("name", "Gesamtbetrieb")])
    writer.writerow([])
    writer.writerow(["Mitarbeiter", "Kennnummer", "Zeitarbeitsfirma", "Abteilung", "Abwesenheitstage", "Krankentage"])
    for worker in report.get("workers", []):
        writer.writerow([
            worker.get("name", ""), worker.get("employee_code", ""), worker.get("agency_name", ""),
            worker.get("department_name", ""), worker.get("total_days", 0), worker.get("sick_days", 0),
        ])
    writer.writerow([])
    writer.writerow(["Art", "Tage"])
    for item in report.get("by_type", []):
        writer.writerow([item.get("label", ""), item.get("days", 0)])
    return output.getvalue()
