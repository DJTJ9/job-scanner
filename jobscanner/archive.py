"""Volltext-Archiv (1.6): Markdown-Snapshot pro Top-Match (Score >= Pass-Schwelle)."""
from __future__ import annotations

import re
from pathlib import Path

from jobscanner.models import Job

_DEFAULT_DIR = Path(__file__).parent.parent / "data" / "archive"


def _safe_filename(fingerprint: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fingerprint.lower()).strip("-") + ".md"


def save_snapshot(job: Job, archive_dir: str | Path | None = None) -> str:
    directory = Path(archive_dir) if archive_dir is not None else _DEFAULT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / _safe_filename(job.fingerprint)
    sources_text = "\n".join(f"- {s.get('portal')}: {s.get('url')}" for s in job.sources)
    content = (
        f"# {job.title}\n\n"
        f"**Firma:** {job.company}\n"
        f"**Ort:** {job.location}\n"
        f"**Datum:** {job.first_seen}\n\n"
        f"## Anforderungen\n" + "\n".join(f"- {r}" for r in job.requirements) + "\n\n"
        f"## Tech-Stack\n" + "\n".join(f"- {t}" for t in job.tech_stack) + "\n\n"
        f"## Quellen\n{sources_text}\n"
    )
    path.write_text(content, encoding="utf-8")
    return str(path)
