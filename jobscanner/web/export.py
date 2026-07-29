# jobscanner/web/export.py
"""Match-Export als CSV/PDF. Reine Builder ohne Request-Kontext — testbar,
hält app.py (1518 Zeilen) schlank. Entry-Shape = storage.list_jobs_with_scores."""
import csv
import io
from pathlib import Path

from fpdf import FPDF

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
