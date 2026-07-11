"""SQLite-Storage — dumm und robust, Validierung gehört in die Portal-Adapter (1.2)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from jobscanner import config
from jobscanner.models import Job

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    fingerprint TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    remote_flag TEXT,
    employment_type TEXT,
    language TEXT,
    salary_text TEXT,
    role TEXT,
    is_neighbor INTEGER DEFAULT 0,
    requirements_json TEXT,
    tech_stack_json TEXT,
    sources_json TEXT,
    first_seen TEXT,
    last_seen TEXT,
    archive_path TEXT,
    score INTEGER,
    score_reason TEXT,
    category TEXT,
    status TEXT DEFAULT 'neu',
    nocodb_row_id INTEGER
)
"""

_SCHEMA_PROFILES = """
CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    data_json TEXT NOT NULL DEFAULT '{}',
    queries_json TEXT,
    active INTEGER DEFAULT 1,
    is_default INTEGER DEFAULT 0,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS criteria (
    id INTEGER PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES profiles(id),
    key TEXT NOT NULL,
    label TEXT NOT NULL,
    weight INTEGER NOT NULL DEFAULT 3 CHECK (weight BETWEEN 0 AND 5),
    sort INTEGER DEFAULT 0,
    UNIQUE (profile_id, key)
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES profiles(id),
    fingerprint TEXT NOT NULL,
    vote TEXT NOT NULL CHECK (vote IN ('up', 'down')),
    created_at TEXT NOT NULL,
    UNIQUE (profile_id, fingerprint)
);
CREATE TABLE IF NOT EXISTS job_scores (
    profile_id INTEGER NOT NULL REFERENCES profiles(id),
    fingerprint TEXT NOT NULL,
    score INTEGER,
    reason TEXT,
    category TEXT,
    breakdown_json TEXT,
    scored_at TEXT,
    PRIMARY KEY (profile_id, fingerprint)
);
"""

_UPDATABLE = {
    "title", "company", "location", "remote_flag", "employment_type", "language",
    "salary_text", "first_seen", "last_seen", "archive_path", "score",
    "score_reason", "category", "status", "nocodb_row_id",
}
_FILTERABLE = {"status", "category", "language", "remote_flag", "company", "first_seen", "last_seen"}

_conn: sqlite3.Connection | None = None


def init_db(path: str | Path) -> None:
    global _conn
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(path)
    _conn.row_factory = sqlite3.Row
    _conn.execute(_SCHEMA)
    existing_cols = {row["name"] for row in _conn.execute("PRAGMA table_info(jobs)")}
    if "role" not in existing_cols:
        _conn.execute("ALTER TABLE jobs ADD COLUMN role TEXT")
    if "is_neighbor" not in existing_cols:
        _conn.execute("ALTER TABLE jobs ADD COLUMN is_neighbor INTEGER DEFAULT 0")
    _conn.executescript(_SCHEMA_PROFILES)
    _conn.commit()


def close() -> None:
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


def _require_conn() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("init_db() muss vor allen Storage-Aufrufen laufen")
    return _conn


