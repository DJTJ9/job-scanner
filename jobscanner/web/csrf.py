"""CSRF-Schutz über den bestehenden Session-Cookie: Token wird bei Bedarf in der
Session erzeugt (ensure_token, als Jinja-Global aus jedem Template aufrufbar) und
bei jedem POST gegen das übermittelte Token geprüft (verify)."""
from __future__ import annotations

import hmac
import secrets

from starlette.requests import Request


def ensure_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def verify(request: Request, submitted: str | None) -> bool:
    expected = request.session.get("csrf_token")
    if not expected or not submitted:
        return False
    return hmac.compare_digest(expected, submitted)
