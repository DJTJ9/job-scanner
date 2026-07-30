"""Storage-Roundtrip für per-Member Adzuna/Jooble-Keys (UI-Refine D2)."""
import pytest

from jobscanner import storage


@pytest.fixture
def uid(tmp_path):
    storage.init_db(tmp_path / "jobs.db")
    storage.create_user("agg@test.de", "pw", role="member")
    return storage.get_user_by_email("agg@test.de")["id"]


def test_adzuna_roundtrip(uid):
    assert storage.get_adzuna_keys_enc(uid) == (None, None)
    storage.set_adzuna_keys(uid, "enc-id", "enc-key")
    assert storage.get_adzuna_keys_enc(uid) == ("enc-id", "enc-key")
    storage.clear_adzuna_keys(uid)
    assert storage.get_adzuna_keys_enc(uid) == (None, None)


def test_jooble_roundtrip(uid):
    assert storage.get_jooble_key_enc(uid) is None
    storage.set_jooble_key(uid, "enc-jooble")
    assert storage.get_jooble_key_enc(uid) == "enc-jooble"
    storage.clear_jooble_key(uid)
    assert storage.get_jooble_key_enc(uid) is None


def test_unknown_user_returns_none(uid):
    assert storage.get_adzuna_keys_enc(99999) == (None, None)
    assert storage.get_jooble_key_enc(99999) is None


def test_migration_idempotent(tmp_path, uid):
    # zweiter init_db-Lauf auf bestehender DB darf nicht crashen (ALTER-Guards)
    storage.init_db(tmp_path / "jobs.db")
    assert storage.get_adzuna_keys_enc(uid) == (None, None)
