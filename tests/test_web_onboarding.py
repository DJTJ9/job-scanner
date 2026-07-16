"""Member-Onboarding-Anleitung: profile_exists-Flag, Buttons/Partials, CSS/JS-Reuse."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jobscanner import storage
from jobscanner.web.app import create_app


@pytest.fixture
def owner_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    app = create_app(db_path=tmp_path / "jobs.db")
    c = TestClient(app)
    c.post("/login", data={"email": "owner@test.de", "password": "geheim123"})
    return c


@pytest.fixture
def member_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    app = create_app(db_path=tmp_path / "jobs.db")
    storage.create_user("member@test.de", "pw", role="member")
    c = TestClient(app)
    c.post("/login", data={"email": "member@test.de", "password": "pw"})
    return c


def test_profile_exists_true_for_owner_with_migrated_profile(owner_client):
    resp = owner_client.get("/")
    assert 'data-profile-exists="true"' in resp.text


def test_profile_exists_false_for_member_without_profile(member_client):
    resp = member_client.get("/")
    assert 'data-profile-exists="false"' in resp.text
