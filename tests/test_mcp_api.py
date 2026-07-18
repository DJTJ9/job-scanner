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


from jobscanner.web import mcp_api


def _member_with_profile(email="scoped@test.de"):
    uid = storage.create_user(email, "pw")
    pid = storage.create_profile(f"Profil-{email}", {"no_gos": []}, user_id=uid)
    storage.save_criteria(pid, [{"key": "remote", "label": "Remote", "weight": 5}])
    return storage.get_user(uid), pid


class TestToolLogic:
    def test_get_my_profile_scoped_to_token_user(self, client):
        user, pid = _member_with_profile()
        _other, other_pid = _member_with_profile("other@test.de")
        out = mcp_api.get_my_profile_data(user)
        ids = [p["id"] for p in out["profiles"]]
        assert pid in ids and other_pid not in ids
        assert out["profiles"][0]["criteria"] == [
            {"key": "remote", "label": "Remote", "weight": 5}]

    def test_pull_pending_includes_raw_and_own_unscored(self, client):
        user, pid = _member_with_profile()
        storage.insert_raw_job("https://m.test/raw", "adzuna", "Rohtext", "2026-07-17")
        fp = _mk_extracted_job("p1")
        out = mcp_api.pull_pending_jobs_data(user, limit=10)
        assert [j["raw_text"] for j in out["jobs"]] == ["Rohtext"]
        assert [j["fingerprint"] for j in out["to_score"]] == [fp]

    def test_push_batch_rejects_foreign_profile(self, client):
        user, _pid = _member_with_profile()
        _other, other_pid = _member_with_profile("fremd@test.de")
        fp = _mk_extracted_job("p2")
        entry = {"fingerprint": fp, "scores": {str(other_pid): {
            "veto": None, "kriterien": {"remote": {"punkte": 5, "grund": "x"}}}}}
        with pytest.raises(ValueError, match="geh"):
            mcp_api.push_batch_data(user, [entry])
        assert storage.get_job_score(other_pid, fp) is None

    def test_push_batch_rejects_out_of_range_punkte(self, client):
        user, pid = _member_with_profile()
        fp = _mk_extracted_job("p3")
        entry = {"fingerprint": fp, "scores": {str(pid): {
            "veto": None, "kriterien": {"remote": {"punkte": 11, "grund": "x"}}}}}
        with pytest.raises(ValueError, match="0-10"):
            mcp_api.push_batch_data(user, [entry])

    def test_push_batch_applies_extraction_and_scores(self, client):
        user, pid = _member_with_profile()
        raw_fp = storage.insert_raw_job("https://m.test/x1", "adzuna",
                                        "Unity Dev bei ACME", "2026-07-17")
        entry = {"fingerprint": raw_fp,
                 "extraction": {"title": "Unity Dev", "company": "ACME",
                                "location": "Hamburg", "remote": "remote",
                                "employment_type": "Festanstellung", "language": "de",
                                "salary": "", "requirements": ["C#"], "tech_stack": ["Unity"]},
                 "scores": {str(pid): {"veto": None, "kriterien": {
                     "remote": {"punkte": 8, "grund": "voll remote"}}}}}
        stats = mcp_api.push_batch_data(user, [entry])
        assert stats["extracted"] == 1 and stats["scored"] == 1
        jobs = storage.list_jobs()
        assert len(jobs) == 1 and jobs[0].title == "Unity Dev"
        score_row = storage.get_job_score(pid, jobs[0].fingerprint)
        assert score_row is not None and score_row["score"] is not None
        assert jobs[0].score is None  # jobs-Tabelle (Owner-Spalten) bleibt unberührt

    def test_push_batch_auto_scores_other_member_profiles(self, client):
        user, _pid = _member_with_profile()
        other, other_pid = _member_with_profile("auto@test.de")
        raw_fp = storage.insert_raw_job("https://m.test/x2", "adzuna", "Text", "2026-07-17")
        entry = {"fingerprint": raw_fp,
                 "extraction": {"title": "Godot Dev", "company": "ACME2",
                                "location": "", "remote": "remote", "employment_type": "",
                                "language": "de", "salary": "",
                                "requirements": [], "tech_stack": []},
                 "scores": {}}
        mcp_api.push_batch_data(user, [entry])
        new_fp = storage.list_jobs()[0].fingerprint
        assert storage.get_job_score(other_pid, new_fp) is not None

    def test_push_jobs_dedups_and_marks_member_source(self, client):
        import json as _json
        user, _pid = _member_with_profile()
        listings = [{"url": "https://m.test/j1", "portal": "adzuna", "raw_text": "Anzeige 1"},
                    {"url": "https://m.test/j1", "portal": "adzuna", "raw_text": "Anzeige 1"}]
        stats = mcp_api.push_jobs_data(user, listings)
        assert stats == {"inserted": 1, "duplicates_url": 1, "duplicates_content": 0}
        pending = storage.list_pending_extraction()
        assert len(pending) == 1
        conn = storage._require_conn()
        row = conn.execute("SELECT sources_json FROM jobs WHERE fingerprint = ?",
                           (pending[0]["fingerprint"],)).fetchone()
        assert _json.loads(row["sources_json"])[0]["via"] == f"member:{user['id']}"

    def test_push_jobs_skips_content_duplicate_from_other_portal(self, client):
        user, _pid = _member_with_profile()
        _mk_extracted_job("cd1", title="Unity Dev")  # fp = make_fingerprint("Firma-cd1", "Unity Dev", "Hamburg")
        listings = [{"url": "https://jooble.test/x9", "portal": "jooble",
                     "raw_text": "Anzeige", "title": "Unity Dev",
                     "company": "Firma-cd1", "location": "Hamburg"}]
        stats = mcp_api.push_jobs_data(user, listings)
        assert stats == {"inserted": 0, "duplicates_url": 0, "duplicates_content": 1}
        assert storage.list_pending_extraction() == []

    def test_push_jobs_missing_structured_fields_falls_back_to_url_only(self, client):
        user, _pid = _member_with_profile()
        listings = [{"url": "https://m.test/legacy", "portal": "adzuna",
                     "raw_text": "Anzeige ohne strukturierte Felder"}]
        stats = mcp_api.push_jobs_data(user, listings)
        assert stats == {"inserted": 1, "duplicates_url": 0, "duplicates_content": 0}

    def test_push_jobs_rejects_bad_listing(self, client):
        user, _pid = _member_with_profile()
        with pytest.raises(ValueError):
            mcp_api.push_jobs_data(user, [{"url": "ftp://x", "portal": "a", "raw_text": "t"}])
        with pytest.raises(ValueError):
            mcp_api.push_jobs_data(user, [{"url": "https://ok.test", "portal": "a",
                                           "raw_text": ""}])


