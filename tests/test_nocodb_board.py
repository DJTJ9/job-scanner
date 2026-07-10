"""Gemockte Tests für nocodb_board — Live-Verhalten deckt der E2E-Task ab."""
import pytest

import jobscanner.nocodb_board as board
from jobscanner.models import Job


class FakeResponse:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture(autouse=True)
def creds(monkeypatch):
    monkeypatch.setenv("NOCODB_API_URL", "https://nocodb.test")
    monkeypatch.setenv("NOCODB_API_TOKEN", "test-token")
    monkeypatch.setenv("NOCODB_BASE_ID", "base123")


def test_ensure_table_reuses_existing(monkeypatch):
    monkeypatch.setattr(board.requests, "get", lambda url, headers=None: FakeResponse(
        {"list": [{"id": "tbl_existing", "title": "Job Scanner Jobs"}]}))
    monkeypatch.setattr(board.requests, "post",
                        lambda *a, **k: pytest.fail("darf bei vorhandener Tabelle nicht posten"))
    assert board.ensure_table() == "tbl_existing"


def test_ensure_table_creates_when_missing(monkeypatch):
    posted = {}
    monkeypatch.setattr(board.requests, "get", lambda url, headers=None: FakeResponse({"list": []}))

    def fake_post(url, headers=None, json=None):
        posted["url"] = url
        posted["payload"] = json
        return FakeResponse({"id": "tbl_new"})

    monkeypatch.setattr(board.requests, "post", fake_post)
    assert board.ensure_table() == "tbl_new"
    assert posted["url"] == "https://nocodb.test/api/v1/db/meta/projects/base123/tables"
    assert posted["payload"]["title"] == "Job Scanner Jobs"
    status_col = next(c for c in posted["payload"]["columns"] if c["title"] == "Status")
    assert status_col["dtxp"] == "'neu','interessant','beworben','interview','abgelehnt'"


def test_push_job_posts_record_and_returns_id(monkeypatch):
    monkeypatch.setattr(board, "ensure_table", lambda: "tbl1")
    captured = {}

    def fake_post(url, headers=None, json=None):
        captured["url"] = url
        captured["payload"] = json
        return FakeResponse({"Id": 42})

    monkeypatch.setattr(board.requests, "post", fake_post)
    job = Job(
        title="Unity Developer", company="ACME", location="Hamburg",
        sources=[{"portal": "indeed", "url": "https://indeed.test/1", "found_at": "2026-07-10"}],
        first_seen="2026-07-10", last_seen="2026-07-10",
    )
    assert board.push_job(job) == 42
    assert captured["url"] == "https://nocodb.test/api/v2/tables/tbl1/records"
    assert captured["payload"]["Title"] == "Unity Developer"
    assert captured["payload"]["Quellen"] == "indeed: https://indeed.test/1"
    assert "Score" not in captured["payload"]  # None-Werte werden weggelassen


def test_missing_credentials_raise(monkeypatch):
    monkeypatch.setattr(board, "ENV_FILE", board.Path("/nonexistent/.env"))
    monkeypatch.delenv("NOCODB_API_URL")
    with pytest.raises(RuntimeError, match="NocoDB"):
        board.ensure_table()
