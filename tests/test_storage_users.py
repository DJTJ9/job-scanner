"""Tests für users-Tabelle, Passwort-Hashing, Owner-Seed und Profil-Isolation."""
import pytest

from jobscanner import storage


@pytest.fixture
def db(tmp_path):
    storage.init_db(tmp_path / "jobs.db")
    yield storage
    storage.close()


def test_create_and_get_user_lowercases_email(db):
    uid = db.create_user("Alice@Example.COM", "pw123", role="member")
    user = db.get_user(uid)
    assert user["email"] == "alice@example.com"
    assert user["role"] == "member"
    assert db.get_user_by_email("ALICE@example.com")["id"] == uid


def test_password_hashed_not_plaintext(db):
    uid = db.create_user("bob@example.com", "geheim")
    user = db.get_user(uid)
    assert user["pw_hash"] != "geheim"
    assert len(user["salt"]) == 32  # 16 bytes hex


def test_verify_password_correct_and_wrong(db):
    db.create_user("carol@example.com", "richtig")
    assert db.verify_password("carol@example.com", "richtig") is not None
    assert db.verify_password("carol@example.com", "falsch") is None
    assert db.verify_password("nobody@example.com", "x") is None


def test_seed_owner_creates_owner_and_backfills_profiles(db):
    pid = db.create_profile("Alt-Profil", {}, user_id=None)
    oid = db.seed_owner("owner@example.com", "ownerpw")
    assert db.get_user(oid)["role"] == "owner"
    assert db.get_profile(pid)["user_id"] == oid


def test_seed_owner_idempotent(db):
    first = db.seed_owner("owner@example.com", "pw")
    second = db.seed_owner("owner@example.com", "pw")
    assert first == second


def test_list_profiles_filters_by_user(db):
    a = db.create_user("a@example.com", "pw")
    b = db.create_user("b@example.com", "pw")
    pa = db.create_profile("A-Profil", {}, user_id=a)
    db.create_profile("B-Profil", {}, user_id=b)
    ids = [p["id"] for p in db.list_profiles(user_id=a)]
    assert ids == [pa]


def test_set_password_changes_hash_and_verify(db):
    uid = db.create_user("dave@example.com", "altpw")
    old_hash = db.get_user(uid)["pw_hash"]
    db.set_password(uid, "neupw")
    new_hash = db.get_user(uid)["pw_hash"]
    assert new_hash != old_hash
    assert db.verify_password("dave@example.com", "neupw") is not None
    assert db.verify_password("dave@example.com", "altpw") is None


def test_set_password_rotates_salt(db):
    uid = db.create_user("erin@example.com", "pw")
    old_salt = db.get_user(uid)["salt"]
    db.set_password(uid, "pw")  # gleiches Passwort, neuer Salt
    assert db.get_user(uid)["salt"] != old_salt


def test_create_user_stores_consent_ip_and_generates_verify_token(db):
    uid = db.create_user("neu@example.com", "pw123456", consent=True, ip="1.2.3.4")
    user = db.get_user(uid)
    assert user["consent_at"] is not None
    assert user["registered_ip"] == "1.2.3.4"
    assert user["email_verified_at"] is None
    assert user["verify_token"]


def test_create_user_without_consent_leaves_consent_at_null(db):
    uid = db.create_user("ohne@example.com", "pw123456")
    user = db.get_user(uid)
    assert user["consent_at"] is None
    assert user["registered_ip"] is None


def test_verify_token_owner_finds_user_and_rejects_unknown_token(db):
    uid = db.create_user("v@example.com", "pw123456")
    token = db.get_user(uid)["verify_token"]
    found = db.verify_token_owner(token)
    assert found["id"] == uid
    assert db.verify_token_owner("nicht-existent") is None
    assert db.verify_token_owner("") is None


def test_mark_email_verified_sets_timestamp_and_clears_token(db):
    uid = db.create_user("m2@example.com", "pw123456")
    db.mark_email_verified(uid)
    user = db.get_user(uid)
    assert user["email_verified_at"] is not None
    assert user["verify_token"] is None