class TestGetMyVotes:
    def test_scoped_to_token_user_with_job_context(self, client):
        user, pid = _member_with_profile()
        other, other_pid = _member_with_profile("votes-other@test.de")
        fp = _mk_extracted_job("v1", title="Unity Dev")
        storage.add_feedback(pid, fp, "up")
        storage.add_feedback(other_pid, fp, "down")
        out = mcp_api.get_my_votes_data(user)
        assert [p["id"] for p in out["profiles"]] == [pid]
        assert out["profiles"][0]["votes"] == [
            {"vote": "up", "fingerprint": fp, "title": "Unity Dev", "company": "Firma-v1",
             "location": "Hamburg", "remote_flag": "remote", "employment_type": "Festanstellung",
             "requirements": ["C#"], "tech_stack": ["Unity"]}]


class TestApplyMemberInsights:
    def test_rejects_foreign_profile(self, client):
        user, _pid = _member_with_profile()
        _other, other_pid = _member_with_profile("insights-other@test.de")
        with pytest.raises(ValueError, match="geh"):
            mcp_api.apply_member_insights_data(
                user, other_pid, "preference", text="Remote bevorzugt")

    def test_rejects_unknown_kind(self, client):
        user, pid = _member_with_profile()
        with pytest.raises(ValueError, match="kind"):
            mcp_api.apply_member_insights_data(user, pid, "location_boost", text="x")

    def test_preference_appends_to_profile_and_confirms(self, client):
        user, pid = _member_with_profile()
        out = mcp_api.apply_member_insights_data(
            user, pid, "preference", text="Bevorzugt Remote, aber Hamburg ok")
        assert out["status"] == "confirmed"
        profile = storage.get_profile(pid)
        assert "Bevorzugt Remote, aber Hamburg ok" in profile["data"]["preferences"]
        insight = storage.list_insights(pid, status="confirmed")[0]
        assert insight["kind"] == "preference" and insight["source"] == "member"

    def test_weight_updates_criterion_and_rejects_unknown_key(self, client):
        user, pid = _member_with_profile()
        with pytest.raises(ValueError, match="Kriterium"):
            mcp_api.apply_member_insights_data(
                user, pid, "weight", payload={"key": "nicht_da", "new_weight": 4})
        mcp_api.apply_member_insights_data(
            user, pid, "weight", payload={"key": "remote", "new_weight": 2})
        criteria = {c["key"]: c["weight"] for c in storage.list_criteria(pid)}
        assert criteria["remote"] == 2

    def test_triggers_deterministic_rescore_and_touches_reminder(self, client):
        user, pid = _member_with_profile()
        fp = _mk_extracted_job("ins1")
        storage.add_feedback(pid, fp, "up")
        assert storage.learn_reminder_status(pid)["new_votes"] == 1
        mcp_api.apply_member_insights_data(
            user, pid, "weight", payload={"key": "remote", "new_weight": 1})
        assert storage.get_job_score(pid, fp) is not None
        assert storage.learn_reminder_status(pid)["new_votes"] == 0


