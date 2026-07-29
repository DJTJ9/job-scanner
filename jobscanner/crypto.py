"""Fernet-Verschlüsselung für Member-Secrets (Firecrawl-Keys).

Klartext nie in der DB — nur der Ciphertext aus encrypt() wird gespeichert.
Server-Key aus JOBSCANNER_FERNET_KEY (Fernet.generate_key()).
"""
from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken


def _fernet() -> Fernet:
    key = os.environ.get("JOBSCANNER_FERNET_KEY")
    if not key:
        raise RuntimeError("JOBSCANNER_FERNET_KEY nicht gesetzt")
    return Fernet(key.encode())


def require_key() -> str:
    """Boot-Assert: JOBSCANNER_FERNET_KEY muss gesetzt sein. Fail-fast beim
    App-Start statt erst bei der ersten Verschlüsselung. Kein Plaintext-Fallback."""
    key = os.environ.get("JOBSCANNER_FERNET_KEY")
    if not key:
        raise RuntimeError(
            "JOBSCANNER_FERNET_KEY nicht gesetzt — Member-Secret-Verschlüsselung "
            "nicht möglich. In /etc/jobscanner/web.env provisionieren (Fernet.generate_key()).")
    return key


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError, TypeError):
        return None
