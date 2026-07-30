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


def _user_with_profile(email="m@test.de"):
    uid = storage.create_user(email, "pw", role="member")
    pid = storage.create_profile(email, {}, user_id=uid)
    return uid, pid


def test_sync_inbox_inserts_pass_matches_idempotent():
    uid, pid = _user_with_profile()
    fp = _pass_match(pid, "Senior Unity", 92)
    assert storage.sync_inbox_notifications(pid) == 1
    assert storage.sync_inbox_notifications(pid) == 0  # INSERT OR IGNORE
    assert storage.count_unread(uid) == 1


def test_sync_inbox_skips_nogo():
    uid, pid = _user_with_profile()
    fp = storage.upsert_job(_job(fp_title="No-Go"))
    storage.upsert_job_score(pid, fp, 10, "nö", "No-Go", {})
    storage.sync_inbox_notifications(pid)
    assert storage.count_unread(uid) == 0


def test_list_inbox_returns_rows_with_read_state_and_url():
    uid, pid = _user_with_profile()
    _pass_match(pid, "Senior Unity", 92)
    storage.sync_inbox_notifications(pid)
    rows = storage.list_inbox(uid)
    assert len(rows) == 1
    r = rows[0]
    assert r["title"] == "Senior Unity" and r["company"] == "ACME"
    assert r["score"] == 92 and r["read_at"] is None
    assert "url" in r and "created_at" in r


def test_mark_inbox_read_clears_unread():
    uid, pid = _user_with_profile()
    _pass_match(pid, "Senior Unity", 92)
    storage.sync_inbox_notifications(pid)
    assert storage.mark_inbox_read(uid) == 1
    assert storage.count_unread(uid) == 0
    assert storage.list_inbox(uid)[0]["read_at"] is not None


def test_inbox_scoped_per_user():
    uid_a, pid_a = _user_with_profile("a@test.de")
    uid_b, pid_b = _user_with_profile("b@test.de")
    fp = storage.upsert_job(_job(fp_title="Shared"))
    storage.upsert_job_score(pid_a, fp, 92, "gut", "Pass", {})
    storage.upsert_job_score(pid_b, fp, 92, "gut", "Pass", {})
    storage.sync_inbox_notifications(pid_a)
    assert storage.count_unread(uid_a) == 1
    assert storage.count_unread(uid_b) == 0


def test_list_immediate_matches_threshold_and_unnotified():
    uid, pid = _user_with_profile()
    fp_hi = _pass_match(pid, "Strong", 92)
    _pass_match(pid, "Weak", 80)
    rows = storage.list_immediate_matches(pid, 90)
    assert [r["fingerprint"] for r in rows] == [fp_hi]
    storage.mark_notified(pid, [fp_hi])
    assert storage.list_immediate_matches(pid, 90) == []


def _pass_job(pid, title, score, language="", location="Hamburg"):
    fp = storage.upsert_job(
        Job(title=title, company="ACME", location=location,
            language=language, first_seen="2026-07-20"))
    storage.upsert_job_score(pid, fp, score, "passt", "Pass", {})
    return fp


def _member_profile(spar, email="m@test.de"):
    uid = storage.create_user(email, "pw", role="member")
    pid = storage.create_profile(email, {"spar_modus": spar}, user_id=uid)
    return uid, pid


def test_sync_inbox_language_filter_excludes_out_of_scope():
    uid, pid = _member_profile({"languages": ["de"], "locations": []})
    _pass_job(pid, "Deutscher Job", 90, language="de")
    _pass_job(pid, "English Job", 88, language="en")
    storage.sync_inbox_notifications(pid)
    titles = [r["title"] for r in storage.list_inbox(uid)]
    assert titles == ["Deutscher Job"]


def test_sync_inbox_location_substring_filter():
    uid, pid = _member_profile({"languages": [], "locations": ["Hamburg"]})
    _pass_job(pid, "HH Job", 90, location="Hamburg (remote)")
    _pass_job(pid, "Berlin Job", 88, location="Berlin")
    storage.sync_inbox_notifications(pid)
    titles = [r["title"] for r in storage.list_inbox(uid)]
    assert titles == ["HH Job"]


def test_sync_inbox_no_filter_when_scope_empty():
    uid, pid = _member_profile({"languages": [], "locations": []})
    _pass_job(pid, "DE Job", 90, language="de", location="Hamburg")
    _pass_job(pid, "EN US Job", 88, language="en", location="Seattle")
    storage.sync_inbox_notifications(pid)
    assert storage.count_unread(uid) == 2


def test_sync_inbox_prunes_out_of_scope_existing_row():
    uid, pid = _member_profile({"languages": [], "locations": []})
    _pass_job(pid, "EN Job", 88, language="en")
    storage.sync_inbox_notifications(pid)
    assert storage.count_unread(uid) == 1
    # Scope auf de einengen → EN-Zeile muss beim Re-Sync verschwinden
    storage.set_spar_modus(uid, None, True, locations=[], languages=["de"])
    storage.sync_inbox_notifications(pid)
    assert storage.count_unread(uid) == 0
    assert storage.list_inbox(uid) == []


def test_sync_inbox_keeps_in_scope_and_inserts_new_returns_count():
    uid, pid = _member_profile({"languages": ["de"], "locations": []})
    _pass_job(pid, "Erst", 90, language="de")
    assert storage.sync_inbox_notifications(pid) == 1
    _pass_job(pid, "Zweit", 85, language="de")
    assert storage.sync_inbox_notifications(pid) == 1  # nur der neue zählt
    titles = {r["title"] for r in storage.list_inbox(uid)}
    assert titles == {"Erst", "Zweit"}