class TestRescoreQueueAndSparModus:
    def test_get_my_profile_includes_spar_modus_defaults(self, client):
        user, _pid = _member_with_profile("sm1@test.de")
        prof = mcp_api.get_my_profile_data(user)["profiles"][0]
        assert prof["spar_modus"] == {"max_jobs": None, "neighbor_roles": True}

    def test_get_my_profile_includes_persisted_spar_modus(self, client):
        user, _pid = _member_with_profile("sm2@test.de")
        storage.set_spar_modus(user["id"], 25, False)
        prof = mcp_api.get_my_profile_data(user)["profiles"][0]
        assert prof["spar_modus"] == {"max_jobs": 25, "neighbor_roles": False}

    def test_apply_member_insights_enqueues_rescore(self, client):
        user, pid = _member_with_profile("sm3@test.de")
        fp = _mk_extracted_job("rq1")
        storage.upsert_job_score(pid, fp, 6, "alt", "Mittel", {"remote": {"punkte": 6}})
        out = mcp_api.apply_member_insights_data(user, pid, "preference", text="Remote bevorzugt")
        assert out["rescore_queued"] >= 1
        pulled = mcp_api.pull_pending_jobs_data(user)
        assert fp in [j["fingerprint"] for j in pulled["to_rescore"]]
        assert pulled["to_rescore"][0]["profile_id"] == pid

    def test_apply_member_insights_respects_spar_cap(self, client):
        user, pid = _member_with_profile("cap@test.de")
        storage.set_spar_modus(user["id"], 1, True)
        for suf, sc in (("cap_a", 80), ("cap_b", 60), ("cap_c", 45)):
            fp = _mk_extracted_job(suf)
            storage.upsert_job_score(pid, fp, sc, "det", "Vielleicht", {"remote": {"punkte": 5}})
        out = mcp_api.apply_member_insights_data(user, pid, "preference", text="Remote bevorzugt")
        assert out["rescore_queued"] == 1

    def test_pull_pending_to_rescore_empty_without_queue(self, client):
        user, _pid = _member_with_profile("sm4@test.de")
        assert mcp_api.pull_pending_jobs_data(user)["to_rescore"] == []

    def test_push_batch_score_clears_rescore_queue_entry(self, client):
        user, pid = _member_with_profile("sm5@test.de")
        fp = _mk_extracted_job("rq2")
        storage.upsert_job_score(pid, fp, 6, "alt", "Mittel", {"remote": {"punkte": 6}})
        storage.enqueue_member_rescore(pid)
        assert len(storage.list_member_rescore([pid])) == 1
        mcp_api.push_batch_data(user, [{
            "fingerprint": fp,
            "scores": {str(pid): {"veto": None,
                                  "kriterien": {"remote": {"punkte": 9, "grund": "voll remote"}}}},
        }])
        assert storage.list_member_rescore([pid]) == []

    def test_push_batch_bonus_adds_on_top_of_base(self, client):
        user, pid = _member_with_profile("bon1@test.de")
        fp = _mk_extracted_job("bon1")
        storage.upsert_job_score(pid, fp, 50, "det", "Vielleicht", {"remote": {"punkte": 5}})
        storage.enqueue_member_rescore(pid)
        mcp_api.push_batch_data(user, [{
            "fingerprint": fp,
            "scores": {str(pid): {"bonus": 25, "grund": "Freitext exakt getroffen"}}}])
        row = storage.get_job_score(pid, fp)
        assert row["score"] == 75
        assert row["category"] == "Pass"
        assert row["reason"] == "Freitext exakt getroffen"
        assert storage.list_member_rescore([pid]) == []

    def test_push_batch_bonus_clamps_to_100(self, client):
        user, pid = _member_with_profile("bon2@test.de")
        fp = _mk_extracted_job("bon2")
        storage.upsert_job_score(pid, fp, 90, "det", "Pass", {"remote": {"punkte": 9}})
        mcp_api.push_batch_data(user, [{
            "fingerprint": fp, "scores": {str(pid): {"bonus": 30, "grund": "top"}}}])
        assert storage.get_job_score(pid, fp)["score"] == 100

    def test_push_batch_bonus_clamps_to_0(self, client):
        user, pid = _member_with_profile("bon3@test.de")
        fp = _mk_extracted_job("bon3")
        storage.upsert_job_score(pid, fp, 10, "det", "No-Go", {"remote": {"punkte": 1}})
        mcp_api.push_batch_data(user, [{
            "fingerprint": fp, "scores": {str(pid): {"bonus": -20, "grund": "schwach"}}}])
        assert storage.get_job_score(pid, fp)["score"] == 0

    def test_push_batch_bonus_missing_base_treated_as_zero(self, client):
        user, pid = _member_with_profile("bon4@test.de")
        fp = _mk_extracted_job("bon4")  # extrahiert, aber noch kein job_score
        mcp_api.push_batch_data(user, [{
            "fingerprint": fp, "scores": {str(pid): {"bonus": 12, "grund": "ok"}}}])
        assert storage.get_job_score(pid, fp)["score"] == 12

    def test_push_batch_rejects_bonus_out_of_range(self, client):
        user, pid = _member_with_profile("bon5@test.de")
        fp = _mk_extracted_job("bon5")
        with pytest.raises(ValueError):
            mcp_api.push_batch_data(user, [{
                "fingerprint": fp, "scores": {str(pid): {"bonus": 31, "grund": "x"}}}])

    def test_push_batch_rejects_bonus_bool(self, client):
        user, pid = _member_with_profile("bon6@test.de")
        fp = _mk_extracted_job("bon6")
        with pytest.raises(ValueError):
            mcp_api.push_batch_data(user, [{
                "fingerprint": fp, "scores": {str(pid): {"bonus": True, "grund": "x"}}}])

    def test_push_batch_rejects_bonus_with_kriterien(self, client):
        user, pid = _member_with_profile("bon7@test.de")
        fp = _mk_extracted_job("bon7")
        with pytest.raises(ValueError):
            mcp_api.push_batch_data(user, [{
                "fingerprint": fp, "scores": {str(pid): {
                    "bonus": 5, "grund": "x", "kriterien": {"remote": {"punkte": 5}}}}}])


