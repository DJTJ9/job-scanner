"""Texte-Aktualitäts-Audit 2026-07-31: Anleitungen aufs neue Scan-Modell, Datenschutz-Pflichtangaben."""
import pytest
from fastapi.testclient import TestClient

from jobscanner.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    app = create_app(db_path=tmp_path / "jobs.db")
    return TestClient(app)


# --- hilfe.html ---

def test_hilfe_erstbefehl_ist_scan_nicht_rescore(client):
    body = client.get("/hilfe").text
    assert 'data-copy="/bob:bob-scan"' in body
    assert 'data-copy="/bob:bob-rescore"' not in body


def test_hilfe_kein_faq_keys_doppler(client):
    body = client.get("/hilfe").text
    assert body.count("es fehlen Keys") == 0


def test_hilfe_wie_es_weitergeht_nennt_learn(client):
    body = client.get("/hilfe").text
    assert "/bob:bob-learn" in body


# --- anleitung_scan.html ---

def test_scan_anleitung_schritt1_ohne_keys_pflicht(client):
    body = client.get("/anleitung/scan").text
    assert "ohne Keys findet der Scan keine" not in body
    assert "Plugin verbunden" in body


def test_scan_anleitung_keys_panel_optional(client):
    body = client.get("/anleitung/scan").text
    assert "Mehr Portale" in body
    assert "optional" in body.lower()


# --- keys.html ---

def test_keys_seite_framing_optional(client):
    body = client.get("/anleitung/keys").text
    assert "Heim-IP" in body
    assert "optional" in body.lower()


# --- datenschutz.html ---

def test_datenschutz_pflichtangaben(client):
    body = client.get("/datenschutz").text
    assert "keine Weitergabe an Dritte" not in body
    assert "Art. 77" in body
    assert "Cookie" in body
    assert "Benutzername" in body
    assert "Anthropic" in body
    assert "Server-Logs" in body
    assert "Stand:" in body
