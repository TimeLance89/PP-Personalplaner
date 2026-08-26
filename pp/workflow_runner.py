from __future__ import annotations

import asyncio

from .config import Settings
from .db import Database
from .system_settings import get_all
from .workflow_center import ensure_workflow_schema, run_workflow_cycle


def _interval(values: dict[str, object]) -> int:
    try:
        minutes = int(values.get("automation_interval_minutes", 5) or 5)
    except (TypeError, ValueError):
        minutes = 5
    return max(1, min(1440, minutes))


async def workflow_loop(db: Database, settings: Settings, stop: asyncio.Event) -> None:
    ensure_workflow_schema(db)
    while not stop.is_set():
        try:
            values = get_all(db, settings)
            mode = str(values.get("autonomy_mode", "manual") or "manual").lower()
            emergency_stop = bool(values.get("automation_emergency_stop", False))
            if mode != "manual" and not emergency_stop:
                run_workflow_cycle(db, settings, mode=mode)
            minutes = _interval(values)
        except Exception:
            minutes = 5
        try:
            await asyncio.wait_for(stop.wait(), timeout=minutes * 60)
        except TimeoutError:
            pass
