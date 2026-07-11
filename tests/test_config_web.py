"""Tests für Web-Settings-Loader."""
from jobscanner import config


def test_load_web_settings_reads_env(monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "testpw123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "testsecret")
    monkeypatch.setenv("JOBSCANNER_WEB_PORT", "9999")
    settings = config.load_web_settings()
    assert settings == {"password": "testpw123", "session_secret": "testsecret", "port": 9999}


def test_load_web_settings_defaults_port_8010(monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "x")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "y")
    monkeypatch.delenv("JOBSCANNER_WEB_PORT", raising=False)
    assert config.load_web_settings()["port"] == 8010