class TestUpdateMyCriteria:
    def test_rejects_foreign_profile(self, client):
        user, _pid = _member_with_profile("uc1@test.de")
        _other, other_pid = _member_with_profile("uc1b@test.de")
        with pytest.raises(ValueError, match="gehört nicht"):
            mcp_api.update_my_criteria_data(user, other_pid, skills=["Unity"])

    def test_rejects_unknown_criteria_key_without_writing(self, client):
        user, pid = _member_with_profile("uc2@test.de")
        with pytest.raises(ValueError, match="Unbekanntes Kriterium"):
            mcp_api.update_my_criteria_data(
                user, pid, skills=["Unity"],
                criteria_weights={"gibt_es_nicht": 3})
        # Ganz-Batch-Ablehnung: auch die gültigen skills wurden NICHT geschrieben
        assert "skills" not in storage.get_profile(pid)["data"]

    def test_rejects_out_of_range_weight(self, client):
        user, pid = _member_with_profile("uc3@test.de")
        with pytest.raises(ValueError, match="0-5"):
            mcp_api.update_my_criteria_data(user, pid, criteria_weights={"remote": 9})

    def test_rejects_non_string_list_entries(self, client):
        user, pid = _member_with_profile("uc4@test.de")
        with pytest.raises(ValueError, match="skills"):
            mcp_api.update_my_criteria_data(user, pid, skills=["ok", 42])

    def test_writes_fields_weights_and_rescores(self, client):
        user, pid = _member_with_profile("uc5@test.de")
        fp = _mk_extracted_job("uc")
        out = mcp_api.update_my_criteria_data(
            user, pid, skills=["Unity", "C#"], target_roles=["Game Developer"],
            criteria_weights={"remote": 2})
        data = storage.get_profile(pid)["data"]
        assert data["skills"] == ["Unity", "C#"]
        assert data["target_roles"] == ["Game Developer"]
        assert storage.list_criteria(pid)[0]["weight"] == 2
        assert out["rescored"] >= 1
        assert storage.get_job_score(pid, fp) is not None

    def test_noop_call_changes_nothing(self, client):
        user, pid = _member_with_profile("uc6@test.de")
        out = mcp_api.update_my_criteria_data(user, pid)
        assert out["updated_fields"] == []


