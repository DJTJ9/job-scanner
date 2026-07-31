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

    rows_html = "".join(
        f'<tr><td style="padding:6px 12px">{r["title"]} @ {r["company"]}</td>'
        f'<td style="padding:6px 12px;text-align:right;font-weight:600">{r["score"]}</td></tr>'
        for r in rows)
    html = (
        '<div style="font-family:Arial,sans-serif;max-width:520px;margin:auto">'
        '<div style="background:#0B2A3A;color:#fff;padding:16px 20px;border-radius:8px 8px 0 0">'
        '<strong>Bob der Job-Bot &middot; Deine Treffer</strong><br>'
        f'<span style="font-size:14px">{len(rows)} neue Treffer</span></div>'
        f'<table style="width:100%;border-collapse:collapse;background:#fff">{rows_html}</table>'
        f'<div style="padding:16px 20px"><a href="{base_url}/benachrichtigungen" '
        'style="background:#1E88A8;color:#fff;padding:10px 16px;border-radius:6px;'
        'text-decoration:none">Alle im Portal ansehen &rarr;</a></div></div>')
    msg.add_alternative(html, subtype="html", cte="7bit")

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(from_addr, [email], msg.as_string())


def send_immediate_match(email: str, profile_id: int, rows: list[dict], base_url: str) -> None:
    host = os.environ.get("SMTP_HOST", "")
    if not host:
        raise RuntimeError("SMTP nicht konfiguriert (SMTP_HOST fehlt)")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASS", "")
    from_addr = os.environ.get("SMTP_FROM", user)

    lines = [f"- {r['title']} @ {r['company']}  (Score {r['score']})" for r in rows]
    body = (
        f"Starke Treffer fuer dich ({len(rows)}):\n\n"
        + "\n".join(lines)
        + f"\n\nIm Portal ansehen: {base_url}/benachrichtigungen\n")

    msg = EmailMessage()
    msg["Subject"] = f"Bob: {len(rows)} starke Treffer"
    msg["From"] = from_addr
    msg["To"] = email
    msg.set_content(body)

    rows_html = "".join(
        f'<div style="padding:8px 20px;font-size:16px"><strong>{r["title"]}</strong> '
        f'@ {r["company"]} <span style="font-weight:600">&middot; Score {r["score"]}</span></div>'
        for r in rows)
    msg.add_alternative(
        '<div style="font-family:Arial,sans-serif;max-width:520px;margin:auto">'
        '<div style="background:#0B2A3A;color:#fff;padding:16px 20px;border-radius:8px">'
        '<strong>Bob der Job-Bot &middot; Starke Treffer</strong></div>'
        f'{rows_html}'
        f'<div style="padding:16px 20px"><a href="{base_url}/benachrichtigungen" '
        'style="background:#1E88A8;color:#fff;padding:10px 16px;border-radius:6px;'
        'text-decoration:none">Im Portal ansehen &rarr;</a></div></div>',
        subtype="html")

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(from_addr, [email], msg.as_string())
