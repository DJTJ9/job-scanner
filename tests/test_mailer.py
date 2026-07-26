from unittest.mock import MagicMock, patch

import pytest

from jobscanner.web import mailer


def test_send_verification_email_raises_when_smtp_not_configured(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    with pytest.raises(RuntimeError, match="SMTP"):
        mailer.send_verification_email("a@b.de", "tok123", "https://job-scanner.thinkshark.de")


def test_send_verification_email_sends_via_smtp(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "bob@example.com")
    monkeypatch.setenv("SMTP_PASS", "geheim")
    monkeypatch.setenv("SMTP_FROM", "bob@example.com")
    mock_smtp = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_smtp) as smtp_cls:
        mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp.__exit__ = MagicMock(return_value=False)
        mailer.send_verification_email("a@b.de", "tok123", "https://job-scanner.thinkshark.de")
    smtp_cls.assert_called_once_with("smtp.example.com", 587)
    mock_smtp.starttls.assert_called_once()
    mock_smtp.login.assert_called_once_with("bob@example.com", "geheim")
    sent_msg = mock_smtp.sendmail.call_args[0][2]
    assert "tok123" in sent_msg
    assert "https://job-scanner.thinkshark.de/verify-email?token=tok123" in sent_msg


def test_send_match_digest_ascii_body_and_recipient(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "bob@example.com")
    monkeypatch.setenv("SMTP_PASS", "geheim")
    monkeypatch.setenv("SMTP_FROM", "bob@example.com")
    rows = [{"title": "Senior Unity", "company": "ACME", "score": 87},
            {"title": "Gruenderjob", "company": "Studio X", "score": 80}]
    mock_smtp = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_smtp):
        mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp.__exit__ = MagicMock(return_value=False)
        mailer.send_match_digest("m@test.de", 42, rows,
                                 "https://job-scanner.thinkshark.de")
    to_addr = mock_smtp.sendmail.call_args[0][1]
    sent_msg = mock_smtp.sendmail.call_args[0][2]
    assert to_addr == ["m@test.de"]
    assert "Senior Unity" in sent_msg
    assert "87" in sent_msg
    assert "https://job-scanner.thinkshark.de/dashboard/42" in sent_msg
    # ASCII-only Body: keine quoted-printable-Eskalation im Link
    assert "=3D" not in sent_msg


def test_send_match_digest_raises_when_smtp_not_configured(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    with pytest.raises(RuntimeError, match="SMTP"):
        mailer.send_match_digest("m@test.de", 1, [{"title": "X", "company": "Y",
                                 "score": 90}], "https://job-scanner.thinkshark.de")


def test_send_password_reset_email_builds_reset_link(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "bob@example.com")
    monkeypatch.setenv("SMTP_PASS", "geheim")
    monkeypatch.setenv("SMTP_FROM", "bob@example.com")
    mock_smtp = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_smtp):
        mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp.__exit__ = MagicMock(return_value=False)
        mailer.send_password_reset_email("u@x.de", "tok123",
                                         "https://job-scanner.thinkshark.de")
    to_addr = mock_smtp.sendmail.call_args[0][1]
    sent_msg = mock_smtp.sendmail.call_args[0][2]
    assert to_addr == ["u@x.de"]
    assert "https://job-scanner.thinkshark.de/reset-password?token=tok123" in sent_msg


def test_send_email_change_verification_builds_confirm_link(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "bob@example.com")
    monkeypatch.setenv("SMTP_PASS", "geheim")
    monkeypatch.setenv("SMTP_FROM", "bob@example.com")
    mock_smtp = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_smtp):
        mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
        mock_smtp.__exit__ = MagicMock(return_value=False)
        mailer.send_email_change_verification("n@x.de", "tok456",
                                              "https://job-scanner.thinkshark.de")
    to_addr = mock_smtp.sendmail.call_args[0][1]
    sent_msg = mock_smtp.sendmail.call_args[0][2]
    assert to_addr == ["n@x.de"]
    assert "https://job-scanner.thinkshark.de/account/email/confirm?token=tok456" in sent_msg
