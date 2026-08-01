# tests/test_web_anleitung_voll.py
"""C5 — Die ausführliche Anleitung: PDF-Builder, beide Routen, Hilfe-Umbau."""
import pytest
from _csrf_client import CSRFTestClient

from jobscanner.web import export
from jobscanner.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSCANNER_WEB_PASSWORD", "geheim123")
    monkeypatch.setenv("JOBSCANNER_SESSION_SECRET", "test-secret-key")
    monkeypatch.setenv("JOBSCANNER_OWNER_EMAIL", "owner@test.de")
    app = create_app(db_path=tmp_path / "jobs.db")
    c = CSRFTestClient(app)
    c.post("/login", data={"email": "owner@test.de", "password": "geheim123"})
    return c


def test_build_anleitung_pdf_magic_bytes():
    data = export.build_anleitung_pdf("<h2>1 Test</h2><p>Kurz.</p>", "01.08.2026")
    assert data.startswith(b"%PDF")
    assert len(data) > 5000                      # Titelseite + TOC + Inhalt


def test_build_anleitung_pdf_umlaute_listen_code_tabelle():
    html = ('<h2>1 Größe</h2><p>Umlaute: äöüß</p>'
            '<ul><li>ä<ul><li>tief</li></ul></li></ul>'
            '<pre><code>echo "Ümlaut"</code></pre>'
            '<table><thead><tr><th>A</th><th>B</th></tr></thead>'
            '<tbody><tr><td>Größe</td><td>1</td></tr></tbody></table>')
    data = export.build_anleitung_pdf(html, "01.08.2026")
    assert data.startswith(b"%PDF")


def test_build_anleitung_pdf_leeres_fragment_robust():
    data = export.build_anleitung_pdf("", "01.08.2026")
    assert data.startswith(b"%PDF")


def test_kapitelliste_deckt_vier_kapitel():
    assert [nr for nr, _ in export._KAPITEL] == ["1", "2", "3", "4"]
