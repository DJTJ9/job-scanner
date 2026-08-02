"""Tests für Spar-Modus-Persistenz + member_rescore_queue (Member-Abo-Vollparität)."""
import pytest

from jobscanner import storage
from jobscanner.models import Job


@pytest.fixture(autouse=True)
def db(tmp_path):
    storage.init_db(tmp_path / "jobs.db")
    yield
    storage.close()


def _member_profile(name="P1", email=None):
    uid = storage.create_user(email or f"{name}@test.de", "pw")
    pid = storage.create_profile(name, {}, user_id=uid)
    storage.save_criteria(pid, [{"key": "remote", "label": "Remote", "weight": 4, "sort": 0}])
    storage.confirm_insight(storage.add_insight(pid, "preference", "seed", source="member"), pid)
    return uid, pid


def _extracted_job(suffix="a"):
    job = Job(title=f"Dev {suffix}", company=f"Firma-{suffix}", location="Hamburg",
              remote_flag="remote", employment_type="Festanstellung", language="de",
              salary_text="", requirements=["C#"], tech_stack=["Unity"],
              sources=[{"portal": "test", "url": f"https://t.test/{suffix}"}],
              first_seen="2026-07-18", last_seen="2026-07-18")
    storage.upsert_job(job)
    return job.fingerprint


def test_spar_modus_defaults_when_unset():
    _uid, pid = _member_profile()
    sm = storage.get_spar_modus(storage.get_profile(pid)["data"])
    assert sm == {"max_jobs": None, "neighbor_roles": True,
                  "locations": [], "languages": ["de"]}


def test_set_spar_modus_writes_all_user_profiles():
    uid, pid = _member_profile()
    pid2 = storage.create_profile("P2", {}, user_id=uid)
    assert storage.set_spar_modus(uid, 25, False) == 2
    for p in (pid, pid2):
        sm = storage.get_spar_modus(storage.get_profile(p)["data"])
        assert sm == {"max_jobs": 25, "neighbor_roles": False,
                      "locations": [], "languages": ["de"]}


def test_set_spar_modus_leaves_other_users_untouched():
    uid, _pid = _member_profile("P1")
    _uid2, pid2 = _member_profile("P3", email="other@test.de")
    storage.set_spar_modus(uid, 10, True)
    assert storage.get_spar_modus(storage.get_profile(pid2)["data"])["max_jobs"] is None


def test_enqueue_lists_and_clears_member_rescore():
    _uid, pid = _member_profile()
    fp = _extracted_job()
    storage.upsert_job_score(pid, fp, 7, "ok", "Vielleicht", {"remote": {"punkte": 7}})
    assert storage.enqueue_member_rescore(pid) == 1
    items = storage.list_member_rescore([pid])
    assert len(items) == 1
    assert items[0]["fingerprint"] == fp
    assert items[0]["profile_id"] == pid
    assert "requirements" in items[0] and "tech_stack" in items[0]
    storage.clear_member_rescore(pid, fp)
    assert storage.list_member_rescore([pid]) == []


def test_enqueue_is_idempotent_and_skips_unscored():
    _uid, pid = _member_profile()
    fp = _extracted_job("b")
    storage.upsert_job_score(pid, fp, 5, "ok", "Vielleicht", {"remote": {"punkte": 5}})
    _extracted_job("c")  # extrahiert, aber nie gescort -> kein Rescore-Kandidat
    storage.enqueue_member_rescore(pid)
    assert storage.enqueue_member_rescore(pid) == 0
    assert len(storage.list_member_rescore([pid])) == 1


def test_list_member_rescore_empty_ids():
    assert storage.list_member_rescore([]) == []


def test_set_criterion_weight_by_key():
    _uid, pid = _member_profile()
    storage.set_criterion_weight_by_key(pid, "remote", 1)
    assert storage.list_criteria(pid)[0]["weight"] == 1


