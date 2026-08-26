from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from .config import Settings
from .db import Database

SECRET_KEYS = {
    "smtp_password",
    "m365_client_secret",
    "m365_refresh_token",
    "m365_access_token",
    "m365_oauth_state",
}

BOOL_KEYS = {
    "smtp_starttls",
    "smtp_ssl",
    "offboarding_default_replacement",
    "offboarding_require_reason_text",
    "offboarding_allow_same_day",
    "notify_admin_on_offboarding",
    "audit_enabled",
    "automation_emergency_stop",
    "automation_retry_failed_mail",
    "automation_watch_upcoming",
    "automation_watch_unassigned",
    "automation_watch_assignment_end",
    "automation_housekeeping",
}

INT_KEYS = {
    "smtp_port",
    "offboarding_default_days",
    "session_hours_override",
    "audit_retention_days",
    "automation_interval_minutes",
    "automation_retry_after_minutes",
    "automation_retry_max_attempts",
    "automation_upcoming_days",
    "automation_assignment_end_days",
}

EDITABLE_KEYS = {
    "company_name",
    "company_site",
    "company_address",
    "company_postal_city",
    "company_phone",
    "company_contact",
    "company_email",
    "mail_provider",
    "mail_default_cc",
    "mail_default_bcc",
    "mail_reply_to",
    "mail_footer",
    "smtp_host",
    "smtp_port",
    "smtp_user",
    "smtp_password",
    "smtp_from",
    "smtp_starttls",
    "smtp_ssl",
    "m365_tenant",
    "m365_client_id",
    "m365_client_secret",
    "m365_public_base_url",
    "offboarding_default_replacement",
    "offboarding_default_days",
    "offboarding_require_reason_text",
    "offboarding_allow_same_day",
    "offboarding_subject_template",
    "offboarding_body_template",
    "notify_admin_on_offboarding",
    "notification_admin_email",
    "session_hours_override",
    "audit_enabled",
    "audit_retention_days",
    "autonomy_mode",
    "automation_emergency_stop",
    "automation_interval_minutes",
    "automation_retry_failed_mail",
    "automation_retry_after_minutes",
    "automation_retry_max_attempts",
    "automation_watch_upcoming",
    "automation_upcoming_days",
    "automation_watch_unassigned",
    "automation_watch_assignment_end",
    "automation_assignment_end_days",
    "automation_housekeeping",
}

M365_INTERNAL_KEYS = {
    "m365_refresh_token",
    "m365_access_token",
    "m365_access_token_expires_at",
    "m365_oauth_state",
    "m365_oauth_state_expires_at",
    "m365_account_id",
    "m365_account_name",
    "m365_account_email",
    "m365_connected_at",
}

