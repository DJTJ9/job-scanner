"""Tests für custom_portals-Storage (Portal-Pre-Check-Tool)."""
import pytest

from jobscanner import storage


@pytest.fixture(autouse=True)
def db(tmp_path):
    storage.init_db(tmp_path / "jobs.db")
    uid = storage.create_user("m@test.de", "pw", role="member")
    yield uid
    storage.close()


def test_create_and_get_roundtrip(db):
    pid = storage.create_custom_portal("https://foo.de/karriere", "career_page", db)
    row = storage.get_custom_portal(pid)
    assert row["url"] == "https://foo.de/karriere"
    assert row["typ"] == "career_page"
    assert row["submitted_by"] == db
    assert row["status"] == "pending_check"
    assert row["check_ergebnis"] is None
    assert row["firecrawl_needed"] is False
    assert row["activated_at"] is None


def test_create_portal_typ_stores_search_fields(db):
    pid = storage.create_custom_portal(
        "https://bar.de/jobs", "portal", db,
        search_url_template="https://bar.de/jobs?q={query}",
        detail_url_pattern=r"bar\.de/jobs/\d+")
    row = storage.get_custom_portal(pid)
    assert row["search_url_template"] == "https://bar.de/jobs?q={query}"
    assert row["detail_url_pattern"] == r"bar\.de/jobs/\d+"


def test_save_check_result_compatible_sets_status(db):
    pid = storage.create_custom_portal("https://foo.de", "career_page", db)
    storage.save_check_result(pid, {"rendered": True, "blocked": False,
                                    "structured": True, "compatible": True})
    row = storage.get_custom_portal(pid)
    assert row["status"] == "compatible"
    assert row["check_ergebnis"]["compatible"] is True


def test_save_check_result_incompatible_sets_needs_firecrawl_pending(db):
    pid = storage.create_custom_portal("https://foo.de", "career_page", db)
    storage.save_check_result(pid, {"rendered": True, "blocked": True,
                                    "structured": False, "compatible": False})
    row = storage.get_custom_portal(pid)
    assert row["status"] == "needs_firecrawl_pending"


def test_activate_from_compatible_no_firecrawl_needed(db):
    pid = storage.create_custom_portal("https://foo.de", "career_page", db)
    storage.save_check_result(pid, {"compatible": True})
    storage.activate_custom_portal(pid)
    row = storage.get_custom_portal(pid)
    assert row["status"] == "active"
    assert row["firecrawl_needed"] is False
    assert row["activated_at"] is not None


def test_activate_from_needs_firecrawl_sets_flag(db):
    pid = storage.create_custom_portal("https://foo.de", "career_page", db)
    storage.save_check_result(pid, {"compatible": False})
    storage.activate_custom_portal(pid)
    row = storage.get_custom_portal(pid)
    assert row["status"] == "active"
    assert row["firecrawl_needed"] is True


def test_list_custom_portals_all_and_filtered(db):
    p1 = storage.create_custom_portal("https://a.de", "career_page", db)
    storage.create_custom_portal("https://b.de", "career_page", db)
    storage.save_check_result(p1, {"compatible": True})
    all_rows = storage.list_custom_portals()
    assert len(all_rows) == 2
    compat = storage.list_custom_portals(status="compatible")
    assert len(compat) == 1
    assert compat[0]["url"] == "https://a.de"
