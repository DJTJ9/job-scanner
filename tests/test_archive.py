"""Tests für archive.save_snapshot — Markdown-Snapshot pro Top-Match (1.6)."""
from jobscanner import archive
from jobscanner.models import Job


def _job(**overrides) -> Job:
    base = dict(
        title="Unity Developer", company="ACME GmbH", location="Hamburg",
        requirements=["Unity", "C#"], tech_stack=["Unity", "C#", "Git"],
        sources=[{"portal": "indeed", "url": "https://indeed.test/1", "found_at": "2026-07-10"}],
        first_seen="2026-07-10",
    )
    base.update(overrides)
    return Job(**base)


def test_save_snapshot_writes_markdown_file(tmp_path):
    job = _job()
    path = archive.save_snapshot(job, archive_dir=tmp_path)
    content = open(path, encoding="utf-8").read()
    assert "Unity Developer" in content
    assert "ACME GmbH" in content
    assert "Unity" in content
    assert "https://indeed.test/1" in content


def test_save_snapshot_filename_is_safe_despite_pipe_in_fingerprint(tmp_path):
    job = _job()
    assert "|" in job.fingerprint
    path = archive.save_snapshot(job, archive_dir=tmp_path)
    assert "|" not in path
    assert path.endswith(".md")
