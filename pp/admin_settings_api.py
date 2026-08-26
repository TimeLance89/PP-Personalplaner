from __future__ import annotations

import json
import secrets
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request as UrlRequest, urlopen

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from .auth import current_user, require_admin, require_csrf
from .config import Settings
from .db import Database
from .mailer import send_mail
from .services import audit
from .system_settings import (
    SECRET_KEYS,
    clear_values,
    get_all,
    mail_ready,
    public_payload,
    set_values,
)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
LOGIN_BASE = "https://login.microsoftonline.com"
M365_SCOPES = "openid profile email offline_access https://graph.microsoft.com/User.Read https://graph.microsoft.com/Mail.Send"


class SettingsBody(BaseModel):
    values: dict[str, Any]


class TestMailBody(BaseModel):
    email: str = Field(min_length=3, max_length=240)


def _json_request(url: str, *, method: str = "GET", data: dict[str, Any] | None = None, token: str = "") -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    body = None
    if data is not None:
        body = urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = UrlRequest(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=25) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8"))
            text = detail.get("error_description") or detail.get("error", {}).get("message") or str(detail)
        except Exception:
            text = str(exc)
        raise HTTPException(status_code=502, detail=f"Microsoft-Verbindung fehlgeschlagen: {text[:500]}") from exc
    except URLError as exc:
        raise HTTPException(status_code=502, detail=f"Microsoft ist nicht erreichbar: {exc.reason}") from exc


def _redirect_uri(values: dict[str, Any]) -> str:
    base = str(values.get("m365_public_base_url", "")).strip().rstrip("/")
    if not base:
        raise HTTPException(status_code=422, detail="Für Microsoft 365 muss zuerst die öffentliche PP-Basis-URL hinterlegt werden.")
    if not (base.startswith("https://") or base.startswith("http://localhost")):
        raise HTTPException(status_code=422, detail="Die Microsoft-365-Basis-URL muss HTTPS verwenden (Ausnahme: localhost).")
    return f"{base}/api/admin/microsoft/callback"


