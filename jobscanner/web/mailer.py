"""smtplib-Wrapper für die Verifizierungs-Mail — bewusst kein Retry/Queue: Register-Route
fängt Fehler ab, Account bleibt gesperrt bis manuelles Eingreifen bei SMTP-Ausfall
(akzeptierter Trade-off des Hard-Locks)."""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage


def send_verification_email(email: str, token: str, base_url: str) -> None:
    host = os.environ.get("SMTP_HOST", "")
    if not host:
        raise RuntimeError("SMTP nicht konfiguriert (SMTP_HOST fehlt)")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASS", "")
    from_addr = os.environ.get("SMTP_FROM", user)
    link = f"{base_url}/verify-email?token={token}"

    msg = EmailMessage()
    msg["Subject"] = "Bob der Job-Bot — Email bestätigen"
    msg["From"] = from_addr
    msg["To"] = email
    msg.set_content(
        f"Willkommen bei Bob der Job-Bot!\n\n"
        f"Bitte bestaetige deine Email-Adresse, um Zugriff auf Scan und\n"
        f"Dashboard freizuschalten:\n\n{link}\n")

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(from_addr, [email], msg.as_string())
