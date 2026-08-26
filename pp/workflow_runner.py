from __future__ import annotations

import asyncio

from .config import Settings
from .db import Database, utcnow
from .system_settings import get_all
from .workflow_center import ensure_workflow_schema, run_workflow_cycle


def _interval(values: dict[str, object]) -> int:
    try:
        minutes = int(values.get("automation_interval_minutes", 5) or 5)
    except (TypeError, ValueError):
        minutes = 5
    return max(1, min(1440, minutes))


def _cleanup_assignment_decisions(db: Database) -> None:
    now = utcnow()
    with db.transaction() as conn:
        # Eine bereits ausgelöste Abmeldung beendet jeden offenen Prüfvorgang für dieselbe Zuteilung.
        conn.execute(
            """UPDATE scheduled_actions SET state='cancelled',executed_at=?
               WHERE action_type='assignment_review' AND state='scheduled'
                 AND EXISTS (
                   SELECT 1 FROM offboarding_requests o
                   WHERE o.assignment_id=scheduled_actions.entity_id AND o.status!='cancelled'
                 )""",
            (now,),
        )
        conn.execute(
            """UPDATE workflow_inbox SET state='done',resolved_at=?,updated_at=?
               WHERE entity_type='assignment' AND state NOT IN ('done','dismissed')
                 AND EXISTS (
                   SELECT 1 FROM offboarding_requests o
                   WHERE o.assignment_id=workflow_inbox.entity_id AND o.status!='cancelled'
                 )""",
            (now, now),
        )
        # Wenn der vorbereitete Entscheid bereits existiert, ist die technische Ablaufwarnung redundant.
        conn.execute(
            """UPDATE workflow_inbox AS warning SET state='done',resolved_at=?,updated_at=?
               WHERE warning.item_type='assignment_end' AND warning.entity_type='assignment'
                 AND warning.state NOT IN ('done','dismissed')
                 AND EXISTS (
                   SELECT 1 FROM workflow_inbox decision
                   WHERE decision.item_type='assignment_review'
                     AND decision.entity_type='assignment'
                     AND decision.entity_id=warning.entity_id
                     AND decision.state NOT IN ('done','dismissed')
                 )""",
            (now, now),
        )


async def workflow_loop(db: Database, settings: Settings, stop: asyncio.Event) -> None:
    ensure_workflow_schema(db)
    while not stop.is_set():
        try:
            values = get_all(db, settings)
            mode = str(values.get("autonomy_mode", "manual") or "manual").lower()
            emergency_stop = bool(values.get("automation_emergency_stop", False))
            if mode != "manual" and not emergency_stop:
                _cleanup_assignment_decisions(db)
                run_workflow_cycle(db, settings, mode=mode)
                _cleanup_assignment_decisions(db)
            minutes = _interval(values)
        except Exception:
            minutes = 5
        try:
            await asyncio.wait_for(stop.wait(), timeout=minutes * 60)
        except TimeoutError:
            pass
