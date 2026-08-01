# jobscanner/web/export.py
"""Match-Export als CSV/PDF. Reine Builder ohne Request-Kontext — testbar,
hält app.py (1518 Zeilen) schlank. Entry-Shape = storage.list_jobs_with_scores."""
import csv
import io
from pathlib import Path

from fpdf import FPDF
from fpdf.fonts import TextStyle

CSV_SPALTEN = ["titel", "firma", "ort", "score", "kategorie", "begruendung",
               "portal", "erstgesehen", "link", "favorit"]

_FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
_TIEFE = (10, 22, 40)      # --tiefe #0A1628 als Tintenfarbe
_SIGNAL = (245, 166, 35)   # --signal #F5A623 für Score-Balken/Links
_GRAU = (110, 122, 140)


def _quelle_url(job) -> str:
    """Erste Quell-URL, nur http(s) — gleiche Guard wie _job_card.html."""
    if job.sources:
        url = job.sources[0].get("url", "") or ""
        if url.startswith(("http://", "https://")):
            return url
    return ""


def _portal(job) -> str:
    return (job.sources[0].get("portal", "") or "") if job.sources else ""


def build_csv(entries: list[dict], favorites: set[str]) -> bytes:
    """Semikolon-CSV (Excel-DE) mit UTF-8-BOM, festes 10-Spalten-Format."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow(CSV_SPALTEN)
    for e in entries:
        job = e["job"]
        writer.writerow([
            job.title, job.company, job.location,
            e["score"] if e["score"] is not None else "",
            e["category"] or "", e["reason"] or "",
            _portal(job), job.first_seen, _quelle_url(job),
            "ja" if job.fingerprint in favorites else "nein",
        ])
    return buf.getvalue().encode("utf-8-sig")


class _MatchesPDF(FPDF):
    """A4-Druckmedium: helles Papier, --tiefe als Tinte, --signal für Score-Balken."""

    def __init__(self, meta: dict):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.meta = meta
        self.add_font("DejaVu", "", _FONT_DIR / "DejaVuSans.ttf")
        self.add_font("DejaVu", "B", _FONT_DIR / "DejaVuSans-Bold.ttf")
        self.add_font("DejaVuMono", "B", _FONT_DIR / "DejaVuSansMono-Bold.ttf")
        self.set_auto_page_break(auto=True, margin=18)

    def header(self):
        self.set_text_color(*_TIEFE)
        self.set_font("DejaVu", "B", 13)
        self.cell(90, 8, "BOB · Matches")
        self.set_font("DejaVu", "", 10)
        self.cell(0, 8, f"{self.meta['datum']} · {self.meta['anzahl']} Jobs",
                  align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_font("DejaVu", "", 9)
        self.set_text_color(*_GRAU)
        self.cell(0, 5, f"Quelle: {self.meta['quelle']}", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*_TIEFE)
        self.line(self.l_margin, self.get_y() + 1, self.w - self.r_margin, self.get_y() + 1)
        self.ln(4)

    def footer(self):
        self.set_y(-14)
        self.set_font("DejaVu", "", 8)
        self.set_text_color(*_GRAU)
        self.cell(90, 6, f"Seite {self.page_no()}")
        self.cell(0, 6, "job-scanner.thinkshark.de", align="R")


def build_pdf(entries: list[dict], favorites: set[str], meta: dict) -> bytes:
    pdf = _MatchesPDF(meta)
    pdf.add_page()
    if not entries:
        pdf.set_font("DejaVu", "", 10)
        pdf.set_text_color(*_GRAU)
        pdf.cell(0, 8, "Keine Jobs in dieser Auswahl.")
        return bytes(pdf.output())
    for e in entries:
        job = e["job"]
        score = e["score"]
        pdf.set_text_color(*_TIEFE)
        pdf.set_font("DejaVuMono", "B", 12)
        pdf.cell(12, 6, f"{score}" if score is not None else "–")
        balken_x = pdf.get_x()
        if score is not None:
            pdf.set_fill_color(*_SIGNAL)
            pdf.rect(balken_x, pdf.get_y() + 1.5, 18 * min(score, 100) / 100, 3, style="F")
        pdf.set_x(balken_x + 20)
        pdf.set_font("DejaVu", "B", 11)
        pdf.cell(0, 6, f"{job.title} · {job.company}"[:90],
                 new_x="LMARGIN", new_y="NEXT")
        teile = [job.location or "—"]
        if job.fingerprint in favorites:
            teile.append("★ Favorit")
        pdf.set_font("DejaVu", "", 9)
        pdf.set_text_color(*_GRAU)
        pdf.set_x(pdf.l_margin + 32)
        pdf.cell(0, 5, " · ".join(teile), new_x="LMARGIN", new_y="NEXT")
        url = _quelle_url(job)
        if url:
            pdf.set_font("DejaVu", "", 8)
            pdf.set_text_color(*_SIGNAL)
            pdf.set_x(pdf.l_margin + 32)
            pdf.cell(0, 5, url[:100], link=url, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
    return bytes(pdf.output())


_KAPITEL = [
    ("1", "Alles auf der Website"),
    ("2", "Wie Bob funktioniert"),
    ("3", "Claude-Anbindung ausführlich"),
    ("4", "Troubleshooting & Sicherheit"),
]

_BOB_BILD = Path(__file__).parent / "static" / "img" / "bob" / "bob-pose-laptop.png"

_STATIC_DIR = Path(__file__).parent / "static"


def _static_src(src: str) -> str:
    """`<img src>` aus dem Template auf einen echten Dateipfad mappen.

    Das Template schreibt `/static/img/…?v=<hash>` — im PDF-Render ist das kein
    Dateipfad. Query abschneiden, `/static/`-Präfix auf das reale Verzeichnis
    mappen. Fremde Quellen sind ein Template-Fehler und werden laut.
    """
    pfad = src.split("?", 1)[0]
    if not pfad.startswith("/static/"):
        raise ValueError(f"Bildquelle ausserhalb von /static/: {src}")
    return str(_STATIC_DIR / pfad[len("/static/"):])


class _AnleitungPDF(FPDF):
    """Druckfassung der ausführlichen Anleitung — Tinte/Fonts wie _MatchesPDF,
    aber Titelseite ohne Kopf-/Fußzeile."""

    def __init__(self, datum: str):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.datum = datum
        self.add_font("DejaVu", "", _FONT_DIR / "DejaVuSans.ttf")
        self.add_font("DejaVu", "B", _FONT_DIR / "DejaVuSans-Bold.ttf")
        self.add_font("DejaVu", "I", _FONT_DIR / "DejaVuSans-Oblique.ttf")
        self.add_font("DejaVu", "BI", _FONT_DIR / "DejaVuSans-BoldOblique.ttf")
        self.add_font("DejaVuMono", "", _FONT_DIR / "DejaVuSansMono.ttf")
        self.set_auto_page_break(auto=True, margin=18)

    def header(self):
        if self.page_no() == 1:
            return
        self.set_text_color(*_TIEFE)
        self.set_font("DejaVu", "B", 11)
        self.cell(0, 8, "BOB · Die ausführliche Anleitung", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*_TIEFE)
        self.line(self.l_margin, self.get_y() + 1, self.w - self.r_margin, self.get_y() + 1)
        self.ln(4)

    def footer(self):
        if self.page_no() == 1:
            return
        self.set_y(-14)
        self.set_font("DejaVu", "", 8)
        self.set_text_color(*_GRAU)
        self.cell(90, 6, f"Seite {self.page_no()}")
        self.cell(0, 6, "job-scanner.thinkshark.de", align="R")


def build_anleitung_pdf(html: str, datum: str) -> bytes:
    """Titelseite + Inhaltsverzeichnis + write_html(fragment).

    `html` ist das gerenderte anleitung_voll.html — dieselbe Quelle wie die
    Web-Fassung, damit kein Content-Drift entsteht. write_html() versteht nur ein
    HTML-Subset (Überschriften, p, Listen, b/i, a, code/pre, table) und ignoriert
    CSS-Klassen; font_family ist Pflicht, sonst fällt es auf einen Core-Font zurück.
    """
    pdf = _AnleitungPDF(datum)
    pdf.add_page()
    if _BOB_BILD.exists():
        pdf.image(str(_BOB_BILD), x=(pdf.w - 35) / 2, y=55, w=35)  # 132x145px → 35mm ≈ 96dpi
    pdf.set_y(115)
    pdf.set_text_color(*_TIEFE)
    pdf.set_font("DejaVu", "B", 24)
    pdf.multi_cell(0, 12, "Die ausführliche Anleitung", align="C",
                   new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", 12)
    pdf.set_text_color(*_GRAU)
    pdf.cell(0, 8, "Bob der Job-Bot · job-scanner.thinkshark.de", align="C",
             new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Stand: {datum}", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.add_page()
    pdf.set_text_color(*_TIEFE)
    pdf.set_font("DejaVu", "B", 16)
    pdf.cell(0, 10, "Inhalt", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    for nr, titel in _KAPITEL:
        pdf.set_font("DejaVu", "B", 12)
        pdf.set_text_color(*_SIGNAL)
        pdf.cell(10, 8, nr)
        pdf.set_font("DejaVu", "", 12)
        pdf.set_text_color(*_TIEFE)
        pdf.cell(0, 8, titel, new_x="LMARGIN", new_y="NEXT")

    pdf.add_page()
    pdf.set_font("DejaVu", "", 11)
    pdf.set_text_color(*_TIEFE)
    pdf.write_html(html, font_family="DejaVu", image_map=_static_src,
                   tag_styles={"code": TextStyle(font_family="DejaVuMono"),
                               "pre": TextStyle(font_family="DejaVuMono")})
    return bytes(pdf.output())