def build_admin_settings_router(db: Database, settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api")

    def admin(request: Request, mutate: bool = False) -> dict[str, Any]:
        user = current_user(db, request)
        require_admin(user)
        if mutate:
            require_csrf(request, user)
        return user

    @router.get("/preferences")
    def preferences(request: Request) -> dict[str, Any]:
        current_user(db, request)
        values = get_all(db, settings)
        ready, provider_name = mail_ready(db, settings)
        return {
            "company_name": values.get("company_name", settings.company_name),
            "mail_ready": ready,
            "mail_provider_name": provider_name,
            "offboarding_default_replacement": bool(values.get("offboarding_default_replacement")),
            "offboarding_default_days": max(0, min(365, int(values.get("offboarding_default_days", 0) or 0))),
            "offboarding_require_reason_text": bool(values.get("offboarding_require_reason_text")),
            "offboarding_allow_same_day": bool(values.get("offboarding_allow_same_day", True)),
        }

    @router.get("/admin/settings")
    def get_settings(request: Request) -> dict[str, Any]:
        admin(request)
        payload = public_payload(db, settings)
        values = get_all(db, settings)
        try:
            payload["m365_redirect_uri"] = _redirect_uri(values)
        except HTTPException:
            payload["m365_redirect_uri"] = "<öffentliche-PP-URL>/api/admin/microsoft/callback"
        ready, provider_name = mail_ready(db, settings)
        payload["mail_ready"] = ready
        payload["mail_provider_name"] = provider_name
        return payload

    @router.put("/admin/settings")
    def update_settings(body: SettingsBody, request: Request) -> dict[str, Any]:
        user = admin(request, mutate=True)
        values = dict(body.values)
        if values.get("mail_provider") not in (None, "smtp", "microsoft365"):
            raise HTTPException(status_code=422, detail="Ungültiger Mailanbieter")
        if "smtp_port" in values:
            try:
                port = int(values["smtp_port"])
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail="SMTP-Port ungültig") from exc
            if not 1 <= port <= 65535:
                raise HTTPException(status_code=422, detail="SMTP-Port ungültig")
            values["smtp_port"] = port
        for key in ("offboarding_default_days", "session_hours_override", "audit_retention_days"):
            if key in values:
                try:
                    values[key] = max(0, int(values[key]))
                except (TypeError, ValueError) as exc:
                    raise HTTPException(status_code=422, detail=f"Ungültiger Zahlenwert: {key}") from exc
        # Leere Secret-Felder bedeuten "bestehendes Geheimnis behalten".
        for key in SECRET_KEYS:
            if key in values and not str(values[key] or "").strip():
                values.pop(key, None)
        set_values(db, values, int(user["id"]))
        audit(db, int(user["id"]), "system_settings_updated", "system", None, {"keys": sorted(values.keys())})
        return public_payload(db, settings)

    @router.post("/admin/mail/test")
    def test_mail(body: TestMailBody, request: Request) -> dict[str, Any]:
        user = admin(request, mutate=True)
        send_mail(
            settings,
            body.email.strip(),
            "PP – Personalplaner: Testnachricht",
            f"Guten Tag,\n\ndies ist eine Testnachricht aus PP – Personalplaner.\n\nAusgelöst von: {user['display_name']}",
        )
        audit(db, int(user["id"]), "mail_test_sent", "system", None, {"to": body.email.strip()})
        return {"ok": True}

    @router.post("/admin/microsoft/connect")
    def microsoft_connect(request: Request) -> dict[str, Any]:
        user = admin(request, mutate=True)
        values = get_all(db, settings)
        client_id = str(values.get("m365_client_id", "")).strip()
        tenant = str(values.get("m365_tenant", "organizations")).strip() or "organizations"
        client_secret = str(values.get("m365_client_secret", "")).strip()
        if not client_id or not client_secret:
            raise HTTPException(status_code=422, detail="Microsoft Client-ID und Client-Secret müssen zuerst gespeichert werden.")
        redirect_uri = _redirect_uri(values)
        state = secrets.token_urlsafe(32)
        set_values(
            db,
            {"m365_oauth_state": state, "m365_oauth_state_expires_at": str(int(time.time()) + 600)},
            int(user["id"]),
            allow_internal=True,
        )
        authorize = f"{LOGIN_BASE}/{tenant}/oauth2/v2.0/authorize?" + urlencode(
            {
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "response_mode": "query",
                "scope": M365_SCOPES,
                "state": state,
                "prompt": "select_account",
            }
        )
        audit(db, int(user["id"]), "m365_connect_started", "system", None)
        return {"authorize_url": authorize, "redirect_uri": redirect_uri}

    @router.get("/admin/microsoft/callback")
    def microsoft_callback(code: str = "", state: str = "", error: str = "", error_description: str = "") -> RedirectResponse:
        values = get_all(db, settings)
        expected = str(values.get("m365_oauth_state", ""))
        try:
            expires = int(values.get("m365_oauth_state_expires_at", "0") or 0)
        except (TypeError, ValueError):
            expires = 0
        if error:
            return RedirectResponse(url=f"/?m365=error&reason={error}", status_code=303)
        if not code or not expected or not secrets.compare_digest(state, expected) or expires < int(time.time()):
            return RedirectResponse(url="/?m365=error&reason=state", status_code=303)
        tenant = str(values.get("m365_tenant", "organizations")).strip() or "organizations"
        redirect_uri = _redirect_uri(values)
        token = _json_request(
            f"{LOGIN_BASE}/{tenant}/oauth2/v2.0/token",
            method="POST",
            data={
                "client_id": values.get("m365_client_id", ""),
                "client_secret": values.get("m365_client_secret", ""),
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "scope": M365_SCOPES,
            },
        )
        access_token = str(token.get("access_token", ""))
        refresh_token = str(token.get("refresh_token", ""))
        if not access_token or not refresh_token:
            raise HTTPException(status_code=502, detail="Microsoft hat kein dauerhaftes Zugriffstoken geliefert.")
        profile = _json_request(f"{GRAPH_BASE}/me?$select=id,displayName,mail,userPrincipalName", token=access_token)
        account_email = str(profile.get("mail") or profile.get("userPrincipalName") or "")
        set_values(
            db,
            {
                "m365_access_token": access_token,
                "m365_refresh_token": refresh_token,
                "m365_access_token_expires_at": str(int(time.time()) + max(60, int(token.get("expires_in", 3600))) - 90),
                "m365_account_id": str(profile.get("id", "")),
                "m365_account_name": str(profile.get("displayName", "")),
                "m365_account_email": account_email,
                "m365_connected_at": str(int(time.time())),
                "m365_oauth_state": "",
                "m365_oauth_state_expires_at": "",
            },
            None,
            allow_internal=True,
        )
        return RedirectResponse(url="/?m365=connected", status_code=303)

    @router.post("/admin/microsoft/disconnect")
    def microsoft_disconnect(request: Request) -> dict[str, Any]:
        user = admin(request, mutate=True)
        clear_values(
            db,
            [
                "m365_refresh_token", "m365_access_token", "m365_access_token_expires_at",
                "m365_account_id", "m365_account_name", "m365_account_email", "m365_connected_at",
                "m365_oauth_state", "m365_oauth_state_expires_at",
            ],
        )
        audit(db, int(user["id"]), "m365_disconnected", "system", None)
        return {"ok": True}

    return router
