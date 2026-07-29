"""Member-Firecrawl-Key-Verwaltung + /portale-Firecrawl-Precheck."""
import pytest
from unittest.mock import patch
from cryptography.fernet import Fernet
from _csrf_client import CSRFTestClient

from jobscanner import storage
from jobscanner.web.app import create_app


@pytest.fixture
def member(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    monkeypatch.setenv("JOBSCANNER_FERNET_KEY", Fernet.generate_key().decode())
    app = create_app(db_path=tmp_path / "jobs.db")
    uid = storage.create_user("m@test.de", "pw", role="member")
    storage.mark_email_verified(uid)
    c = CSRFTestClient(app)
    c.post("/login", data={"email": "m@test.de", "password": "pw"})
    return c, uid


def test_firecrawl_tab_renders(member):
    c, uid = member
    resp = c.get("/einstellungen?tab=firecrawl")
    assert 'data-tab-panel="firecrawl"' in resp.text
    assert 'action="/einstellungen/firecrawl"' in resp.text


def test_save_valid_key_encrypts_and_stores(member):
    c, uid = member
    with patch("jobscanner.web.app.browser.validate_firecrawl_key", return_value=True):
        resp = c.post("/einstellungen/firecrawl", data={"firecrawl_key": "fc-xyz"},
                      follow_redirects=False)
    assert resp.status_code == 303
    enc = storage.get_firecrawl_key_enc(uid)
    assert enc and enc != "fc-xyz"
    from jobscanner import crypto
    assert crypto.decrypt(enc) == "fc-xyz"


def test_save_invalid_key_rejected(member):
    c, uid = member
    with patch("jobscanner.web.app.browser.validate_firecrawl_key", return_value=False):
        resp = c.post("/einstellungen/firecrawl", data={"firecrawl_key": "bad"})
    assert storage.get_firecrawl_key_enc(uid) is None
    assert "ungültig" in resp.text.lower() or "abgelehnt" in resp.text.lower()


def test_delete_key(member):
    c, uid = member
    storage.set_firecrawl_key(uid, "enc")
    resp = c.post("/einstellungen/firecrawl/loeschen", follow_redirects=False)
    assert resp.status_code == 303
    assert storage.get_firecrawl_key_enc(uid) is None


def test_pruefen_firecrawl_sets_failover_on_compatible(member):
    c, uid = member
    from jobscanner import crypto
    storage.set_firecrawl_key(uid, crypto.encrypt("fc-key"))
    pid = storage.create_custom_portal("https://foo.de", "career_page", uid)
    good = {"compatible": True, "rendered": True, "blocked": False, "structured": True}
    with patch("jobscanner.web.app.precheck.precheck_portal", return_value=good) as pc:
        resp = c.post(f"/portale/pruefen-firecrawl/{pid}")
    assert pc.call_args.kwargs["use_firecrawl"] is True
    assert pc.call_args.kwargs["firecrawl_key"] == "fc-key"
    assert storage.get_custom_portal(pid)["firecrawl_failover"] is True


def test_pruefen_firecrawl_without_key_redirects_no_call(member):
    c, uid = member
    pid = storage.create_custom_portal("https://foo.de", "career_page", uid)
    with patch("jobscanner.web.app.precheck.precheck_portal") as pc:
        c.post(f"/portale/pruefen-firecrawl/{pid}", follow_redirects=False)
    pc.assert_not_called()