_MCP_HEADERS = {"Accept": "application/json, text/event-stream",
                "Content-Type": "application/json"}


def _rpc(method, rpc_id, params=None):
    return {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params or {}}


class TestMcpTransport:
    def test_mcp_without_token_401(self, client):
        with client:
            resp = client.post("/mcp", json=_rpc("tools/list", 1), headers=_MCP_HEADERS)
        assert resp.status_code == 401

    def test_mcp_exact_path_not_redirected(self, client):
        # Ohne den Pfad-Rewrite in log_pageview käme hier ein 307 auf /mcp/ —
        # hinter Caddy würde der Redirect auf http:// downgraden.
        with client:
            resp = client.post("/mcp", json=_rpc("tools/list", 1), headers=_MCP_HEADERS,
                               follow_redirects=False)
        assert resp.status_code == 401

    def test_mcp_wrong_token_401(self, client):
        with client:
            resp = client.post("/mcp", json=_rpc("tools/list", 1),
                               headers={**_MCP_HEADERS,
                                        "Authorization": "Bearer bob_" + "f" * 48})
        assert resp.status_code == 401

    def test_mcp_tools_list_with_valid_token(self, client, member):
        with client:
            resp = client.post("/mcp", json=_rpc("tools/list", 1),
                               headers={**_MCP_HEADERS,
                                        "Authorization": f"Bearer {member['token']}"})
        assert resp.status_code == 200
        names = {t["name"] for t in resp.json()["result"]["tools"]}
        assert names == {"get_my_profile", "pull_pending_jobs", "push_batch", "push_jobs",
                          "get_my_votes", "apply_member_insights", "update_my_criteria"}

    def test_mcp_tool_call_scoped_to_token_user(self, client, member):
        pid = storage.create_profile("Member-Sicht", {"no_gos": []},
                                     user_id=member["id"])
        storage.save_criteria(pid, [{"key": "remote", "label": "Remote", "weight": 5}])
        storage.create_profile("Fremdes Profil", {"no_gos": []}, user_id=999)
        with client:
            resp = client.post(
                "/mcp",
                json=_rpc("tools/call", 2,
                          {"name": "get_my_profile", "arguments": {}}),
                headers={**_MCP_HEADERS,
                         "Authorization": f"Bearer {member['token']}"})
        assert resp.status_code == 200
        assert "Member-Sicht" in resp.text
        assert "Fremdes Profil" not in resp.text


class TestTokenUi:
    def _login(self, client):
        client.post("/login", data={"email": "owner@test.de", "password": "geheim123"})

    def test_api_token_route_requires_login(self, client):
        resp = client.post("/profiles/api-token", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"

    def test_api_token_shown_once_then_gone(self, client):
        self._login(client)
        resp = client.post("/profiles/api-token")
        assert resp.status_code == 200
        assert "bob_" in resp.text
        resp2 = client.get("/einstellungen")
        assert "bob_" not in resp2.text
        assert "API-Token erzeugen" in resp2.text

    def test_generated_token_works_against_mcp(self, client):
        import re
        self._login(client)
        resp = client.post("/profiles/api-token")
        token = re.search(r"bob_[0-9a-f]{48}", resp.text).group(0)
        assert storage.get_user_by_api_token(token)["email"] == "owner@test.de"
