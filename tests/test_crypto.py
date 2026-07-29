"""Fernet wrap/unwrap für Member-Firecrawl-Keys."""
import pytest

from cryptography.fernet import Fernet
from jobscanner import crypto


@pytest.fixture
def fkey(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("JOBSCANNER_FERNET_KEY", key)
    return key


def test_roundtrip(fkey):
    token = crypto.encrypt("fc-secret-123")
    assert token != "fc-secret-123"
    assert crypto.decrypt(token) == "fc-secret-123"


def test_decrypt_bad_token_returns_none(fkey):
    assert crypto.decrypt("not-a-valid-token") is None


def test_missing_env_raises(monkeypatch):
    monkeypatch.delenv("JOBSCANNER_FERNET_KEY", raising=False)
    with pytest.raises(RuntimeError):
        crypto.encrypt("x")


def test_require_key_raises_when_missing(monkeypatch):
    monkeypatch.delenv("JOBSCANNER_FERNET_KEY", raising=False)
    with pytest.raises(RuntimeError):
        crypto.require_key()


def test_require_key_returns_when_set(monkeypatch):
    monkeypatch.setenv("JOBSCANNER_FERNET_KEY", Fernet.generate_key().decode())
    assert crypto.require_key()
