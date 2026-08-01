"""Tests für den Sofort-Pass: Rollen-Gate (nur Owner mailt), Inbox ungated, Bündelung, Dedup via notified_at."""
from unittest.mock import patch

import pytest

from jobscanner import notify_immediate, storage
from jobscanner.models import Job


@pytest.fixture(autouse=True)
def db(tmp_path):
    storage.init_db(tmp_path / "jobs.db")
    yield
    storage.close()


def _member(email, title, score, immediate=True, inbox=True, role="member"):
    uid = storage.create_user(email, "pw", role=role)
    pid = storage.create_profile(email, {}, user_id=uid)
    storage.set_notify_pref(uid, {"email_mode": "daily", "immediate": immediate, "inbox": inbox})
    fp = storage.upsert_job(Job(title=title, company="ACME", location="Hamburg",
                                first_seen="2026-07-20"))
    storage.upsert_job_score(pid, fp, score, "passt", "Pass", {})
    return uid, pid, fp


def _add_match(pid, title, score):
    fp = storage.upsert_job(Job(title=title, company="ACME", location="Hamburg",
                                first_seen="2026-07-20"))
    storage.upsert_job_score(pid, fp, score, "passt", "Pass", {})
    return fp


def test_owner_mails_strong_match_and_marks():
    uid, pid, fp = _member("o@test.de", "Strong", 92, role="owner")
    with patch("jobscanner.notify_immediate.mailer.send_immediate_match") as send:
        stats = notify_immediate.run_immediate_notifications()
    assert send.call_count == 1
    assert send.call_args[0][0] == "o@test.de"
    assert stats["emails"] == 1
    assert storage.list_immediate_matches(pid, 90) == []  # gemarkt


def test_owner_bundles_all_matches_in_single_call():
    uid, pid, fp = _member("o@test.de", "Strong", 92, role="owner")
    _add_match(pid, "Second", 95)
    with patch("jobscanner.notify_immediate.mailer.send_immediate_match") as send:
        notify_immediate.run_immediate_notifications()
    assert send.call_count == 1
    groups_arg = send.call_args[0][1]  # (email, groups, base_url)
    assert len(groups_arg) == 1
    assert len(groups_arg[0]["rows"]) == 2
    assert storage.list_immediate_matches(pid, 90) == []  # alle gemarkt


def test_user_with_two_profiles_gets_one_mail_with_two_groups():
    uid, pid1, _fp = _member("o@test.de", "Strong", 92, role="owner")
    pid2 = storage.create_profile("Audio", {}, user_id=uid)
    _add_match(pid2, "Sound Designer", 91)
    # Pref wird pro User gesetzt, aber pro Profil persistiert — nach dem zweiten
    # Profil erneut schreiben, damit beide Profile immediate=True tragen.
    storage.set_notify_pref(uid, {"email_mode": "daily", "immediate": True, "inbox": True})
    with patch("jobscanner.notify_immediate.mailer.send_immediate_match") as send:
        stats = notify_immediate.run_immediate_notifications()
    assert send.call_count == 1
    assert send.call_args[0][0] == "o@test.de"
    groups = send.call_args[0][1]
    assert len(groups) == 2
    assert [g["profile"] for g in groups] == ["o@test.de", "Audio"]  # ORDER BY id
    assert stats == {"members": 1, "emails": 1, "matches": 2}
    assert storage.list_immediate_matches(pid1, 90) == []  # beide Profile gemarkt
    assert storage.list_immediate_matches(pid2, 90) == []


def test_member_never_mailed_even_with_immediate():
    uid, pid, fp = _member("m@test.de", "Strong", 92, immediate=True, role="member")
    with patch("jobscanner.notify_immediate.mailer.send_immediate_match") as send:
        notify_immediate.run_immediate_notifications()
    assert send.call_count == 0
    assert storage.count_unread(uid) == 1  # Inbox läuft trotzdem


def test_inbox_synced_ungated_even_when_inbox_pref_false():
    uid, pid, fp = _member("m@test.de", "Strong", 92, inbox=False, role="member")
    with patch("jobscanner.notify_immediate.mailer.send_immediate_match"):
        notify_immediate.run_immediate_notifications()
    assert storage.count_unread(uid) == 1  # entkoppelt: inbox=False → trotzdem gesynct


def test_owner_below_threshold_not_mailed():
    _member("o@test.de", "Weak", 80, role="owner")
    with patch("jobscanner.notify_immediate.mailer.send_immediate_match") as send:
        notify_immediate.run_immediate_notifications()
    assert send.call_count == 0


def test_owner_immediate_opt_out_skips_mail_but_still_syncs_inbox():
    uid, pid, fp = _member("o@test.de", "Strong", 92, immediate=False, role="owner")
    with patch("jobscanner.notify_immediate.mailer.send_immediate_match") as send:
        notify_immediate.run_immediate_notifications()
    assert send.call_count == 0
    assert storage.count_unread(uid) == 1


def test_owner_threshold_from_env(monkeypatch):
    monkeypatch.setattr(notify_immediate, "IMMEDIATE_SCORE_THRESHOLD", 95)
    _member("o@test.de", "Ninety", 92, role="owner")
    with patch("jobscanner.notify_immediate.mailer.send_immediate_match") as send:
        notify_immediate.run_immediate_notifications()
    assert send.call_count == 0
