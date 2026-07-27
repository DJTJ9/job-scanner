"""Tests für Web-Settings-Loader."""
from jobscanner import config


def test_load_web_settings_reads_env(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "_ENV_FILE", tmp_path / "none.env")
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "testpw123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "testsecret")
    monkeypatch.setenv("JOBSCANNER_WEB_PORT", "9999")
    monkeypatch.delenv("JOBSCANNER_INVITE_CODE", raising=False)
    monkeypatch.delenv("JOBSCANNER_OWNER_EMAIL", raising=False)
    settings = config.load_web_settings()
    assert settings == {
        "password": "testpw123",
        "session_secret": "testsecret",
        "port": 9999,
        "invite_code": "",
        "owner_email": "",
        "base_url": "https://job-scanner.thinkshark.de",
        "smtp_host": "",
        "smtp_port": 587,
        "smtp_user": "",
        "smtp_pass": "",
        "smtp_from": "",
    }


def test_load_web_settings_defaults_port_8010(monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "x")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "y")
    monkeypatch.delenv("JOBSCANNER_WEB_PORT", raising=False)
    assert config.load_web_settings()["port"] == 8010


def test_load_web_settings_includes_invite_and_owner(monkeypatch):
    monkeypatch.setenv("JOBSCANNER_INVITE_CODE", "geheim-invite")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@thinkshark.de")
    s = config.load_web_settings()
    assert s["invite_code"] == "geheim-invite"
    assert s["owner_email"] == "owner@thinkshark.de"