def upsert_job(job: Job) -> str:
    conn = _require_conn()
    fp = job.fingerprint
    row = conn.execute("SELECT sources_json FROM jobs WHERE fingerprint = ?", (fp,)).fetchone()
    if row is None:
        conn.execute(
            """INSERT INTO jobs (fingerprint, title, company, location, remote_flag,
                   employment_type, language, salary_text, role, is_neighbor, requirements_json,
                   tech_stack_json, sources_json, first_seen, last_seen, archive_path,
                   score, score_reason, category, status, nocodb_row_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (fp, job.title, job.company, job.location, job.remote_flag,
             job.employment_type, job.language, job.salary_text, job.role, int(job.is_neighbor),
             json.dumps(job.requirements, ensure_ascii=False),
             json.dumps(job.tech_stack, ensure_ascii=False),
             json.dumps(job.sources, ensure_ascii=False),
             job.first_seen, job.last_seen, job.archive_path,
             job.score, job.score_reason, job.category, job.status, job.nocodb_row_id),
        )
    else:
        existing = json.loads(row["sources_json"] or "[]")
        known_urls = {s.get("url") for s in existing}
        merged = existing + [s for s in job.sources if s.get("url") not in known_urls]
        conn.execute(
            "UPDATE jobs SET last_seen = ?, sources_json = ? WHERE fingerprint = ?",
            (job.last_seen, json.dumps(merged, ensure_ascii=False), fp),
        )
    conn.commit()
    return fp


def _row_to_job(row: sqlite3.Row) -> Job:
    return Job(
        title=row["title"],
        company=row["company"],
        location=row["location"] or "",
        remote_flag=row["remote_flag"] or "unknown",
        employment_type=row["employment_type"] or "",
        language=row["language"] or "",
        salary_text=row["salary_text"] or "",
        role=row["role"] or "",
        is_neighbor=bool(row["is_neighbor"]),
        requirements=json.loads(row["requirements_json"] or "[]"),
        tech_stack=json.loads(row["tech_stack_json"] or "[]"),
        sources=json.loads(row["sources_json"] or "[]"),
        first_seen=row["first_seen"] or "",
        last_seen=row["last_seen"] or "",
        archive_path=row["archive_path"],
        score=row["score"],
        score_reason=row["score_reason"],
        category=row["category"],
        status=row["status"] or "neu",
        nocodb_row_id=row["nocodb_row_id"],
    )


def get_job(fingerprint: str) -> Job | None:
    conn = _require_conn()
    row = conn.execute("SELECT * FROM jobs WHERE fingerprint = ?", (fingerprint,)).fetchone()
    return _row_to_job(row) if row else None


def list_jobs(**filters) -> list[Job]:
    conn = _require_conn()
    unknown = set(filters) - _FILTERABLE
    if unknown:
        raise ValueError(f"Unbekannte Filter-Felder: {sorted(unknown)}")
    sql = "SELECT * FROM jobs"
    params: list = []
    if filters:
        sql += " WHERE " + " AND ".join(f"{k} = ?" for k in filters)
        params = list(filters.values())
    return [_row_to_job(r) for r in conn.execute(sql, params)]


def update_job(fingerprint: str, /, **fields) -> None:
    conn = _require_conn()
    unknown = set(fields) - _UPDATABLE
    if unknown:
        raise ValueError(f"Unbekannte Update-Felder: {sorted(unknown)}")
    if not fields:
        return
    sql = "UPDATE jobs SET " + ", ".join(f"{k} = ?" for k in fields) + " WHERE fingerprint = ?"
    conn.execute(sql, [*fields.values(), fingerprint])
    conn.commit()


def _row_to_profile(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "data": json.loads(row["data_json"] or "{}"),
        "queries": json.loads(row["queries_json"]) if row["queries_json"] else None,
        "active": bool(row["active"]),
        "is_default": bool(row["is_default"]),
        "created_at": row["created_at"],
    }


def create_profile(name: str, data: dict, queries: dict | None = None,
                   is_default: bool = False) -> int:
    conn = _require_conn()
    cur = conn.execute(
        """INSERT INTO profiles (name, data_json, queries_json, active, is_default, created_at)
           VALUES (?, ?, ?, 1, ?, date('now'))""",
        (name, json.dumps(data, ensure_ascii=False),
         json.dumps(queries, ensure_ascii=False) if queries else None,
         int(is_default)),
    )
    conn.commit()
    return cur.lastrowid


def get_profile(profile_id: int) -> dict | None:
    conn = _require_conn()
    row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    return _row_to_profile(row) if row else None


def get_profile_by_name(name: str) -> dict | None:
    conn = _require_conn()
    row = conn.execute("SELECT * FROM profiles WHERE name = ?", (name,)).fetchone()
    return _row_to_profile(row) if row else None


def list_profiles(active_only: bool = False) -> list[dict]:
    conn = _require_conn()
    sql = "SELECT * FROM profiles"
    if active_only:
        sql += " WHERE active = 1"
    return [_row_to_profile(r) for r in conn.execute(sql + " ORDER BY id")]


def save_criteria(profile_id: int, criteria: list[dict]) -> None:
    """Ersetzt den kompletten Kriteriensatz des Profils (Wizard/Settings-Save)."""
    conn = _require_conn()
    with conn:
        conn.execute("DELETE FROM criteria WHERE profile_id = ?", (profile_id,))
        conn.executemany(
            "INSERT INTO criteria (profile_id, key, label, weight, sort) VALUES (?, ?, ?, ?, ?)",
            [(profile_id, c["key"], c["label"], c["weight"], c.get("sort", i))
             for i, c in enumerate(criteria)],
        )


def list_criteria(profile_id: int) -> list[dict]:
    conn = _require_conn()
    rows = conn.execute(
        "SELECT * FROM criteria WHERE profile_id = ? ORDER BY sort, id", (profile_id,))
    return [dict(r) for r in rows]


def set_criterion_weight(criterion_id: int, weight: int) -> None:
    conn = _require_conn()
    conn.execute("UPDATE criteria SET weight = ? WHERE id = ?", (weight, criterion_id))
    conn.commit()


def add_feedback(profile_id: int, fingerprint: str, vote: str) -> None:
    conn = _require_conn()
    conn.execute(
        """INSERT INTO feedback (profile_id, fingerprint, vote, created_at)
           VALUES (?, ?, ?, datetime('now'))
           ON CONFLICT (profile_id, fingerprint)
           DO UPDATE SET vote = excluded.vote, created_at = excluded.created_at""",
        (profile_id, fingerprint, vote),
    )
    conn.commit()


def list_feedback(profile_id: int) -> list[dict]:
    conn = _require_conn()
    rows = conn.execute("SELECT * FROM feedback WHERE profile_id = ?", (profile_id,))
    return [dict(r) for r in rows]


def upsert_job_score(profile_id: int, fingerprint: str, score: int | None,
                     reason: str, category: str | None, breakdown: dict) -> None:
    conn = _require_conn()
    conn.execute(
        """INSERT INTO job_scores (profile_id, fingerprint, score, reason, category,
                                   breakdown_json, scored_at)
           VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT (profile_id, fingerprint)
           DO UPDATE SET score = excluded.score, reason = excluded.reason,
                         category = excluded.category, breakdown_json = excluded.breakdown_json,
                         scored_at = excluded.scored_at""",
        (profile_id, fingerprint, score, reason, category,
         json.dumps(breakdown, ensure_ascii=False)),
    )
    conn.commit()


def get_job_score(profile_id: int, fingerprint: str) -> dict | None:
    conn = _require_conn()
    row = conn.execute(
        "SELECT * FROM job_scores WHERE profile_id = ? AND fingerprint = ?",
        (profile_id, fingerprint)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["breakdown"] = json.loads(d.pop("breakdown_json") or "{}")
    return d


DEFAULT_CRITERIA = [
    {"key": "role_fit", "label": "Passung zu Zielrollen", "weight": 5},
    {"key": "seniority", "label": "Level passt (Junior/Entry)", "weight": 5},
    {"key": "tech_stack", "label": "Tech-Stack-Übereinstimmung", "weight": 4},
    {"key": "remote", "label": "Remote-Möglichkeit", "weight": 4},
    {"key": "location", "label": "Standort (Hamburg-Bonus)", "weight": 3},
    {"key": "employment", "label": "Anstellungsart (Festanstellung/Teilzeit)", "weight": 3},
    {"key": "domain", "label": "Domänen-Bonus (Sport/EdTech/Serious Games)", "weight": 3},
    {"key": "language", "label": "Sprache (de/en)", "weight": 2},
    {"key": "salary", "label": "Gehalt", "weight": 2},
]


def migrate_yaml_profile() -> int:
    """default.yaml + queries.yaml → Profil „Tjark" mit Seed-Kriterien. Idempotent."""
    existing = get_profile_by_name("Tjark")
    if existing is not None:
        return existing["id"]
    data = config.load_profile("default")
    queries = config.load_queries()
    pid = create_profile("Tjark", data, queries=queries, is_default=True)
    save_criteria(pid, [dict(c, sort=i) for i, c in enumerate(DEFAULT_CRITERIA)])
    return pid
