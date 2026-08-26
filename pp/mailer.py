from __future__ import annotations

import json
import smtplib
import time
from email.message import EmailMessage
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import Settings
from .db import Database
from .system_settings import get_all, set_values


class MailConfigurationError(RuntimeError):
    pass


class MailDeliveryError(RuntimeError):
    pass


def _db(settings: Settings) -> Database:
    return Database(settings.data_dir / "personalplaner.sqlite3")


def _addresses(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").replace(";", ",").split(",") if part.strip()]


def _smtp_send(values: dict[str, Any], to: str, subject: str, body: str, cc: list[str], bcc: list[str]) -> None:
    host = str(values.get("smtp_host", "")).strip()
    sender = str(values.get("smtp_from", "")).strip()
    if not host or not sender:
        raise MailConfigurationError("SMTP ist noch nicht vollständig konfiguriert.")

    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    if cc:
        message["Cc"] = ", ".join(cc)
    if bcc:
        message["Bcc"] = ", ".join(bcc)
    if values.get("mail_reply_to"):
        message["Reply-To"] = str(values["mail_reply_to"]).strip()
    message["Subject"] = subject
    message.set_content(body)

    smtp_ssl = bool(values.get("smtp_ssl"))
    smtp_cls = smtplib.SMTP_SSL if smtp_ssl else smtplib.SMTP
    try:
        with smtp_cls(host, int(values.get("smtp_port", 587) or 587), timeout=20) as client:
            if not smtp_ssl:
                client.ehlo()
                if bool(values.get("smtp_starttls", True)):
                    client.starttls()
                    client.ehlo()
            user = str(values.get("smtp_user", "")).strip()
            if user:
                client.login(user, str(values.get("smtp_password", "")))
            client.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise MailDeliveryError(f"SMTP-Versand fehlgeschlagen: {exc}") from exc


def _token_request(url: str, data: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        url,
        data=urlencode(data).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=25) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
            detail = payload.get("error_description") or payload.get("error") or str(exc)
        except Exception:
            detail = str(exc)
        raise MailDeliveryError(f"Microsoft-Token konnte nicht erneuert werden: {str(detail)[:500]}") from exc
    except URLError as exc:
        raise MailDeliveryError(f"Microsoft ist nicht erreichbar: {exc.reason}") from exc


def _m365_access_token(db: Database, settings: Settings, values: dict[str, Any]) -> str:
    access = str(values.get("m365_access_token", ""))
    try:
        expires = int(values.get("m365_access_token_expires_at", "0") or 0)
    except (TypeError, ValueError):
        expires = 0
    if access and expires > int(time.time()) + 30:
        return access

    tenant = str(values.get("m365_tenant", "organizations")).strip() or "organizations"
    client_id = str(values.get("m365_client_id", "")).strip()
    client_secret = str(values.get("m365_client_secret", ""))
    refresh_token = str(values.get("m365_refresh_token", ""))
    if not client_id or not client_secret or not refresh_token:
        raise MailConfigurationError("Microsoft 365 ist noch nicht vollständig verbunden.")

    token = _token_request(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": "openid profile email offline_access https://graph.microsoft.com/User.Read https://graph.microsoft.com/Mail.Send",
        },
    )
    access = str(token.get("access_token", ""))
    if not access:
        raise MailDeliveryError("Microsoft hat kein Zugriffstoken geliefert.")
    update = {
        "m365_access_token": access,
        "m365_access_token_expires_at": str(int(time.time()) + max(60, int(token.get("expires_in", 3600))) - 90),
    }
    if token.get("refresh_token"):
        update["m365_refresh_token"] = str(token["refresh_token"])
    set_values(db, update, None, allow_internal=True)
    return access


def _graph_recipient(email: str) -> dict[str, Any]:
    return {"emailAddress": {"address": email}}


def _m365_send(db: Database, settings: Settings, values: dict[str, Any], to: str, subject: str, body: str, cc: list[str], bcc: list[str]) -> None:
    token = _m365_access_token(db, settings, values)
    message: dict[str, Any] = {
        "subject": subject,
        "body": {"contentType": "Text", "content": body},
        "toRecipients": [_graph_recipient(address) for address in _addresses(to)],
    }
    if cc:
        message["ccRecipients"] = [_graph_recipient(address) for address in cc]
    if bcc:
        message["bccRecipients"] = [_graph_recipient(address) for address in bcc]
    reply_to = str(values.get("mail_reply_to", "")).strip()
    if reply_to:
        message["replyTo"] = [_graph_recipient(reply_to)]

    payload = json.dumps({"message": message, "saveToSentItems": True}, ensure_ascii=False).encode("utf-8")
    request = Request(
        "https://graph.microsoft.com/v1.0/me/sendMail",
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=25) as response:
            if response.status not in (200, 202):
                raise MailDeliveryError(f"Microsoft Graph antwortete mit HTTP {response.status}")
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
            detail = payload.get("error", {}).get("message") or str(exc)
        except Exception:
            detail = str(exc)
        raise MailDeliveryError(f"Microsoft-365-Versand fehlgeschlagen: {str(detail)[:500]}") from exc
    except URLError as exc:
        raise MailDeliveryError(f"Microsoft Graph ist nicht erreichbar: {exc.reason}") from exc


def send_mail(settings: Settings, to: str, subject: str, body: str) -> None:
    if not to or not _addresses(to):
        raise MailConfigurationError("Bei der Zeitarbeitsfirma ist keine E-Mail-Adresse hinterlegt.")

    db = _db(settings)
    values = get_all(db, settings)
    footer = str(values.get("mail_footer", "")).strip()
    if footer:
        body = f"{body.rstrip()}\n\n{footer}"

    cc = _addresses(str(values.get("mail_default_cc", "")))
    bcc = _addresses(str(values.get("mail_default_bcc", "")))
    if bool(values.get("notify_admin_on_offboarding")) and subject.lower().startswith("abmeldung"):
        admin_email = str(values.get("notification_admin_email", "")).strip()
        if admin_email and admin_email not in cc:
            cc.append(admin_email)

    provider = str(values.get("mail_provider", "smtp")).strip().lower()
    if provider == "microsoft365":
        _m365_send(db, settings, values, to, subject, body, cc, bcc)
        return
    _smtp_send(values, to, subject, body, cc, bcc)
