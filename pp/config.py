from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    data_dir: Path
    allowed_hosts: list[str]
    cookie_secure: bool
    session_hours: int
    setup_token: str
    company_name: str
    company_contact: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    smtp_starttls: bool
    smtp_ssl: bool


def load_settings() -> Settings:
    data_dir = Path(os.getenv("PP_DATA_DIR", "./data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    setup_token = os.getenv("PP_SETUP_TOKEN", "").strip()
    token_file = data_dir / "setup-token.txt"
    if not setup_token:
        if token_file.exists():
            setup_token = token_file.read_text(encoding="utf-8").strip()
        else:
            setup_token = secrets.token_urlsafe(24)
            token_file.write_text(setup_token + "\n", encoding="utf-8")
            try:
                token_file.chmod(0o600)
            except OSError:
                pass
            print(f"[PP] First-run setup token: {setup_token}", flush=True)
    allowed = [item.strip() for item in os.getenv("PP_ALLOWED_HOSTS", "").split(",") if item.strip()]
    return Settings(
        host=os.getenv("PP_HOST", "0.0.0.0"),
        port=int(os.getenv("PP_PORT", "8780")),
        data_dir=data_dir,
        allowed_hosts=allowed or ["*"],
        cookie_secure=_bool("PP_COOKIE_SECURE", False),
        session_hours=max(1, min(168, int(os.getenv("PP_SESSION_HOURS", "12")))),
        setup_token=setup_token,
        company_name=os.getenv("PP_COMPANY_NAME", "Meine Firma").strip() or "Meine Firma",
        company_contact=os.getenv("PP_COMPANY_CONTACT", "Personalplanung").strip() or "Personalplanung",
        smtp_host=os.getenv("SMTP_HOST", "").strip(),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_user=os.getenv("SMTP_USER", "").strip(),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        smtp_from=os.getenv("SMTP_FROM", "").strip(),
        smtp_starttls=_bool("SMTP_STARTTLS", True),
        smtp_ssl=_bool("SMTP_SSL", False),
    )
