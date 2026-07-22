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
