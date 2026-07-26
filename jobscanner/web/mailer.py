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


def send_password_reset_email(email: str, token: str, base_url: str) -> None:
    host = os.environ.get("SMTP_HOST", "")
    if not host:
        raise RuntimeError("SMTP nicht konfiguriert (SMTP_HOST fehlt)")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASS", "")
    from_addr = os.environ.get("SMTP_FROM", user)
    link = f"{base_url}/reset-password?token={token}"

    msg = EmailMessage()
    msg["Subject"] = "Bob der Job-Bot — Passwort zuruecksetzen"
    msg["From"] = from_addr
    msg["To"] = email
    msg.set_content(
        f"Du hast ein neues Passwort angefordert.\n\n"
        f"Setze es hier (Link 1 Stunde gueltig):\n\n{link}\n\n"
        f"Falls du das nicht warst, ignoriere diese Mail.\n")

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(from_addr, [email], msg.as_string())


def send_email_change_verification(new_email: str, token: str, base_url: str) -> None:
    host = os.environ.get("SMTP_HOST", "")
    if not host:
        raise RuntimeError("SMTP nicht konfiguriert (SMTP_HOST fehlt)")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASS", "")
    from_addr = os.environ.get("SMTP_FROM", user)
    link = f"{base_url}/account/email/confirm?token={token}"

    msg = EmailMessage()
    msg["Subject"] = "Bob der Job-Bot — Neue Email bestaetigen"
    msg["From"] = from_addr
    msg["To"] = new_email
    msg.set_content(
        f"Bitte bestaetige deine neue Email-Adresse:\n\n{link}\n\n"
        f"Erst nach Klick wird sie aktiv.\n")

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(from_addr, [new_email], msg.as_string())


def send_match_digest(email: str, profile_id: int, rows: list[dict], base_url: str) -> None:
    host = os.environ.get("SMTP_HOST", "")
    if not host:
        raise RuntimeError("SMTP nicht konfiguriert (SMTP_HOST fehlt)")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASS", "")
    from_addr = os.environ.get("SMTP_FROM", user)

    lines = [f"- {r['title']} @ {r['company']}  (Score {r['score']})" for r in rows]
    body = (
        "Hallo,\n\n"
        f"{len(rows)} neue Top-Treffer in deinem Profil:\n\n"
        + "\n".join(lines)
        + f"\n\nAlle ansehen: {base_url}/dashboard/{profile_id}\n"
        "Abschalten: Einstellungen -> Benachrichtigung\n")

    msg = EmailMessage()
    msg["Subject"] = f"Bob: {len(rows)} neue Top-Treffer"
    msg["From"] = from_addr
    msg["To"] = email
    msg.set_content(body, cte="7bit")

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(from_addr, [email], msg.as_string())
