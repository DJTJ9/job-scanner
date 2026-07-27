"""Tests für get_home_summary + scan_pushed-Events."""
import pytest

from jobscanner import storage
from jobscanner.models import Job
from jobscanner.web import mcp_api


@pytest.fixture(autouse=True)
def db(tmp_path):
    storage.init_db(tmp_path / "jobs.db")
    yield
    storage.close()


def _mk_job(**overrides) -> Job:
    base = dict(title="Unity Dev", company="ACME", location="Hamburg", first_seen="2026-07-27")
    base.update(overrides)
    return Job(**base)


def test_home_summary_leere_db(tmp_path):
    pid = storage.create_profile("P", {"skills": []})
    s = storage.get_home_summary(pid)
    assert s["new_matches"] == 0
    assert s["score_queue"] == 0
    assert s["favorites_count"] == 0
    assert s["top_matches"] == []
    assert s["vote_count"] == 0
    assert s["last_scan_ts"] is None
    assert s["scan_frisch"] is False
    assert s["jobs_total"] == 0


def test_home_summary_zaehlt_treffer_queue_favoriten_votes():
    pid = storage.create_profile("P", {"skills": []})
    fp_pass = storage.upsert_job(_mk_job(title="Pass-Job"))
    storage.upsert_job_score(pid, fp_pass, 90, "top", "Pass", {})
    fp_unscored = storage.upsert_job(_mk_job(title="Unscored-Job", company="Other"))
    storage.toggle_favorite(pid, fp_pass)
    storage.add_feedback(pid, fp_pass, "up")
    s = storage.get_home_summary(pid)
    assert s["new_matches"] == 1          # Pass + notified_at IS NULL
    assert s["score_queue"] == 1          # fp_unscored hat keinen job_scores-Eintrag
    assert s["favorites_count"] == 1
    assert s["vote_count"] == 1
    assert s["jobs_total"] == 2
    assert s["top_matches"][0]["job"].fingerprint == fp_pass


def test_home_summary_top_matches_max_3_ohne_nogo_und_ausland():
    pid = storage.create_profile("P", {"skills": []})
    for i in range(4):
        fp = storage.upsert_job(_mk_job(title=f"Job {i}", company=f"C{i}"))
        storage.upsert_job_score(pid, fp, 50 + i, "ok", "Pass", {})
    fp_nogo = storage.upsert_job(_mk_job(title="NoGo", company="NG"))
    storage.upsert_job_score(pid, fp_nogo, 99, "nogo", "No-Go", {})
    s = storage.get_home_summary(pid)
    assert len(s["top_matches"]) == 3
    titles = [e["job"].title for e in s["top_matches"]]
    assert "NoGo" not in titles
    assert titles[0] == "Job 3"           # höchster Score zuerst


def test_scan_pushed_event_setzt_last_scan():
    pid = storage.create_profile("P", {"skills": []})
    storage.log_event("scan_pushed", meta={"source": "server", "new": 5})
    s = storage.get_home_summary(pid)
    assert s["last_scan_ts"] is not None
    assert s["scan_frisch"] is True       # gerade eben → < 24h


def test_push_jobs_data_loggt_scan_pushed():
    uid = storage.create_user("m@test.de", "geheim123")
    user = storage.get_user(uid)
    mcp_api.push_jobs_data(user, [{
        "url": "https://example.com/job/1", "portal": "stepstone",
        "raw_text": "Unity Developer gesucht"}])
    conn = storage._require_conn()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM events WHERE event_type = 'scan_pushed'").fetchone()
    assert row["n"] == 1
