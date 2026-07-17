"""Tests für den BYO-Member-MCP-Zugang: Token, Tool-Scoping, Auth, Push-Validierung."""
import pytest
from fastapi.testclient import TestClient

from jobscanner import storage
from jobscanner.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    app = create_app(db_path=tmp_path / "jobs.db")
    return TestClient(app)


@pytest.fixture
def member(client):
    uid = storage.create_user("member@test.de", "memberpw")
    token = storage.create_api_token(uid)
    return {"id": uid, "token": token}


class TestApiToken:
    def test_create_api_token_returns_bob_prefixed_plaintext(self, client):
        uid = storage.create_user("m1@test.de", "pw")
        token = storage.create_api_token(uid)
        assert token.startswith("bob_")
        assert len(token) == 4 + 48  # bob_ + 24 Hex-Bytes

    def test_token_stored_as_hash_not_plaintext(self, client):
        uid = storage.create_user("m2@test.de", "pw")
        token = storage.create_api_token(uid)
        user = storage.get_user(uid)
        assert user["api_token_hash"] != token
        assert token not in (user["api_token_hash"] or "")

    def test_get_user_by_api_token_roundtrip(self, client):
        uid = storage.create_user("m3@test.de", "pw")
        token = storage.create_api_token(uid)
        assert storage.get_user_by_api_token(token)["id"] == uid

    def test_get_user_by_api_token_invalid_returns_none(self, client):
        assert storage.get_user_by_api_token("bob_" + "0" * 48) is None
        assert storage.get_user_by_api_token("") is None

    def test_create_api_token_replaces_old_token(self, client):
        uid = storage.create_user("m4@test.de", "pw")
        old = storage.create_api_token(uid)
        new = storage.create_api_token(uid)
        assert storage.get_user_by_api_token(old) is None
        assert storage.get_user_by_api_token(new)["id"] == uid


def _mk_extracted_job(fp_suffix: str, title: str = "Unity Dev") -> str:
    """Extrahierten Job direkt in die jobs-Tabelle legen (Test-Shortcut)."""
    from jobscanner.models import Job
    job = Job(title=title, company=f"Firma-{fp_suffix}", location="Hamburg",
              remote_flag="remote", employment_type="Festanstellung", language="de",
              salary_text="", requirements=["C#"], tech_stack=["Unity"],
              sources=[{"portal": "test", "url": f"https://t.test/{fp_suffix}"}],
              first_seen="2026-07-17", last_seen="2026-07-17")
    storage.upsert_job(job)
    return job.fingerprint


class TestScopedQueries:
    def test_list_unscored_for_profiles_returns_only_missing(self, client):
        uid = storage.create_user("m5@test.de", "pw")
        pid = storage.create_profile("M5", {"no_gos": []}, user_id=uid)
        fp1 = _mk_extracted_job("a")
        fp2 = _mk_extracted_job("b", title="Godot Dev")
        storage.upsert_job_score(pid, fp1, 7, "ok", "Pass", {})
        out = storage.list_unscored_for_profiles([pid])
        assert [j["fingerprint"] for j in out] == [fp2]
        assert out[0]["title"] == "Godot Dev"
        assert "requirements" in out[0] and "tech_stack" in out[0]

    def test_list_unscored_for_profiles_empty_ids(self, client):
        _mk_extracted_job("c")
        assert storage.list_unscored_for_profiles([]) == []

    def test_insert_raw_job_via_marker(self, client):
        storage.insert_raw_job("https://m.test/1", "adzuna", "Rohtext", "2026-07-17",
                               via="member:7")
        job = storage.list_pending_extraction()[0]
        import json as _json
        conn = storage._require_conn()
        row = conn.execute("SELECT sources_json FROM jobs WHERE fingerprint = ?",
                           (job["fingerprint"],)).fetchone()
        assert _json.loads(row["sources_json"])[0]["via"] == "member:7"

    def test_score_deterministic_only_missing_keeps_existing(self, client):
        uid = storage.create_user("m6@test.de", "pw")
        pid = storage.create_profile("M6", {"no_gos": []}, user_id=uid)
        storage.save_criteria(pid, [{"key": "remote", "label": "Remote", "weight": 5}])
        fp1 = _mk_extracted_job("d")
        storage.upsert_job_score(pid, fp1, 99, "member-llm", "Pass", {})
        fp2 = _mk_extracted_job("e", title="Zweiter Job")
        storage.score_profile_deterministic(pid, only_missing=True)
        assert storage.get_job_score(pid, fp1)["score"] == 99      # nicht überschrieben
        assert storage.get_job_score(pid, fp2) is not None          # Lücke gefüllt
