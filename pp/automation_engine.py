from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

from .config import Settings
from .db import Database, utcnow
from .mailer import send_mail
from .services import audit
from .system_settings import get_all


def ensure_automation_schema(db: Database) -> None:
    with db.transaction() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS automation_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trigger_type TEXT NOT NULL,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                summary_json TEXT NOT NULL DEFAULT '{}',
                error_text TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS automation_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL,
                severity TEXT NOT NULL,
                title TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                entity_type TEXT NOT NULL DEFAULT '',
                entity_id INTEGER,
                state TEXT NOT NULL DEFAULT 'open' CHECK(state IN ('open','resolved')),
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                resolved_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_automation_events_state ON automation_events(state,last_seen_at DESC);

            CREATE TABLE IF NOT EXISTS automation_mail_retry (
                offboarding_id INTEGER PRIMARY KEY REFERENCES offboarding_requests(id) ON DELETE CASCADE,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_attempt_at TEXT,
                last_error TEXT NOT NULL DEFAULT ''
            );
            """
        )


def _setting_int(values: dict[str, Any], key: str, default: int, low: int, high: int) -> int:
    try:
        value = int(values.get(key, default) or default)
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def _upsert_event(
    db: Database,
    fingerprint: str,
    category: str,
    severity: str,
    title: str,
    detail: str,
    entity_type: str = "",
    entity_id: int | None = None,
) -> None:
    now = utcnow()
    with db.transaction() as conn:
        conn.execute(
            """INSERT INTO automation_events(
                    fingerprint,category,severity,title,detail,entity_type,entity_id,state,first_seen_at,last_seen_at,resolved_at
                ) VALUES (?,?,?,?,?,?,?,'open',?,?,NULL)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    category=excluded.category,severity=excluded.severity,title=excluded.title,detail=excluded.detail,
                    entity_type=excluded.entity_type,entity_id=excluded.entity_id,state='open',
                    last_seen_at=excluded.last_seen_at,resolved_at=NULL""",
            (fingerprint, category, severity, title, detail, entity_type, entity_id, now, now),
        )


def _resolve_event(db: Database, fingerprint: str) -> None:
    db.execute(
        "UPDATE automation_events SET state='resolved',resolved_at=?,last_seen_at=? WHERE fingerprint=? AND state='open'",
        (utcnow(), utcnow(), fingerprint),
    )


def _resolve_missing(db: Database, category: str, active_fingerprints: set[str]) -> None:
    rows = db.all("SELECT fingerprint FROM automation_events WHERE category=? AND state='open'", (category,))
    for row in rows:
        if row["fingerprint"] not in active_fingerprints:
            _resolve_event(db, row["fingerprint"])


def _scan_failed_mail(db: Database) -> list[dict[str, Any]]:
    return db.all(
        """SELECT o.id,o.notification_to,o.notification_subject,o.notification_body,o.mail_error,
                  w.first_name,w.last_name,d.name AS department_name,ag.name AS agency_name
           FROM offboarding_requests o
           JOIN workers w ON w.id=o.worker_id
           JOIN departments d ON d.id=o.department_id
           JOIN agencies ag ON ag.id=o.agency_id
           WHERE o.status='mail_failed'
           ORDER BY o.id"""
    )


def _scan_upcoming_offboardings(db: Database, days: int) -> list[dict[str, Any]]:
    today = date.today()
    until = today + timedelta(days=days)
    return db.all(
        """SELECT o.id,o.effective_at,o.status,w.first_name,w.last_name,d.name AS department_name
           FROM offboarding_requests o
           JOIN workers w ON w.id=o.worker_id
           JOIN departments d ON d.id=o.department_id
           WHERE o.status!='cancelled' AND date(o.effective_at)>=date(?) AND date(o.effective_at)<=date(?)
           ORDER BY date(o.effective_at),o.id""",
        (today.isoformat(), until.isoformat()),
    )


def _scan_unassigned(db: Database) -> list[dict[str, Any]]:
    return db.all(
        """SELECT w.id,w.first_name,w.last_name,ag.name AS agency_name
           FROM workers w JOIN agencies ag ON ag.id=w.agency_id
           WHERE w.status='active' AND NOT EXISTS (
               SELECT 1 FROM assignments a
               WHERE a.worker_id=w.id
                 AND date(a.assigned_from)<=date('now','localtime')
                 AND (a.assigned_until IS NULL OR date(a.assigned_until)>=date('now','localtime'))
           )
           ORDER BY w.last_name COLLATE NOCASE,w.first_name COLLATE NOCASE"""
    )


def _scan_assignments_ending(db: Database, days: int) -> list[dict[str, Any]]:
    today = date.today()
    until = today + timedelta(days=days)
    return db.all(
        """SELECT a.id,a.assigned_until,w.first_name,w.last_name,d.name AS department_name
           FROM assignments a
           JOIN workers w ON w.id=a.worker_id
           JOIN departments d ON d.id=a.department_id
           WHERE a.assigned_until IS NOT NULL
             AND date(a.assigned_until)>=date(?) AND date(a.assigned_until)<=date(?)
           ORDER BY date(a.assigned_until),a.id""",
        (today.isoformat(), until.isoformat()),
    )


def _retry_due(row: dict[str, Any], retry: dict[str, Any] | None, after_minutes: int, max_attempts: int) -> bool:
    if retry and int(retry.get("attempts", 0) or 0) >= max_attempts:
        return False
    if not retry or not retry.get("last_attempt_at"):
        return True
    try:
        last = datetime.fromisoformat(str(retry["last_attempt_at"]))
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
    except ValueError:
        return True
    return datetime.now(UTC) - last >= timedelta(minutes=after_minutes)


def _retry_failed_mails(db: Database, settings: Settings, values: dict[str, Any], failed: list[dict[str, Any]]) -> tuple[int, int]:
    if not values.get("automation_retry_failed_mail", True):
        return 0, 0
    after_minutes = _setting_int(values, "automation_retry_after_minutes", 15, 1, 1440)
    max_attempts = _setting_int(values, "automation_retry_max_attempts", 5, 1, 50)
    sent = 0
    attempted = 0
    for row in failed:
        retry = db.one("SELECT * FROM automation_mail_retry WHERE offboarding_id=?", (row["id"],))
        if not _retry_due(row, retry, after_minutes, max_attempts):
            continue
        attempted += 1
        attempts = int(retry.get("attempts", 0) or 0) + 1 if retry else 1
        try:
            send_mail(settings, row["notification_to"], row["notification_subject"], row["notification_body"])
        except Exception as exc:
            with db.transaction() as conn:
                conn.execute(
                    """INSERT INTO automation_mail_retry(offboarding_id,attempts,last_attempt_at,last_error)
                       VALUES (?,?,?,?)
                       ON CONFLICT(offboarding_id) DO UPDATE SET attempts=excluded.attempts,
                       last_attempt_at=excluded.last_attempt_at,last_error=excluded.last_error""",
                    (row["id"], attempts, utcnow(), str(exc)[:1000]),
                )
                conn.execute("UPDATE offboarding_requests SET mail_error=? WHERE id=?", (str(exc)[:1000], row["id"]))
            continue
        sent += 1
        with db.transaction() as conn:
            conn.execute(
                "UPDATE offboarding_requests SET status='sent',mail_error='',sent_at=? WHERE id=?",
                (utcnow(), row["id"]),
            )
            conn.execute("DELETE FROM automation_mail_retry WHERE offboarding_id=?", (row["id"],))
        _resolve_event(db, f"mail_failed:{row['id']}")
        audit(db, None, "automation_mail_retried", "offboarding", int(row["id"]), {"attempt": attempts})
    return attempted, sent


def _housekeeping(db: Database, values: dict[str, Any]) -> dict[str, int]:
    result = {"expired_sessions": 0, "audit_rows": 0}
    if not values.get("automation_housekeeping", False):
        return result
    with db.transaction() as conn:
        cur = conn.execute("DELETE FROM sessions WHERE datetime(expires_at)<=datetime('now')")
        result["expired_sessions"] = max(0, int(cur.rowcount or 0))
        retention = _setting_int(values, "audit_retention_days", 3650, 30, 36500)
        if values.get("audit_enabled", True):
            cur = conn.execute("DELETE FROM audit_log WHERE datetime(created_at)<datetime('now', ?)", (f"-{retention} days",))
            result["audit_rows"] = max(0, int(cur.rowcount or 0))
    return result


def run_once(db: Database, settings: Settings, *, trigger: str = "scheduler") -> dict[str, Any]:
    ensure_automation_schema(db)
    values = get_all(db, settings)
    mode = str(values.get("autonomy_mode", "manual") or "manual").lower()
    emergency_stop = bool(values.get("automation_emergency_stop", False))
    started = utcnow()
    run_id = db.execute(
        "INSERT INTO automation_runs(trigger_type,mode,status,started_at,summary_json) VALUES (?,?, 'running', ?, '{}')",
        (trigger, mode, started),
    )

    if emergency_stop or mode == "manual":
        summary = {"mode": mode, "skipped": True, "reason": "emergency_stop" if emergency_stop else "manual"}
        db.execute(
            "UPDATE automation_runs SET status='skipped',finished_at=?,summary_json=? WHERE id=?",
            (utcnow(), json.dumps(summary, ensure_ascii=False), run_id),
        )
        return summary

    try:
        failed = _scan_failed_mail(db)
        upcoming_days = _setting_int(values, "automation_upcoming_days", 7, 1, 60)
        ending_days = _setting_int(values, "automation_assignment_end_days", 3, 1, 60)
        upcoming = _scan_upcoming_offboardings(db, upcoming_days) if values.get("automation_watch_upcoming", True) else []
        unassigned = _scan_unassigned(db) if values.get("automation_watch_unassigned", True) else []
        ending = _scan_assignments_ending(db, ending_days) if values.get("automation_watch_assignment_end", True) else []

        active_failed: set[str] = set()
        for row in failed:
            fingerprint = f"mail_failed:{row['id']}"
            active_failed.add(fingerprint)
            _upsert_event(
                db, fingerprint, "mail", "danger", "Abmelde-Mail fehlgeschlagen",
                f"{row['first_name']} {row['last_name']} · {row['agency_name']} · {row.get('mail_error') or 'Versandfehler'}",
                "offboarding", int(row["id"]),
            )
        _resolve_missing(db, "mail", active_failed)

        active_upcoming: set[str] = set()
        for row in upcoming:
            fingerprint = f"upcoming_offboarding:{row['id']}"
            active_upcoming.add(fingerprint)
            _upsert_event(
                db, fingerprint, "upcoming", "warning", "Abmeldung wird zeitnah wirksam",
                f"{row['first_name']} {row['last_name']} · {row['department_name']} · {row['effective_at']}",
                "offboarding", int(row["id"]),
            )
        _resolve_missing(db, "upcoming", active_upcoming)

        active_unassigned: set[str] = set()
        for row in unassigned:
            fingerprint = f"unassigned:{row['id']}"
            active_unassigned.add(fingerprint)
            _upsert_event(
                db, fingerprint, "unassigned", "warning", "Aktive Kraft ohne Zuteilung",
                f"{row['first_name']} {row['last_name']} · {row['agency_name']}",
                "worker", int(row["id"]),
            )
        _resolve_missing(db, "unassigned", active_unassigned)

        active_ending: set[str] = set()
        for row in ending:
            fingerprint = f"assignment_end:{row['id']}"
            active_ending.add(fingerprint)
            _upsert_event(
                db, fingerprint, "assignment_end", "info", "Einsatz endet zeitnah",
                f"{row['first_name']} {row['last_name']} · {row['department_name']} · {row['assigned_until']}",
                "assignment", int(row["id"]),
            )
        _resolve_missing(db, "assignment_end", active_ending)

        attempted = sent = 0
        if mode in {"rules", "autopilot"}:
            attempted, sent = _retry_failed_mails(db, settings, values, failed)
        housekeeping = _housekeeping(db, values) if mode == "autopilot" else {"expired_sessions": 0, "audit_rows": 0}

        summary = {
            "mode": mode,
            "mail_failed": len(failed),
            "upcoming_offboardings": len(upcoming),
            "unassigned_workers": len(unassigned),
            "assignments_ending": len(ending),
            "mail_retry_attempted": attempted,
            "mail_retry_sent": sent,
            "housekeeping": housekeeping,
        }
        db.execute(
            "UPDATE automation_runs SET status='success',finished_at=?,summary_json=? WHERE id=?",
            (utcnow(), json.dumps(summary, ensure_ascii=False), run_id),
        )
        return summary
    except Exception as exc:
        db.execute(
            "UPDATE automation_runs SET status='failed',finished_at=?,error_text=? WHERE id=?",
            (utcnow(), str(exc)[:2000], run_id),
        )
        raise


async def automation_loop(db: Database, settings: Settings, stop: asyncio.Event) -> None:
    ensure_automation_schema(db)
    while not stop.is_set():
        try:
            values = get_all(db, settings)
            mode = str(values.get("autonomy_mode", "manual") or "manual").lower()
            if mode != "manual" and not values.get("automation_emergency_stop", False):
                run_once(db, settings, trigger="scheduler")
            minutes = _setting_int(values, "automation_interval_minutes", 5, 1, 1440)
        except Exception:
            minutes = 5
        try:
            await asyncio.wait_for(stop.wait(), timeout=minutes * 60)
        except TimeoutError:
            pass
