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


def _activate(db, url="https://foo.de", typ="career_page"):
    pid = storage.create_custom_portal(url, typ, db)
    storage.save_check_result(pid, {"compatible": True})
    storage.activate_custom_portal(pid)
    return pid


def test_deactivate_active_sets_inactive(db):
    pid = _activate(db)
    storage.deactivate_custom_portal(pid)
    assert storage.get_custom_portal(pid)["status"] == "inactive"


def test_deactivate_only_touches_active(db):
    pid = storage.create_custom_portal("https://foo.de", "career_page", db)
    storage.save_check_result(pid, {"compatible": True})  # status='compatible'
    storage.deactivate_custom_portal(pid)
    assert storage.get_custom_portal(pid)["status"] == "compatible"


def test_reactivate_inactive_sets_active(db):
    pid = _activate(db)
    storage.deactivate_custom_portal(pid)
    storage.activate_custom_portal(pid)
    assert storage.get_custom_portal(pid)["status"] == "active"


def test_inactive_falls_out_of_scannable(db):
    pid = _activate(db)
    storage.deactivate_custom_portal(pid)
    assert all(cp["id"] != pid for cp in storage.list_scannable_custom_portals())


def test_soft_delete_sets_deleted_and_hides_from_default_list(db):
    pid = _activate(db)
    storage.soft_delete_custom_portal(pid)
    assert storage.get_custom_portal(pid)["status"] == "deleted"
    assert all(p["id"] != pid for p in storage.list_custom_portals())
    # explizit weiterhin abrufbar (auditierbar)
    assert any(p["id"] == pid for p in storage.list_custom_portals(status="deleted"))


def test_soft_delete_falls_out_of_scannable(db):
    pid = _activate(db)
    storage.soft_delete_custom_portal(pid)
    assert all(cp["id"] != pid for cp in storage.list_scannable_custom_portals())


def test_migration_rebuild_allows_new_status_on_legacy_schema(tmp_path):
    import sqlite3
    dbfile = tmp_path / "legacy.db"
    conn = sqlite3.connect(dbfile)
    conn.executescript(
        """CREATE TABLE custom_portals (
            id INTEGER PRIMARY KEY, url TEXT NOT NULL,
            typ TEXT NOT NULL CHECK (typ IN ('career_page','portal')),
            search_url_template TEXT, detail_url_pattern TEXT,
            submitted_by INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending_check' CHECK (status IN
                ('pending_check','compatible','needs_firecrawl_pending','active','rejected')),
            firecrawl_needed INTEGER DEFAULT 0, check_ergebnis_json TEXT,
            created_at TEXT NOT NULL, activated_at TEXT);
        INSERT INTO custom_portals (id, url, typ, submitted_by, status, created_at)
            VALUES (1, 'https://legacy.de', 'career_page', 1, 'active', datetime('now'));""")
    conn.commit()
    conn.close()

    storage.init_db(dbfile)  # muss Rebuild ausführen, Daten erhalten
    try:
        storage.deactivate_custom_portal(1)  # 'inactive' war im Alt-CHECK verboten
        assert storage.get_custom_portal(1)["status"] == "inactive"
        assert storage.get_custom_portal(1)["url"] == "https://legacy.de"
    finally:
        storage.close()


def test_migration_second_start_is_noop(tmp_path):
    dbfile = tmp_path / "twice.db"
    storage.init_db(dbfile); storage.close()
    storage.init_db(dbfile)  # String matcht schon → kein zweiter Rebuild, kein Fehler
    try:
        assert storage.list_custom_portals() == []
    finally:
        storage.close()


def test_is_global_defaults_false(db):
    pid = storage.create_custom_portal("https://foo.de/karriere", "career_page", db)
    assert storage.get_custom_portal(pid)["is_global"] is False


def test_create_with_is_global_true_roundtrips(db):
    pid = storage.create_custom_portal(
        "https://studio.de/jobs", "career_page", db, is_global=True)
    assert storage.get_custom_portal(pid)["is_global"] is True
    assert any(p["is_global"] for p in storage.list_custom_portals())
