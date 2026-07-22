"""Tests für Favoriten-Storage (Toggle, Set, with_scores/with_titles, Kaskade)."""
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


def test_toggle_favorite_adds_then_removes():
    pid = storage.create_profile("Testi", {"skills": []})
    fp = storage.upsert_job(_mk_job())
    assert storage.toggle_favorite(pid, fp) is True
    assert storage.get_favorites_set(pid) == {fp}
    assert storage.toggle_favorite(pid, fp) is False
    assert storage.get_favorites_set(pid) == set()


def test_toggle_favorite_is_per_profile():
    p1 = storage.create_profile("A", {"skills": []})
    p2 = storage.create_profile("B", {"skills": []})
    fp = storage.upsert_job(_mk_job())
    storage.toggle_favorite(p1, fp)
    assert storage.get_favorites_set(p1) == {fp}
    assert storage.get_favorites_set(p2) == set()


def test_list_favorites_with_scores_filters_to_favorited_score_desc():
    pid = storage.create_profile("Testi", {"skills": []})
    fp_lo = storage.upsert_job(_mk_job(title="Low"))
    fp_hi = storage.upsert_job(_mk_job(title="High", company="Hi"))
    fp_no = storage.upsert_job(_mk_job(title="NotFav", company="No"))
    storage.upsert_job_score(pid, fp_lo, 40, "ok", "Pass", {})
    storage.upsert_job_score(pid, fp_hi, 90, "top", "Pass", {})
    storage.upsert_job_score(pid, fp_no, 99, "top", "Pass", {})
    storage.toggle_favorite(pid, fp_lo)
    storage.toggle_favorite(pid, fp_hi)
    entries = storage.list_favorites_with_scores(pid)
    titles = [e["job"].title for e in entries]
    assert titles == ["High", "Low"]  # Score DESC, NotFav ausgeschlossen


def test_list_favorites_with_titles_newest_first():
    pid = storage.create_profile("Testi", {"skills": []})
    fp1 = storage.upsert_job(_mk_job(title="Erst"))
    fp2 = storage.upsert_job(_mk_job(title="Zuletzt", company="Z"))
    storage.toggle_favorite(pid, fp1)
    storage.toggle_favorite(pid, fp2)
    titles = [r["title"] for r in storage.list_favorites_with_titles(pid)]
    assert titles == ["Zuletzt", "Erst"]


def test_delete_profile_removes_favorites():
    pid = storage.create_profile("Testi", {"skills": []})
    fp = storage.upsert_job(_mk_job())
    storage.toggle_favorite(pid, fp)
    storage.delete_profile(pid)
    pid2 = storage.create_profile("Neu", {"skills": []})
    assert storage.get_favorites_set(pid2) == set()
