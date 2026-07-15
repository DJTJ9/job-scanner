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