DEFAULT_BODY = """Guten Tag,

hiermit melden wir folgende Zeitarbeitskraft bei {agency_name} ab:

Mitarbeiter: {employee_name}
{employee_code_line}Abteilung: {department_name}
Abmeldung wirksam zum: {effective_date}
Grund: {reason}
{reason_text_line}Ersatz wird benötigt: {replacement}
{replacement_notes_line}
Angefordert von: {requested_by}

Viele Grüße
{company_contact}
{company_name}

Diese Nachricht wurde durch PP – Personalplaner erstellt."""


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def ensure_schema(db: Database) -> None:
    with db.transaction() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT '',
                is_secret INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                updated_by INTEGER REFERENCES users(id)
            );
            """
        )


def defaults(settings: Settings) -> dict[str, Any]:
    return {
        "company_name": settings.company_name,
        "company_site": "",
        "company_address": "",
        "company_postal_city": "",
        "company_phone": "",
        "company_contact": settings.company_contact,
        "company_email": "",
        "mail_provider": "smtp",
        "mail_default_cc": "",
        "mail_default_bcc": "",
        "mail_reply_to": "",
        "mail_footer": "",
        "smtp_host": settings.smtp_host,
        "smtp_port": settings.smtp_port,
        "smtp_user": settings.smtp_user,
        "smtp_password": settings.smtp_password,
        "smtp_from": settings.smtp_from,
        "smtp_starttls": settings.smtp_starttls,
        "smtp_ssl": settings.smtp_ssl,
        "m365_tenant": "organizations",
        "m365_client_id": "",
        "m365_client_secret": "",
        "m365_public_base_url": "",
        "m365_refresh_token": "",
        "m365_access_token": "",
        "m365_access_token_expires_at": "",
        "m365_oauth_state": "",
        "m365_oauth_state_expires_at": "",
        "m365_account_id": "",
        "m365_account_name": "",
        "m365_account_email": "",
        "m365_connected_at": "",
        "offboarding_default_replacement": False,
        "offboarding_default_days": 0,
        "offboarding_require_reason_text": False,
        "offboarding_allow_same_day": True,
        "offboarding_subject_template": "Abmeldung Zeitarbeit: {employee_name} zum {effective_date}",
        "offboarding_body_template": DEFAULT_BODY,
        "notify_admin_on_offboarding": False,
        "notification_admin_email": "",
        "session_hours_override": settings.session_hours,
        "audit_enabled": True,
        "audit_retention_days": 3650,
        "autonomy_mode": "manual",
        "automation_emergency_stop": False,
        "automation_interval_minutes": 5,
        "automation_retry_failed_mail": True,
        "automation_retry_after_minutes": 15,
        "automation_retry_max_attempts": 5,
        "automation_watch_upcoming": True,
        "automation_upcoming_days": 7,
        "automation_watch_unassigned": True,
        "automation_watch_assignment_end": True,
        "automation_assignment_end_days": 3,
        "automation_housekeeping": False,
    }


def _decode(key: str, value: str) -> Any:
    if key in BOOL_KEYS:
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if key in INT_KEYS:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    return value


def _encode(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value if value is not None else "")


def get_all(db: Database, settings: Settings) -> dict[str, Any]:
    ensure_schema(db)
    result = defaults(settings)
    for row in db.all("SELECT key,value FROM system_settings"):
        result[row["key"]] = _decode(row["key"], row["value"])
    return result


def get_value(db: Database, settings: Settings, key: str, default: Any = "") -> Any:
    values = get_all(db, settings)
    return values.get(key, default)


def set_values(db: Database, values: dict[str, Any], user_id: int | None = None, *, allow_internal: bool = False) -> None:
    ensure_schema(db)
    allowed = EDITABLE_KEYS | (M365_INTERNAL_KEYS if allow_internal else set())
    now = _now()
    with db.transaction() as conn:
        for key, value in values.items():
            if key not in allowed:
                continue
            if key in INT_KEYS:
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    value = 0
            if key in BOOL_KEYS:
                value = bool(value)
            encoded = _encode(value)
            conn.execute(
                """INSERT INTO system_settings(key,value,is_secret,updated_at,updated_by)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value,is_secret=excluded.is_secret,
                   updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                (key, encoded, int(key in SECRET_KEYS), now, user_id),
            )


def clear_values(db: Database, keys: list[str]) -> None:
    ensure_schema(db)
    with db.transaction() as conn:
        conn.executemany("DELETE FROM system_settings WHERE key=?", [(key,) for key in keys])


def public_payload(db: Database, settings: Settings) -> dict[str, Any]:
    values = get_all(db, settings)
    payload = {key: value for key, value in values.items() if key in EDITABLE_KEYS and key not in SECRET_KEYS}
    for key in SECRET_KEYS & EDITABLE_KEYS:
        payload[f"{key}_configured"] = bool(values.get(key))
    payload["m365_connected"] = bool(values.get("m365_refresh_token") and values.get("m365_account_email"))
    payload["m365_account_name"] = values.get("m365_account_name", "")
    payload["m365_account_email"] = values.get("m365_account_email", "")
    payload["m365_connected_at"] = values.get("m365_connected_at", "")
    return payload


def mail_ready(db: Database, settings: Settings) -> tuple[bool, str]:
    values = get_all(db, settings)
    provider = values.get("mail_provider", "smtp")
    if provider == "microsoft365":
        ready = bool(values.get("m365_refresh_token") and values.get("m365_client_id") and values.get("m365_client_secret"))
        return ready, "Microsoft 365"
    ready = bool(values.get("smtp_host") and values.get("smtp_from"))
    return ready, "SMTP"
