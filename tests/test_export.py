# tests/test_export.py
"""Tests für Match-Export: CSV/PDF-Builder, /export-Route, Dialog-Präsenz."""
from pathlib import Path

import pytest

from jobscanner import storage
from jobscanner.models import Job
from jobscanner.web import export


def _mk_entry(title="Unity Dev", company="ACME", location="Hamburg",
              score=92, category="Pass", reason="passt gut",
              sources=None, first_seen="2026-07-11"):
    if sources is None:
        sources = [{"portal": "stepstone", "url": "https://example.com/j/1",
                    "found_at": "2026-07-11"}]
    job = Job(title=title, company=company, location=location,
              first_seen=first_seen, sources=sources)
    return {"job": job, "score": score, "reason": reason, "category": category,
            "breakdown": {}, "scored_at": "2026-07-11", "is_ausland": False}


def test_build_csv_bom_header_and_row():
    entry = _mk_entry()
    fp = entry["job"].fingerprint
    data = export.build_csv([entry], {fp})
    assert data.startswith(b"\xef\xbb\xbf")
    lines = data.decode("utf-8-sig").splitlines()
    assert lines[0] == "titel;firma;ort;score;kategorie;begruendung;portal;erstgesehen;link;favorit"
    assert lines[1] == "Unity Dev;ACME;Hamburg;92;Pass;passt gut;stepstone;2026-07-11;https://example.com/j/1;ja"


def test_build_csv_none_score_no_sources_nicht_favorit():
    entry = _mk_entry(score=None, category=None, reason=None, sources=[])
    data = export.build_csv([entry], set())
    row = data.decode("utf-8-sig").splitlines()[1]
    assert row == "Unity Dev;ACME;Hamburg;;;;;2026-07-11;;nein"


def test_build_csv_quotes_semicolon_in_begruendung():
    entry = _mk_entry(reason="gut; aber remote")
    row = export.build_csv([entry], set()).decode("utf-8-sig").splitlines()[1]
    assert '"gut; aber remote"' in row


def test_build_csv_unsafe_scheme_leerer_link():
    entry = _mk_entry(sources=[{"portal": "x", "url": "javascript:alert(1)"}])
    row = export.build_csv([entry], set()).decode("utf-8-sig").splitlines()[1]
    assert "javascript" not in row


def test_build_pdf_magic_bytes_und_meta():
    entry = _mk_entry()
    data = export.build_pdf([entry], {entry["job"].fingerprint},
                            {"quelle": "Alle Matches", "datum": "29.07.2026", "anzahl": 1})
    assert data[:5] == b"%PDF-"
    assert len(data) > 1000  # Fonts eingebettet, echter Inhalt


def test_build_pdf_unicode_und_none_score_robust():
    # TTF-Subset macht Text nicht greppbar — Test sichert: kein Latin-1-Crash
    entry = _mk_entry(title="Sölöist – C++/Qt (m/w/d) „Games“", score=None)
    data = export.build_pdf([entry], set(),
                            {"quelle": "Aktuelle Ansicht (Wartet auf Score)",
                             "datum": "29.07.2026", "anzahl": 1})
    assert data[:5] == b"%PDF-"


def test_build_pdf_leere_liste():
    data = export.build_pdf([], set(),
                            {"quelle": "Nur Favoriten", "datum": "29.07.2026", "anzahl": 0})
    assert data[:5] == b"%PDF-"


from _csrf_client import CSRFTestClient

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


def _owner_pid():
    owner = storage.get_user_by_email("owner@test.de")
    return storage.list_profiles(user_id=owner["id"])[0]["id"]


def _seed_job(pid, title, company, score, favorit=False):
    fp = storage.upsert_job(Job(title=title, company=company, location="Hamburg",
                                first_seen="2026-07-11",
                                sources=[{"portal": "stepstone",
                                          "url": "https://example.com/j/1"}]))
    if score is not None:
        storage.upsert_job_score(pid, fp, score, "grund", "Pass", {})
    if favorit:
        storage.toggle_favorite(pid, fp)
    return fp


def test_export_csv_download_headers(client):
    from datetime import date
    _seed_job(_owner_pid(), "Unity Dev", "ACME", 90, favorit=True)
    resp = client.get("/export?quelle=favoriten&format=csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert (f'filename="bob-matches-favoriten-{date.today().isoformat()}.csv"'
            in resp.headers["content-disposition"])
    assert "Unity Dev" in resp.content.decode("utf-8-sig")


