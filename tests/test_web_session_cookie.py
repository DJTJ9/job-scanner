"""Finding 4: Session-Cookie trägt Secure + explizites SameSite=lax.

Die App läuft in Prod ausschließlich hinter https (job-scanner.thinkshark.de),
daher muss das Session-Cookie mit `Secure` und explizitem `SameSite=lax`
ausgeliefert werden.
"""
import pytest
from _csrf_client import CSRFTestClient

from jobscanner.web.app import create_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "ownerpw")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    return create_app(db_path=tmp_path / "jobs.db")


def test_session_cookie_secure_and_samesite_lax_over_https(app):
    client = CSRFTestClient(app, base_url="https://testserver")
    resp = client.post("/login", data={"email": "owner@test.de", "password": "ownerpw"},
                       follow_redirects=False)
    set_cookie = resp.headers.get("set-cookie", "")
    assert "session=" in set_cookie
    # Starlette schreibt die Cookie-Flags kleingeschrieben ("secure").
    assert "secure" in set_cookie.lower()
    assert "samesite=lax" in set_cookie.lower()
