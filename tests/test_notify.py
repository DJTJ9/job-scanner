"""Tests für den Notify-Pass: 1 Digest/Member, Dedup, Opt-out, SMTP-Fehler isoliert."""
from unittest.mock import patch

import pytest

from jobscanner import notify, storage
from jobscanner.models import Job


@pytest.fixture(autouse=True)
def db(tmp_path):
    storage.init_db(tmp_path / "jobs.db")
    yield
    storage.close()


def _member_with_pass(email, title, score, active=True):
    uid = storage.create_user(email, "pw", role="member")
    pid = storage.create_profile(email, {}, user_id=uid)
    fp = storage.upsert_job(Job(title=title, company="ACME", location="Hamburg",
                                first_seen="2026-07-20"))
    storage.upsert_job_score(pid, fp, score, "passt", "Pass", {})
    return uid, pid, fp


def test_one_email_per_member_to_correct_address():
    _member_with_pass("m@test.de", "Senior Unity", 87)
    with patch("jobscanner.notify.mailer.send_match_digest") as send:
        stats = notify.run_notifications()
    assert send.call_count == 1
    assert send.call_args[0][0] == "m@test.de"
    assert stats["emails"] == 1


def test_no_duplicate_after_marked():
    _member_with_pass("m@test.de", "Senior Unity", 87)
    with patch("jobscanner.notify.mailer.send_match_digest"):
        notify.run_notifications()
    with patch("jobscanner.notify.mailer.send_match_digest") as send2:
        stats = notify.run_notifications()
    assert send2.call_count == 0
    assert stats["emails"] == 0


def test_opt_out_suppresses_email_but_still_marks():
    uid, pid, fp = _member_with_pass("m@test.de", "Senior Unity", 87)
    storage.set_notify_pref(uid, False)
    with patch("jobscanner.notify.mailer.send_match_digest") as send:
        notify.run_notifications()
    assert send.call_count == 0
    assert storage.list_unnotified_top_matches(pid) == []


def test_smtp_error_isolated_per_member():
    _member_with_pass("a@test.de", "Job A", 90)
    _member_with_pass("b@test.de", "Job B", 88)
    with patch("jobscanner.notify.mailer.send_match_digest",
               side_effect=[RuntimeError("smtp down"), None]) as send:
        stats = notify.run_notifications()
    assert send.call_count == 2
    assert stats["emails"] == 1
