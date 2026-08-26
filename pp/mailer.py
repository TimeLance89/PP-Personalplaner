from __future__ import annotations

import smtplib
from email.message import EmailMessage

from .config import Settings


class MailConfigurationError(RuntimeError):
    pass


def send_mail(settings: Settings, to: str, subject: str, body: str) -> None:
    if not settings.smtp_host or not settings.smtp_from:
        raise MailConfigurationError("SMTP ist noch nicht vollständig konfiguriert.")
    if not to:
        raise MailConfigurationError("Bei der Zeitarbeitsfirma ist keine E-Mail-Adresse hinterlegt.")

    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    smtp_cls = smtplib.SMTP_SSL if settings.smtp_ssl else smtplib.SMTP
    with smtp_cls(settings.smtp_host, settings.smtp_port, timeout=20) as client:
        if not settings.smtp_ssl:
            client.ehlo()
            if settings.smtp_starttls:
                client.starttls()
                client.ehlo()
        if settings.smtp_user:
            client.login(settings.smtp_user, settings.smtp_password)
        client.send_message(message)
