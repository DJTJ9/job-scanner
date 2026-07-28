"""Tests für expired-Favoriten: include_expired-Param + Aktiv-vor-Expired-Sortierung."""
import pytest

from jobscanner import storage
from jobscanner.models import Job


@pytest.fixture(autouse=True)
def db(tmp_path):
    storage.init_db(tmp_path / "jobs.db")
    yield
    storage.close()


def _mk_job(**overrides) -> Job:
    base = dict(title="Unity Dev", company="ACME", location="Hamburg", first_seen="2026-07-11")
    base.update(overrides)
    return Job(**base)


def test_list_jobs_excludes_expired_by_default():
    pid = storage.create_profile("Testi", {"skills": []})
    fp_active = storage.upsert_job(_mk_job(title="Aktiv", status="neu"))
    fp_expired = storage.upsert_job(_mk_job(title="Abgelaufen", company="Ex", status="expired"))
    storage.upsert_job_score(pid, fp_active, 80, "ok", "Pass", {})
    storage.upsert_job_score(pid, fp_expired, 90, "top", "Pass", {})

    default_titles = [e["job"].title for e in storage.list_jobs_with_scores(pid)]
    assert default_titles == ["Aktiv"]

    all_titles = {e["job"].title for e in storage.list_jobs_with_scores(pid, include_expired=True)}
    assert all_titles == {"Aktiv", "Abgelaufen"}


def test_favorites_active_before_expired():
    pid = storage.create_profile("Testi", {"skills": []})
    fp_active_lo = storage.upsert_job(_mk_job(title="AktivLow", company="AL", status="neu"))
    fp_expired_hi = storage.upsert_job(_mk_job(title="ExpiredHigh", company="EH", status="expired"))
    fp_active_hi = storage.upsert_job(_mk_job(title="AktivHigh", company="AH", status="neu"))
    storage.upsert_job_score(pid, fp_active_lo, 40, "ok", "Pass", {})
    storage.upsert_job_score(pid, fp_expired_hi, 95, "top", "Pass", {})
    storage.upsert_job_score(pid, fp_active_hi, 88, "gut", "Pass", {})
    storage.toggle_favorite(pid, fp_active_lo)
    storage.toggle_favorite(pid, fp_expired_hi)
    storage.toggle_favorite(pid, fp_active_hi)

    entries = storage.list_favorites_with_scores(pid)
    titles = [e["job"].title for e in entries]
    assert titles == ["AktivHigh", "AktivLow", "ExpiredHigh"]
    assert entries[-1]["job"].status == "expired"
