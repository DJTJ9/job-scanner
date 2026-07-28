"""Tests für Notify-Storage: notified_at-Marker + Notify-Pref."""
import pytest

from jobscanner import storage
from jobscanner.models import Job


@pytest.fixture(autouse=True)
def db(tmp_path):
    storage.init_db(tmp_path / "jobs.db")
    yield
    storage.close()


def _job(fp_title="Unity Dev", company="ACME", location="Hamburg"):
    return Job(title=fp_title, company=company, location=location, first_seen="2026-07-20")


def _pass_match(pid, title, score):
    fp = storage.upsert_job(_job(fp_title=title))
    storage.upsert_job_score(pid, fp, score, "passt", "Pass", {})
    return fp


def test_list_unnotified_returns_only_pass_and_null_notified():
    pid = storage.create_profile("Testi", {})
    fp_pass = _pass_match(pid, "Senior Unity", 87)
    fp_nogo = storage.upsert_job(_job(fp_title="No-Go Job"))
    storage.upsert_job_score(pid, fp_nogo, 10, "nö", "No-Go", {})
    rows = storage.list_unnotified_top_matches(pid)
    assert [r["fingerprint"] for r in rows] == [fp_pass]
    assert rows[0]["title"] == "Senior Unity"
    assert rows[0]["company"] == "ACME"
    assert rows[0]["score"] == 87


def test_mark_notified_removes_from_unnotified():
    pid = storage.create_profile("Testi", {})
    fp = _pass_match(pid, "Senior Unity", 87)
    storage.mark_notified(pid, [fp])
    assert storage.list_unnotified_top_matches(pid) == []


def test_mark_notified_is_scoped_per_profile():
    pid1 = storage.create_profile("P1", {})
    pid2 = storage.create_profile("P2", {})
    fp = storage.upsert_job(_job(fp_title="Shared Job"))
    storage.upsert_job_score(pid1, fp, 90, "gut", "Pass", {})
    storage.upsert_job_score(pid2, fp, 90, "gut", "Pass", {})
    storage.mark_notified(pid1, [fp])
    assert storage.list_unnotified_top_matches(pid1) == []
    assert len(storage.list_unnotified_top_matches(pid2)) == 1


def test_mark_notified_empty_list_is_noop():
    pid = storage.create_profile("Testi", {})
    _pass_match(pid, "Senior Unity", 87)
    storage.mark_notified(pid, [])
    assert len(storage.list_unnotified_top_matches(pid)) == 1


def test_get_notify_pref_default_new_shape():
    assert storage.get_notify_pref({}) == {
        "email_mode": "daily", "immediate": True, "inbox": True}


def test_get_notify_pref_reads_new_shape():
    stored = {"notifications": {"email_mode": "weekly", "immediate": False, "inbox": True}}
    assert storage.get_notify_pref(stored) == {
        "email_mode": "weekly", "immediate": False, "inbox": True}


def test_get_notify_pref_lazy_migrates_legacy_true():
    assert storage.get_notify_pref({"notifications": {"email": True}}) == {
        "email_mode": "daily", "immediate": True, "inbox": True}


def test_get_notify_pref_lazy_migrates_legacy_false():
    pref = storage.get_notify_pref({"notifications": {"email": False}})
    assert pref["email_mode"] == "off"
    assert "email" not in pref


def test_get_notify_pref_fills_missing_keys():
    pref = storage.get_notify_pref({"notifications": {"email_mode": "weekly"}})
    assert pref == {"email_mode": "weekly", "immediate": True, "inbox": True}


def test_set_notify_pref_persists_new_shape_to_all_profiles():
    uid = storage.create_user("m@test.de", "pw", role="member")
    storage.create_profile("A", {}, user_id=uid)
    storage.create_profile("B", {}, user_id=uid)
    pref = {"email_mode": "weekly", "immediate": False, "inbox": True}
    count = storage.set_notify_pref(uid, pref)
    assert count == 2
    for p in storage.list_profiles(user_id=uid):
        assert storage.get_notify_pref(p["data"]) == pref
