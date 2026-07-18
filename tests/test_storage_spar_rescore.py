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
    assert sm == {"max_jobs": None, "neighbor_roles": True}


def test_set_spar_modus_writes_all_user_profiles():
    uid, pid = _member_profile()
    pid2 = storage.create_profile("P2", {}, user_id=uid)
    assert storage.set_spar_modus(uid, 25, False) == 2
    for p in (pid, pid2):
        sm = storage.get_spar_modus(storage.get_profile(p)["data"])
        assert sm == {"max_jobs": 25, "neighbor_roles": False}


def test_set_spar_modus_leaves_other_users_untouched():
    uid, _pid = _member_profile("P1")
    _uid2, pid2 = _member_profile("P3", email="other@test.de")
    storage.set_spar_modus(uid, 10, True)
    assert storage.get_spar_modus(storage.get_profile(pid2)["data"])["max_jobs"] is None


def test_enqueue_lists_and_clears_member_rescore():
    _uid, pid = _member_profile()
    fp = _extracted_job()
    storage.upsert_job_score(pid, fp, 7, "ok", "Gut", {"remote": {"punkte": 7}})
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
    storage.upsert_job_score(pid, fp, 5, "ok", "Mittel", {"remote": {"punkte": 5}})
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