def test_export_pdf_download(client):
    from datetime import date
    _seed_job(_owner_pid(), "Unity Dev", "ACME", 90)
    resp = client.get("/export?quelle=alle&format=pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert (f'filename="bob-matches-alle-{date.today().isoformat()}.pdf"'
            in resp.headers["content-disposition"])
    assert resp.content[:5] == b"%PDF-"


def test_export_ansicht_respektiert_min_score_und_q(client):
    pid = _owner_pid()
    _seed_job(pid, "High Job", "HiCo", 90)
    _seed_job(pid, "Low Job", "LoCo", 40)
    text = client.get("/export?quelle=ansicht&format=csv&tab=aktiv&min_score=70"
                      ).content.decode("utf-8-sig")
    assert "High Job" in text and "Low Job" not in text
    text = client.get("/export?quelle=ansicht&format=csv&tab=aktiv&q=low"
                      ).content.decode("utf-8-sig")
    assert "Low Job" in text and "High Job" not in text


def test_export_alle_ignoriert_filter_und_favoriten_nur_favorisierte(client):
    pid = _owner_pid()
    _seed_job(pid, "High Job", "HiCo", 90, favorit=True)
    _seed_job(pid, "Low Job", "LoCo", 40)
    text = client.get("/export?quelle=alle&format=csv&min_score=70"
                      ).content.decode("utf-8-sig")
    assert "High Job" in text and "Low Job" in text  # min_score wirkt bei alle nicht
    text = client.get("/export?quelle=favoriten&format=csv").content.decode("utf-8-sig")
    assert "High Job" in text and "Low Job" not in text


def test_export_tenant_scoped_fremdes_profil(client):
    pid = _owner_pid()
    fremd_pid = storage.create_profile("Fremd", {"skills": []})
    fp = storage.upsert_job(Job(title="Fremd Job", company="FremdCo", location="Hamburg",
                                first_seen="2026-07-11"))
    storage.upsert_job_score(fremd_pid, fp, 95, "top", "Pass", {})
    storage.toggle_favorite(fremd_pid, fp)
    text = client.get("/export?quelle=favoriten&format=csv").content.decode("utf-8-sig")
    assert "Fremd Job" not in text  # fremde Favoriten bleiben draußen
    row = [z for z in client.get("/export?quelle=alle&format=csv"
                                 ).content.decode("utf-8-sig").splitlines()
           if z.startswith("Fremd Job")]
    assert not row or ";95;" not in row[0]  # fremder Score nie im eigenen Export


def test_export_invalide_params_400_und_anonym_redirect(client, tmp_path):
    assert client.get("/export?quelle=admin&format=csv").status_code == 400
    assert client.get("/export?quelle=alle&format=xlsx").status_code == 400
    anon = CSRFTestClient(create_app(db_path=tmp_path / "jobs.db"))
    resp = anon.get("/export?quelle=alle&format=csv", follow_redirects=False)
    assert resp.status_code in (302, 303)


def test_jobs_seite_hat_export_dialog_mit_ansicht(client):
    resp = client.get("/jobs")
    assert "export-dialog" in resp.text
    assert "⤓ Export" in resp.text
    assert 'value="ansicht"' in resp.text
    assert 'name="min_score"' in resp.text  # hidden fields tragen Filter


def test_favoriten_seite_dialog_favoriten_vorgewaehlt_ohne_ansicht(client):
    resp = client.get("/favoriten")
    assert "export-dialog" in resp.text
    assert 'value="favoriten"\n      checked' in resp.text.replace("\r", "") or \
           'value="favoriten" checked' in resp.text
    assert 'value="ansicht"' not in resp.text


def test_static_src_schneidet_query_und_mappt_auf_static_dir():
    pfad = export._static_src("/static/img/anleitung/01-register.png?v=abc123")
    assert pfad == str(export._STATIC_DIR / "img" / "anleitung" / "01-register.png")
    assert Path(pfad).exists()


def test_static_src_ohne_query_bleibt_gueltig():
    pfad = export._static_src("/static/img/anleitung/01-register.png")
    assert Path(pfad).exists()


def test_static_src_fremde_quelle_wirft_valueerror():
    with pytest.raises(ValueError):
        export._static_src("https://example.com/fremd.png")


def test_build_anleitung_pdf_bettet_bild_ein():
    fragment = (
        '<h2>1 Test</h2><p>Ein Absatz.</p>'
        '<figure class="anl-shot">'
        '<img src="/static/img/anleitung/01-register.png?v=abc123" width="480"'
        ' alt="Registrierungs-Formular">'
        '<figcaption>Bildunterschrift.</figcaption></figure>'
    )
    daten = export.build_anleitung_pdf(fragment, "01.08.2026")
    assert daten[:5] == b"%PDF-"
    assert b"/Subtype /Image" in daten
