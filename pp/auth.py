from __future__ import annotations

import hashlib
import secrets
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException, Request, status

from .db import Database, utcnow

SESSION_COOKIE = "pp_session"
PASSWORDS = PasswordHasher()
_LOGIN_ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)


def hash_password(password: str) -> str:
    if len(password) < 10:
        raise ValueError("Das Passwort muss mindestens 10 Zeichen lang sein.")
    return PASSWORDS.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return PASSWORDS.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def rate_limit_login(ip: str, *, max_attempts: int = 8, window_seconds: int = 900) -> None:
    now = time.monotonic()
    bucket = _LOGIN_ATTEMPTS[ip]
    while bucket and now - bucket[0] > window_seconds:
        bucket.popleft()
    if len(bucket) >= max_attempts:
        raise HTTPException(status_code=429, detail="Zu viele Anmeldeversuche. Bitte später erneut versuchen.")
    bucket.append(now)


def clear_login_attempts(ip: str) -> None:
    _LOGIN_ATTEMPTS.pop(ip, None)


def create_session(db: Database, user_id: int, hours: int, user_agent: str, ip: str) -> tuple[str, str]:
    raw = secrets.token_urlsafe(36)
    csrf = secrets.token_urlsafe(24)
    now = datetime.now(UTC)
    expires = now + timedelta(hours=hours)
    db.execute(
        "INSERT INTO sessions(token_hash,csrf_token,user_id,expires_at,created_at,last_seen_at,user_agent,ip_address) VALUES (?,?,?,?,?,?,?,?)",
        (token_hash(raw), csrf, user_id, expires.replace(microsecond=0).isoformat(), utcnow(), utcnow(), user_agent[:300], ip[:80]),
    )
    return raw, csrf


def delete_session(db: Database, raw_token: str) -> None:
    if raw_token:
        db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(raw_token),))


def current_user(db: Database, request: Request) -> dict[str, Any]:
    raw = request.cookies.get(SESSION_COOKIE, "")
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nicht angemeldet")
    row = db.one(
        """SELECT u.*, s.csrf_token, s.expires_at, s.id AS session_id
           FROM sessions s JOIN users u ON u.id=s.user_id
           WHERE s.token_hash=? AND u.active=1""",
        (token_hash(raw),),
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sitzung ungültig")
    try:
        expires = datetime.fromisoformat(row["expires_at"])
    except ValueError:
        expires = datetime.min.replace(tzinfo=UTC)
    if expires <= datetime.now(UTC):
        delete_session(db, raw)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sitzung abgelaufen")
    db.execute("UPDATE sessions SET last_seen_at=? WHERE id=?", (utcnow(), row["session_id"]))
    return row


def require_csrf(request: Request, user: dict[str, Any]) -> None:
    supplied = request.headers.get("X-CSRF-Token", "")
    if not supplied or not secrets.compare_digest(supplied, str(user["csrf_token"])):
        raise HTTPException(status_code=403, detail="CSRF-Prüfung fehlgeschlagen")


def require_admin(user: dict[str, Any]) -> None:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Administratorrechte erforderlich")


def require_department_access(user: dict[str, Any], department_id: int) -> None:
    if user["role"] == "admin":
        return
    if not user.get("department_id") or int(user["department_id"]) != int(department_id):
        raise HTTPException(status_code=403, detail="Kein Zugriff auf diese Abteilung")
