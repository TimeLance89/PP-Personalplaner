from __future__ import annotations

import json
from datetime import date
from typing import Any, Awaitable, Callable

from fastapi import HTTPException, Request
from starlette.responses import JSONResponse

from .auth import current_user
from .db import Database
from .services import active_assignment_for_worker

ASGIApp = Callable[[dict[str, Any], Callable[..., Awaitable[dict[str, Any]]], Callable[..., Awaitable[None]]], Awaitable[None]]


def _unprocessable(detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=422)


def _parse_day(value: Any, label: str) -> date:
    try:
        return date.fromisoformat(str(value or ""))
    except ValueError as exc:
        raise ValueError(f"{label} ist ungültig") from exc


class PersonnelGuardMiddleware:
    """Additional privacy and temporal integrity checks around the personnel API."""

    def __init__(self, app: ASGIApp, db: Database):
        self.app = app
        self.db = db

    async def __call__(self, scope: dict[str, Any], receive: Callable[..., Awaitable[dict[str, Any]]], send: Callable[..., Awaitable[None]]) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method", "GET")).upper()
        path = str(scope.get("path", ""))
        request = Request(scope, receive=receive)

        # Agency contact data is administrative master data. A department leader
        # gets agency information only as part of an assigned worker/offboarding,
        # never as a global address book.
        if method == "GET" and path == "/api/agencies":
            try:
                user = current_user(self.db, request)
            except HTTPException:
                await self.app(scope, receive, send)
                return
            if user["role"] != "admin":
                response = JSONResponse([])
                await response(scope, receive, send)
                return

        if method != "POST" or path not in {"/api/assignments", "/api/offboardings", "/api/offboardings/preview"}:
            await self.app(scope, receive, send)
            return

        raw = await request.body()
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            response = _unprocessable("Ungültige Anfrage")
            await response(scope, receive, send)
            return

        try:
            if path == "/api/assignments":
                start = _parse_day(payload.get("assigned_from") or date.today().isoformat(), "Startdatum")
                end_raw = payload.get("assigned_until")
                if end_raw:
                    end = _parse_day(end_raw, "Enddatum")
                    if end < start:
                        raise ValueError("Enddatum darf nicht vor dem Startdatum liegen")
                worker_id = int(payload.get("worker_id"))
                worker = self.db.one("SELECT status FROM workers WHERE id=?", (worker_id,))
                if not worker or worker["status"] != "active":
                    raise ValueError("Nur aktive Zeitarbeiter können zugeteilt werden")
            else:
                effective = _parse_day(payload.get("effective_at"), "Abmeldedatum")
                if effective < date.today():
                    raise ValueError("Das Abmeldedatum darf nicht in der Vergangenheit liegen")
                worker_id = int(payload.get("worker_id"))
                try:
                    user = current_user(self.db, request)
                except HTTPException:
                    user = None
                if user:
                    department_id = user.get("department_id") if user["role"] == "leader" else None
                    assignment = active_assignment_for_worker(self.db, worker_id, department_id)
                    if assignment and effective < date.fromisoformat(assignment["assigned_from"]):
                        raise ValueError("Abmeldung darf nicht vor Beginn der Zuteilung liegen")
        except (TypeError, ValueError) as exc:
            response = _unprocessable(str(exc))
            await response(scope, receive, send)
            return

        sent = False

        async def replay() -> dict[str, Any]:
            nonlocal sent
            if sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent = True
            return {"type": "http.request", "body": raw, "more_body": False}

        await self.app(scope, replay, send)