def _scored_job(pid, suffix, score, category):
    fp = _extracted_job(suffix)
    storage.upsert_job_score(pid, fp, score, "det", category, {"remote": {"punkte": score // 10}})
    return fp


def test_enqueue_floor_excludes_no_go():
    _uid, pid = _member_profile()
    ok = _scored_job(pid, "ok", 55, "Vielleicht")
    _nogo = _scored_job(pid, "no", 0, "No-Go")
    assert storage.enqueue_member_rescore(pid) == 1
    fps = {i["fingerprint"] for i in storage.list_member_rescore([pid])}
    assert fps == {ok}


def test_enqueue_cap_keeps_top_scores():
    _uid, pid = _member_profile()
    hi = _scored_job(pid, "hi", 80, "Pass")
    mid = _scored_job(pid, "mid", 60, "Vielleicht")
    lo = _scored_job(pid, "lo", 45, "Vielleicht")
    assert storage.enqueue_member_rescore(pid, max_jobs=2) == 2
    fps = {i["fingerprint"] for i in storage.list_member_rescore([pid])}
    assert fps == {hi, mid}
    assert lo not in fps


def test_enqueue_none_is_unbounded():
    _uid, pid = _member_profile()
    for s, suf in ((80, "a"), (60, "b"), (45, "c")):
        _scored_job(pid, suf, s, "Vielleicht")
    assert storage.enqueue_member_rescore(pid, max_jobs=None) == 3


def _extracted_scored_job(pid, suffix, location="Hamburg", language="de"):
    job = Job(title=f"Dev {suffix}", company=f"Firma-{suffix}", location=location,
              remote_flag="remote", employment_type="Festanstellung", language=language,
              salary_text="", requirements=["C#"], tech_stack=["Unity"],
              sources=[{"portal": "test", "url": f"https://t.test/{suffix}"}],
              first_seen="2026-07-18", last_seen="2026-07-18")
    storage.upsert_job(job)
    storage.upsert_job_score(pid, job.fingerprint, 70, "det", "Vielleicht", {"remote": {"punkte": 7}})
    return job.fingerprint


def test_spar_modus_defaults_include_location_language():
    d = storage.get_spar_modus({})
    assert d["locations"] == []
    assert d["languages"] == ["de"]


def test_set_spar_modus_persists_location_language():
    uid, _pid = _member_profile("m", "m@x.de")
    storage.set_spar_modus(uid, 25, True, locations=["Berlin"], languages=["de", "en"])
    d = storage.get_spar_modus(storage.list_profiles()[0]["data"])
    assert d["locations"] == ["Berlin"]
    assert d["languages"] == ["de", "en"]


def test_enqueue_filters_by_language():
    _uid, pid = _member_profile("m", "m@x.de")
    de_fp = _extracted_scored_job(pid, "de", language="de")
    en_fp = _extracted_scored_job(pid, "en", location="Austin, TX", language="en")
    storage.enqueue_member_rescore(pid, languages=["de"])
    queued = {i["fingerprint"] for i in storage.list_member_rescore([pid])}
    assert de_fp in queued and en_fp not in queued


def test_enqueue_filters_by_location_substring():
    _uid, pid = _member_profile("m", "m@x.de")
    ber = _extracted_scored_job(pid, "b", location="Berlin, DE")
    muc = _extracted_scored_job(pid, "m", location="München")
    storage.enqueue_member_rescore(pid, locations=["Berlin"])
    queued = {i["fingerprint"] for i in storage.list_member_rescore([pid])}
    assert ber in queued and muc not in queued


def test_has_confirmed_insight_reflects_confirmed_status():
    uid = storage.create_user("hci@test.de", "pw")
    pid = storage.create_profile("HCI", {}, user_id=uid)
    assert storage.has_confirmed_insight(pid) is False
    iid = storage.add_insight(pid, "preference", "remote bevorzugt", source="member")
    assert storage.has_confirmed_insight(pid) is False  # proposed, nicht confirmed
    storage.confirm_insight(iid, pid)
    assert storage.has_confirmed_insight(pid) is True


def test_enqueue_gated_without_insight_returns_zero():
    uid = storage.create_user("gated@test.de", "pw")
    pid = storage.create_profile("Gated", {}, user_id=uid)
    storage.save_criteria(pid, [{"key": "remote", "label": "Remote", "weight": 4, "sort": 0}])
    fp = _scored_job(pid, "g", 80, "Pass")
    assert storage.enqueue_member_rescore(pid) == 0
    assert storage.list_member_rescore([pid]) == []


def test_enqueue_includes_favorited_no_go():
    _uid, pid = _member_profile("favng", "favng@test.de")
    fp = _scored_job(pid, "fng", 0, "No-Go")
    storage.toggle_favorite(pid, fp)
    assert storage.enqueue_member_rescore(pid) == 1
    assert {i["fingerprint"] for i in storage.list_member_rescore([pid])} == {fp}


def test_enqueue_includes_feedback_no_go():
    _uid, pid = _member_profile("fbng", "fbng@test.de")
    fp = _scored_job(pid, "bng", 0, "No-Go")
    storage.add_feedback(pid, fp, "down")
    assert storage.enqueue_member_rescore(pid) == 1


def test_enqueue_includes_pass_band():
    _uid, pid = _member_profile("passband", "passband@test.de")
    _scored_job(pid, "p", 85, "Pass")
    assert storage.enqueue_member_rescore(pid) == 1


def test_enqueue_member_rescore_nimmt_englische_de_jobs_und_landesnamen():
    _uid, pid = _member_profile()
    job = Job(title="EN DE Job", company="ACME", location="Germany", language="en",
              sources=[{"portal": "jooble", "url": "https://t.test/en-de"}],
              first_seen="2026-08-01", last_seen="2026-08-01")
    storage.upsert_job(job)
    storage.upsert_job_score(pid, job.fingerprint, 80, "passt", "Pass", {})
    assert storage.enqueue_member_rescore(pid, locations=["Hamburg"],
                                          languages=["de"]) == 1
