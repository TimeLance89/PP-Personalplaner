from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .config import Settings
from .db import Database, utcnow
from .mailer import send_mail
from .system_settings import get_all

BERLIN = ZoneInfo("Europe/Berlin")


def ensure_workflow_schema(db: Database) -> None:
    with db.transaction() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS workflow_inbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL UNIQUE,
                item_type TEXT NOT NULL,
                priority TEXT NOT NULL DEFAULT 'info' CHECK(priority IN ('info','warning','danger')),
                title TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                department_id INTEGER REFERENCES departments(id),
                owner_user_id INTEGER REFERENCES users(id),
                entity_type TEXT NOT NULL DEFAULT '',
                entity_id INTEGER,
                state TEXT NOT NULL DEFAULT 'open' CHECK(state IN ('open','pp_handling','needs_decision','done','dismissed')),
                due_at TEXT,
                action_hint TEXT NOT NULL DEFAULT '',
                automation_owned INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                resolved_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_workflow_inbox_scope ON workflow_inbox(state,department_id,owner_user_id,updated_at DESC);

            CREATE TABLE IF NOT EXISTS scheduled_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL UNIQUE,
                action_type TEXT NOT NULL,
                entity_type TEXT NOT NULL DEFAULT '',
                entity_id INTEGER,
                department_id INTEGER REFERENCES departments(id),
                scheduled_for TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                state TEXT NOT NULL DEFAULT 'scheduled' CHECK(state IN ('scheduled','completed','cancelled','failed')),
                created_at TEXT NOT NULL,
                executed_at TEXT,
                error_text TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_scheduled_actions_due ON scheduled_actions(state,scheduled_for);

            CREATE TABLE IF NOT EXISTS daily_briefings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                briefing_date TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                summary_json TEXT NOT NULL DEFAULT '{}',
                emailed INTEGER NOT NULL DEFAULT 0,
                email_error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(user_id,briefing_date)
            );
            CREATE INDEX IF NOT EXISTS idx_daily_briefings_user ON daily_briefings(user_id,briefing_date DESC);

            CREATE TABLE IF NOT EXISTS user_notifications (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                email TEXT NOT NULL DEFAULT '',
                briefing_email_enabled INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            """
        )


def _int(values: dict[str, Any], key: str, default: int, low: int, high: int) -> int:
    try:
        value = int(values.get(key, default) or default)
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def _json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        decoded = json.loads(value)
        return decoded if isinstance(decoded, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _upsert_inbox(
    db: Database,
    *,
    fingerprint: str,
    item_type: str,
    priority: str,
    title: str,
    detail: str,
    department_id: int | None = None,
    owner_user_id: int | None = None,
    entity_type: str = "",
    entity_id: int | None = None,
    state: str = "open",
    due_at: str | None = None,
    action_hint: str = "",
    automation_owned: bool = False,
) -> int:
    now = utcnow()
    with db.transaction() as conn:
        conn.execute(
            """INSERT INTO workflow_inbox(
                   fingerprint,item_type,priority,title,detail,department_id,owner_user_id,entity_type,entity_id,
                   state,due_at,action_hint,automation_owned,created_at,updated_at,resolved_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)
               ON CONFLICT(fingerprint) DO UPDATE SET
                   item_type=excluded.item_type,priority=excluded.priority,title=excluded.title,detail=excluded.detail,
                   department_id=excluded.department_id,owner_user_id=excluded.owner_user_id,
                   entity_type=excluded.entity_type,entity_id=excluded.entity_id,
                   state=CASE WHEN workflow_inbox.state IN ('done','dismissed') THEN workflow_inbox.state ELSE excluded.state END,
                   due_at=excluded.due_at,action_hint=excluded.action_hint,automation_owned=excluded.automation_owned,
                   updated_at=excluded.updated_at""",
            (
                fingerprint, item_type, priority, title, detail, department_id, owner_user_id, entity_type, entity_id,
                state, due_at, action_hint, int(automation_owned), now, now,
            ),
        )
        row = conn.execute("SELECT id FROM workflow_inbox WHERE fingerprint=?", (fingerprint,)).fetchone()
        return int(row[0])


def _resolve_inbox(db: Database, fingerprint: str) -> None:
    db.execute(
        """UPDATE workflow_inbox SET state='done',resolved_at=?,updated_at=?
           WHERE fingerprint=? AND state NOT IN ('done','dismissed')""",
        (utcnow(), utcnow(), fingerprint),
    )


def _department_for_event(db: Database, entity_type: str, entity_id: int | None) -> int | None:
    if not entity_id:
        return None
    if entity_type == "offboarding":
        row = db.one("SELECT department_id FROM offboarding_requests WHERE id=?", (entity_id,))
        return int(row["department_id"]) if row else None
    if entity_type == "assignment":
        row = db.one("SELECT department_id FROM assignments WHERE id=?", (entity_id,))
        return int(row["department_id"]) if row else None
    return None


def sync_automation_events(db: Database, mode: str) -> int:
    ensure_workflow_schema(db)
    rows = db.all("SELECT * FROM automation_events ORDER BY id")
    active = 0
    for event in rows:
        fingerprint = f"automation:{event['fingerprint']}"
        if event["state"] != "open":
            _resolve_inbox(db, fingerprint)
            continue
        active += 1
        category = str(event["category"])
        department_id = _department_for_event(db, str(event.get("entity_type") or ""), event.get("entity_id"))
        if category == "mail" and mode in {"rules", "autopilot"}:
            state = "pp_handling"
            action_hint = "mail_retry"
            owned = True
        elif category in {"unassigned", "assignment_end"}:
            state = "needs_decision"
            action_hint = "assignment_review" if category == "assignment_end" else "assign_worker"
            owned = False
        else:
            state = "open"
            action_hint = "watch"
            owned = True
        _upsert_inbox(
            db,
            fingerprint=fingerprint,
            item_type=category,
            priority=str(event["severity"]),
            title=str(event["title"]),
            detail=str(event["detail"]),
            department_id=department_id,
            entity_type=str(event.get("entity_type") or ""),
            entity_id=int(event["entity_id"]) if event.get("entity_id") is not None else None,
            state=state,
            action_hint=action_hint,
            automation_owned=owned,
        )
    return active


def plan_assignment_reviews(db: Database, values: dict[str, Any], *, today: date | None = None) -> int:
    ensure_workflow_schema(db)
    if not values.get("workflow_assignment_review_enabled", True):
        return 0
    today = today or datetime.now(BERLIN).date()
    lead_days = _int(values, "workflow_assignment_review_days", 7, 1, 60)
    rows = db.all(
        """SELECT a.id,a.worker_id,a.department_id,a.assigned_until,w.first_name,w.last_name,d.name AS department_name
           FROM assignments a
           JOIN workers w ON w.id=a.worker_id
           JOIN departments d ON d.id=a.department_id
           WHERE a.assigned_until IS NOT NULL AND date(a.assigned_until)>=date(?)""",
        (today.isoformat(),),
    )
    created = 0
    for row in rows:
        try:
            end_date = date.fromisoformat(str(row["assigned_until"])[:10])
        except ValueError:
            continue
        scheduled = max(today, end_date - timedelta(days=lead_days))
        fingerprint = f"assignment_review:{row['id']}:{end_date.isoformat()}"
        payload = {
            "worker_id": int(row["worker_id"]),
            "worker_name": f"{row['first_name']} {row['last_name']}",
            "department_name": row["department_name"],
            "assigned_until": end_date.isoformat(),
        }
        with db.transaction() as conn:
            conn.execute(
                """UPDATE scheduled_actions SET state='cancelled'
                   WHERE action_type='assignment_review' AND entity_type='assignment' AND entity_id=?
                     AND fingerprint<>? AND state='scheduled'""",
                (row["id"], fingerprint),
            )
            cur = conn.execute(
                """INSERT OR IGNORE INTO scheduled_actions(
                       fingerprint,action_type,entity_type,entity_id,department_id,scheduled_for,payload_json,state,created_at
                   ) VALUES (?,?,?,?,?,?,?,'scheduled',?)""",
                (
                    fingerprint, "assignment_review", "assignment", row["id"], row["department_id"],
                    scheduled.isoformat(), json.dumps(payload, ensure_ascii=False), utcnow(),
                ),
            )
            if cur.rowcount:
                created += 1
    return created


def execute_due_actions(db: Database, *, today: date | None = None) -> int:
    ensure_workflow_schema(db)
    today = today or datetime.now(BERLIN).date()
    rows = db.all(
        "SELECT * FROM scheduled_actions WHERE state='scheduled' AND date(scheduled_for)<=date(?) ORDER BY scheduled_for,id",
        (today.isoformat(),),
    )
    completed = 0
    for row in rows:
        try:
            payload = _json(row.get("payload_json"))
            if row["action_type"] == "assignment_review":
                assignment = db.one(
                    """SELECT a.*,w.first_name,w.last_name,d.name AS department_name
                       FROM assignments a JOIN workers w ON w.id=a.worker_id JOIN departments d ON d.id=a.department_id
                       WHERE a.id=?""",
                    (row["entity_id"],),
                )
                if not assignment or not assignment.get("assigned_until"):
                    db.execute("UPDATE scheduled_actions SET state='cancelled',executed_at=? WHERE id=?", (utcnow(), row["id"]))
                    continue
                detail = (
                    f"{assignment['first_name']} {assignment['last_name']} · {assignment['department_name']} · "
                    f"Einsatzende {assignment['assigned_until']}. PP hat den Vorgang vorbereitet."
                )
                _upsert_inbox(
                    db,
                    fingerprint=f"decision:{row['fingerprint']}",
                    item_type="assignment_review",
                    priority="warning",
                    title="Entscheidung zum auslaufenden Einsatz",
                    detail=detail,
                    department_id=int(assignment["department_id"]),
                    entity_type="assignment",
                    entity_id=int(assignment["id"]),
                    state="needs_decision",
                    due_at=str(assignment["assigned_until"]),
                    action_hint="assignment_review",
                    automation_owned=False,
                )
            db.execute("UPDATE scheduled_actions SET state='completed',executed_at=?,error_text='' WHERE id=?", (utcnow(), row["id"]))
            completed += 1
        except Exception as exc:
            db.execute(
                "UPDATE scheduled_actions SET state='failed',executed_at=?,error_text=? WHERE id=?",
                (utcnow(), str(exc)[:1000], row["id"]),
            )
    return completed


def _scope_sql(user: dict[str, Any]) -> tuple[str, tuple[Any, ...]]:
    if user["role"] == "admin":
        return "", ()
    department_id = user.get("department_id")
    return " AND department_id=?", (department_id,) if department_id else (-1,)


def inbox_for_user(db: Database, user: dict[str, Any], *, include_done: bool = False, limit: int = 100) -> list[dict[str, Any]]:
    ensure_workflow_schema(db)
    state_clause = "" if include_done else " AND i.state NOT IN ('done','dismissed')"
    scope, params = _scope_sql(user)
    rows = db.all(
        f"""SELECT i.*,d.name AS department_name
            FROM workflow_inbox i LEFT JOIN departments d ON d.id=i.department_id
            WHERE 1=1 {state_clause} {scope.replace('department_id','i.department_id')}
            ORDER BY CASE i.state WHEN 'needs_decision' THEN 0 WHEN 'pp_handling' THEN 1 ELSE 2 END,
                     CASE i.priority WHEN 'danger' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                     COALESCE(i.due_at,'9999-12-31'),i.updated_at DESC LIMIT ?""",
        (*params, max(1, min(500, limit))),
    )
    for row in rows:
        if row["entity_type"] == "assignment" and row.get("entity_id"):
            assignment = db.one("SELECT worker_id,assigned_until FROM assignments WHERE id=?", (row["entity_id"],))
            if assignment:
                row["worker_id"] = assignment["worker_id"]
                row["assigned_until"] = assignment["assigned_until"]
        elif row["entity_type"] == "worker" and row.get("entity_id"):
            row["worker_id"] = row["entity_id"]
    return rows


def _briefing_summary(db: Database, user: dict[str, Any], values: dict[str, Any], briefing_date: date) -> dict[str, Any]:
    days = _int(values, "briefing_days_ahead", 7, 1, 30)
    until = briefing_date + timedelta(days=days)
    if user["role"] == "admin":
        active = db.one(
            """SELECT COUNT(DISTINCT a.worker_id) AS n FROM assignments a JOIN workers w ON w.id=a.worker_id
               WHERE w.status='active' AND date(a.assigned_from)<=date(?) AND (a.assigned_until IS NULL OR date(a.assigned_until)>=date(?))""",
            (briefing_date.isoformat(), briefing_date.isoformat()),
        )["n"]
        unassigned = db.one(
            """SELECT COUNT(*) AS n FROM workers w WHERE w.status='active' AND NOT EXISTS(
                 SELECT 1 FROM assignments a WHERE a.worker_id=w.id AND date(a.assigned_from)<=date(?)
                 AND (a.assigned_until IS NULL OR date(a.assigned_until)>=date(?)))""",
            (briefing_date.isoformat(), briefing_date.isoformat()),
        )["n"]
        upcoming = db.one(
            "SELECT COUNT(*) AS n FROM offboarding_requests WHERE status!='cancelled' AND date(effective_at)>=date(?) AND date(effective_at)<=date(?)",
            (briefing_date.isoformat(), until.isoformat()),
        )["n"]
        failed = db.one("SELECT COUNT(*) AS n FROM offboarding_requests WHERE status='mail_failed'")["n"]
        decisions = db.one("SELECT COUNT(*) AS n FROM workflow_inbox WHERE state='needs_decision'")["n"]
        handling = db.one("SELECT COUNT(*) AS n FROM workflow_inbox WHERE state='pp_handling'")["n"]
    else:
        dep = int(user.get("department_id") or -1)
        active = db.one(
            """SELECT COUNT(DISTINCT a.worker_id) AS n FROM assignments a JOIN workers w ON w.id=a.worker_id
               WHERE w.status='active' AND a.department_id=? AND date(a.assigned_from)<=date(?)
               AND (a.assigned_until IS NULL OR date(a.assigned_until)>=date(?))""",
            (dep, briefing_date.isoformat(), briefing_date.isoformat()),
        )["n"]
        unassigned = 0
        upcoming = db.one(
            """SELECT COUNT(*) AS n FROM offboarding_requests WHERE department_id=? AND status!='cancelled'
               AND date(effective_at)>=date(?) AND date(effective_at)<=date(?)""",
            (dep, briefing_date.isoformat(), until.isoformat()),
        )["n"]
        failed = db.one("SELECT COUNT(*) AS n FROM offboarding_requests WHERE department_id=? AND status='mail_failed'", (dep,))["n"]
        decisions = db.one("SELECT COUNT(*) AS n FROM workflow_inbox WHERE department_id=? AND state='needs_decision'", (dep,))["n"]
        handling = db.one("SELECT COUNT(*) AS n FROM workflow_inbox WHERE department_id=? AND state='pp_handling'", (dep,))["n"]
    return {
        "active_workers": int(active or 0),
        "unassigned_workers": int(unassigned or 0),
        "upcoming_offboardings": int(upcoming or 0),
        "failed_mails": int(failed or 0),
        "decisions": int(decisions or 0),
        "pp_handling": int(handling or 0),
        "days_ahead": days,
    }


def generate_briefing_for_user(
    db: Database,
    settings: Settings,
    user: dict[str, Any],
    *,
    briefing_date: date | None = None,
    allow_email: bool = True,
) -> dict[str, Any]:
    ensure_workflow_schema(db)
    values = get_all(db, settings)
    briefing_date = briefing_date or datetime.now(BERLIN).date()
    summary = _briefing_summary(db, user, values, briefing_date)
    scope_name = "Gesamtbetrieb" if user["role"] == "admin" else str(user.get("department_name") or "Ihre Abteilung")
    lines = [
        f"Guten Morgen {user['display_name']},",
        "",
        f"PP-Briefing für {scope_name} · {briefing_date.strftime('%d.%m.%Y')}",
        "",
        f"• Im Einsatz: {summary['active_workers']}",
        f"• Entscheidungen offen: {summary['decisions']}",
        f"• PP kümmert sich gerade um: {summary['pp_handling']}",
        f"• Abmeldungen in den nächsten {summary['days_ahead']} Tagen: {summary['upcoming_offboardings']}",
        f"• Fehlgeschlagene Abmelde-Mails: {summary['failed_mails']}",
    ]
    if user["role"] == "admin":
        lines.append(f"• Aktive Kräfte ohne Zuteilung: {summary['unassigned_workers']}")
    if summary["decisions"]:
        lines.extend(["", "Es liegen Entscheidungen in Ihrer PP-Inbox bereit."])
    elif summary["failed_mails"] or summary["pp_handling"]:
        lines.extend(["", "PP bearbeitet die offenen Routinevorgänge nach den freigegebenen Regeln."])
    else:
        lines.extend(["", "Aktuell besteht kein akuter Handlungsbedarf."])
    body = "\n".join(lines)
    title = f"Tagesbriefing · {briefing_date.strftime('%d.%m.%Y')}"

    with db.transaction() as conn:
        conn.execute(
            """INSERT INTO daily_briefings(user_id,briefing_date,title,body,summary_json,emailed,email_error,created_at)
               VALUES (?,?,?,?,?,0,'',?)
               ON CONFLICT(user_id,briefing_date) DO UPDATE SET
                 title=excluded.title,body=excluded.body,summary_json=excluded.summary_json""",
            (user["id"], briefing_date.isoformat(), title, body, json.dumps(summary, ensure_ascii=False), utcnow()),
        )
    row = db.one("SELECT * FROM daily_briefings WHERE user_id=? AND briefing_date=?", (user["id"], briefing_date.isoformat())) or {}

    mode = str(values.get("autonomy_mode", "manual") or "manual")
    email_allowed_by_mode = mode in {"rules", "autopilot"}
    notification = db.one("SELECT * FROM user_notifications WHERE user_id=?", (user["id"],))
    should_email = (
        allow_email
        and email_allowed_by_mode
        and bool(values.get("briefing_email_enabled", False))
        and bool(notification and notification.get("briefing_email_enabled"))
        and bool(notification and str(notification.get("email") or "").strip())
        and not bool(row.get("emailed"))
    )
    if should_email:
        try:
            send_mail(settings, str(notification["email"]).strip(), f"PP – {title}", body)
            db.execute("UPDATE daily_briefings SET emailed=1,email_error='' WHERE id=?", (row["id"],))
        except Exception as exc:
            db.execute("UPDATE daily_briefings SET email_error=? WHERE id=?", (str(exc)[:1000], row["id"]))
    final = db.one("SELECT * FROM daily_briefings WHERE id=?", (row["id"],)) or row
    final["summary"] = _json(final.pop("summary_json", "{}"))
    return final


def generate_due_briefings(
    db: Database,
    settings: Settings,
    values: dict[str, Any],
    *,
    now: datetime | None = None,
) -> tuple[int, int]:
    ensure_workflow_schema(db)
    if not values.get("briefing_enabled", True):
        return 0, 0
    now = now or datetime.now(BERLIN)
    if now.tzinfo is None:
        now = now.replace(tzinfo=BERLIN)
    hour = _int(values, "briefing_hour", 6, 0, 23)
    if now.hour < hour:
        return 0, 0
    users = db.all(
        """SELECT u.id,u.display_name,u.role,u.department_id,d.name AS department_name
           FROM users u LEFT JOIN departments d ON d.id=u.department_id WHERE u.active=1"""
    )
    created = emailed = 0
    for user in users:
        existing = db.one("SELECT id,emailed FROM daily_briefings WHERE user_id=? AND briefing_date=?", (user["id"], now.date().isoformat()))
        if existing:
            continue
        briefing = generate_briefing_for_user(db, settings, user, briefing_date=now.date(), allow_email=True)
        created += 1
        emailed += int(bool(briefing.get("emailed")))
    return created, emailed


def run_workflow_cycle(
    db: Database,
    settings: Settings,
    *,
    mode: str,
    today: date | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    ensure_workflow_schema(db)
    values = get_all(db, settings)
    scheduled = plan_assignment_reviews(db, values, today=today)
    executed = execute_due_actions(db, today=today)
    synced = sync_automation_events(db, mode)
    briefings, emailed = generate_due_briefings(db, settings, values, now=now)
    open_items = db.one("SELECT COUNT(*) AS n FROM workflow_inbox WHERE state NOT IN ('done','dismissed')")["n"]
    decisions = db.one("SELECT COUNT(*) AS n FROM workflow_inbox WHERE state='needs_decision'")["n"]
    handling = db.one("SELECT COUNT(*) AS n FROM workflow_inbox WHERE state='pp_handling'")["n"]
    return {
        "scheduled_actions_created": scheduled,
        "scheduled_actions_executed": executed,
        "automation_events_synced": synced,
        "briefings_created": briefings,
        "briefings_emailed": emailed,
        "inbox_open": int(open_items or 0),
        "inbox_decisions": int(decisions or 0),
        "inbox_pp_handling": int(handling or 0),
    }