def test_list_registrations_lists_members_only_oldest_first(db):
    db.create_user("owner@example.com", "pw123456", role="owner")
    m1 = db.create_user("m1@example.com", "pw123456", consent=True, ip="9.9.9.9")
    db.mark_email_verified(m1)
    db.create_user("m2@example.com", "pw123456", consent=True, ip="9.9.9.9")
    rows = db.list_registrations()
    assert [r["email"] for r in rows] == ["m1@example.com", "m2@example.com"]
    assert rows[0]["email_verified_at"] is not None
    assert rows[1]["email_verified_at"] is None
    assert rows[0]["registered_ip"] == "9.9.9.9"


def test_create_reset_token_returns_token_for_known_email(db):
    db.create_user("reset@example.com", "pw123456")
    token = db.create_reset_token("reset@example.com")
    assert token
    user = db.get_user_by_reset_token(token)
    assert user is not None
    assert user["email"] == "reset@example.com"


def test_create_reset_token_unknown_email_returns_none(db):
    assert db.create_reset_token("nobody@example.com") is None


def test_get_user_by_reset_token_rejects_unknown_and_empty(db):
    assert db.get_user_by_reset_token("nope") is None
    assert db.get_user_by_reset_token("") is None


def test_clear_reset_token_invalidates(db):
    uid = db.create_user("clear@example.com", "pw123456")
    token = db.create_reset_token("clear@example.com")
    db.clear_reset_token(uid)
    assert db.get_user_by_reset_token(token) is None


def test_request_email_change_sets_pending_and_returns_token(db):
    uid = db.create_user("old@example.com", "pw123456")
    token = db.request_email_change(uid, "new@example.com")
    assert token
    assert db.get_user(uid)["pending_email"] == "new@example.com"
    assert db.get_user(uid)["email"] == "old@example.com"  # alte bleibt aktiv


def test_request_email_change_rejects_taken_email(db):
    db.create_user("taken@example.com", "pw123456")
    uid = db.create_user("me@example.com", "pw123456")
    assert db.request_email_change(uid, "taken@example.com") is None


def test_confirm_email_change_swaps_email_and_verifies(db):
    uid = db.create_user("old2@example.com", "pw123456")
    token = db.request_email_change(uid, "new2@example.com")
    user = db.confirm_email_change(token)
    assert user["email"] == "new2@example.com"
    assert user["email_verified_at"] is not None
    assert user["pending_email"] is None
    assert user["pending_email_token"] is None
    assert db.get_user_by_email("new2@example.com") is not None


def test_confirm_email_change_rejects_unknown_token(db):
    assert db.confirm_email_change("nope") is None
    assert db.confirm_email_change("") is None


def test_delete_user_removes_user_and_profiles(db):
    uid = db.create_user("del@example.com", "pw123456")
    pid = db.create_profile("Testprofil", {}, user_id=uid)
    db.delete_user(uid)
    assert db.get_user(uid) is None
    assert db.list_profiles(user_id=uid) == []
    # Row in profiles wirklich weg (Orphan-Check)
    import jobscanner.storage as s
    conn = s._require_conn()
    assert conn.execute("SELECT COUNT(*) FROM profiles WHERE id = ?", (pid,)).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM criteria WHERE profile_id = ?", (pid,)).fetchone()[0] == 0


def test_export_user_data_contains_email_and_profiles_no_secrets(db):
    uid = db.create_user("exp@example.com", "pw123456")
    db.create_profile("Exportprofil", {}, user_id=uid)
    data = db.export_user_data(uid)
    assert data["user"]["email"] == "exp@example.com"
    assert "pw_hash" not in data["user"]
    assert "salt" not in data["user"]
    assert len(data["profiles"]) == 1


def test_admin_list_members_returns_all_users(db):
    db.create_user("m1@example.com", "pw123456")
    db.create_user("m2@example.com", "pw123456")
    members = db.admin_list_members()
    emails = {m["email"] for m in members}
    assert {"m1@example.com", "m2@example.com"} <= emails
    assert all("email_verified_at" in m and "role" in m for m in members)
