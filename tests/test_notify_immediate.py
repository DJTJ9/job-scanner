"""Tests für den Sofort-Pass: Score-Schwelle, immediate-Opt-in, Dedup via notified_at."""
from unittest.mock import patch

import pytest

from jobscanner import notify_immediate, storage
from jobscanner.models import Job


@pytest.fixture(autouse=True)
def db(tmp_path):
    storage.init_db(tmp_path / "jobs.db")
    yield
    storage.close()


def _member(email, title, score, immediate=True):
    uid = storage.create_user(email, "pw", role="member")
    pid = storage.create_profile(email, {}, user_id=uid)
    storage.set_notify_pref(uid, {"email_mode": "daily", "immediate": immediate, "inbox": True})
    fp = storage.upsert_job(Job(title=title, company="ACME", location="Hamburg",
                                first_seen="2026-07-20"))
    storage.upsert_job_score(pid, fp, score, "passt", "Pass", {})
    return uid, pid, fp


def test_immediate_mails_strong_match_and_marks():
    uid, pid, fp = _member("m@test.de", "Strong", 92)
    with patch("jobscanner.notify_immediate.mailer.send_immediate_match") as send:
        stats = notify_immediate.run_immediate_notifications()
    assert send.call_count == 1
    assert send.call_args[0][0] == "m@test.de"
    assert stats["emails"] == 1
    assert storage.list_immediate_matches(pid, 90) == []  # gemarkt


def test_immediate_ignores_below_threshold():
    _member("m@test.de", "Weak", 80)
    with patch("jobscanner.notify_immediate.mailer.send_immediate_match") as send:
        notify_immediate.run_immediate_notifications()
    assert send.call_count == 0


def test_immediate_opt_out_skips_mail_but_still_syncs_inbox():
    uid, pid, fp = _member("m@test.de", "Strong", 92, immediate=False)
    with patch("jobscanner.notify_immediate.mailer.send_immediate_match") as send:
        notify_immediate.run_immediate_notifications()
    assert send.call_count == 0
    assert storage.count_unread(uid) == 1  # inbox=True → trotzdem gesynct


def test_immediate_threshold_from_env(monkeypatch):
    monkeypatch.setattr(notify_immediate, "IMMEDIATE_SCORE_THRESHOLD", 95)
    _member("m@test.de", "Ninety", 92)
    with patch("jobscanner.notify_immediate.mailer.send_immediate_match") as send:
        notify_immediate.run_immediate_notifications()
    assert send.call_count == 0
