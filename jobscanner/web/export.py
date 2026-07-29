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
