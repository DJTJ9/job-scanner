"""Tests für Event-Logging + Metrik-Aggregation (events-Tabelle)."""
import pytest

from jobscanner import storage


@pytest.fixture(autouse=True)
def db(tmp_path):
    storage.init_db(tmp_path / "jobs.db")
    yield
    storage.close()


def test_log_event_inserts_row_with_meta():
    storage.log_event("pageview", meta={"path": "/dashboard/1"})
    conn = storage._require_conn()
    row = conn.execute("SELECT * FROM events").fetchone()
    assert row["event_type"] == "pageview"
    assert row["meta_json"] == '{"path": "/dashboard/1"}'
    assert row["ts"] > 0


def test_log_event_defaults_user_id_none():
    storage.log_event("pageview")
    conn = storage._require_conn()
    row = conn.execute("SELECT user_id FROM events").fetchone()
    assert row["user_id"] is None


def test_get_metrics_summary_counts_active_members_by_role():
    owner_id = storage.create_user("owner@test.de", "pw", role="owner")
    member_id = storage.create_user("member@test.de", "pw", role="member")
    storage.log_event("pageview", user_id=owner_id)
    storage.log_event("pageview", user_id=member_id)
    metrics = storage.get_metrics_summary()
    assert metrics["active_members"] == 1


def test_get_metrics_summary_excludes_events_outside_window():
    member_id = storage.create_user("member@test.de", "pw", role="member")
    storage.log_event("pageview", user_id=member_id)
    conn = storage._require_conn()
    conn.execute("UPDATE events SET ts = strftime('%s', 'now', '-10 days') WHERE user_id = ?",
                 (member_id,))
    conn.commit()
    metrics = storage.get_metrics_summary(days=7)
    assert metrics["active_members"] == 0


def test_get_metrics_summary_onboarding_completion_rate():
    storage.log_event("onboarding_start")
    storage.log_event("onboarding_start")
    storage.log_event("profil_erstellt")
    metrics = storage.get_metrics_summary()
    assert metrics["onboarding_completion_rate"] == 50
    assert metrics["funnel_counts"] == {
        "onboarding_start": 2, "profil_erstellt": 1, "feedback_gegeben": 0}


def test_get_metrics_summary_onboarding_completion_rate_zero_when_no_starts():
    metrics = storage.get_metrics_summary()
    assert metrics["onboarding_completion_rate"] == 0


def test_get_metrics_summary_sessions_today_counts_pageviews_today_only():
    storage.log_event("pageview")
    conn = storage._require_conn()
    conn.execute("UPDATE events SET ts = strftime('%s', 'now', '-2 days')")
    conn.commit()
    storage.log_event("pageview")
    metrics = storage.get_metrics_summary()
    assert metrics["sessions_today"] == 1


def test_get_daily_event_counts_fills_gaps_with_zero_oldest_first():
    storage.log_event("pageview")
    counts = storage.get_daily_event_counts(days=3)
    assert len(counts) == 3
    assert counts[0]["day"] < counts[1]["day"] < counts[2]["day"]
    assert counts[-1]["count"] == 1
    assert counts[0]["count"] == 0
