"""SQLite-Storage — dumm und robust, Validierung gehört in die Portal-Adapter (1.2)."""
from __future__ import annotations

import functools
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from datetime import date, timedelta
from pathlib import Path

from jobscanner import config, scoring
from jobscanner.models import Job
from jobscanner.search import classify_location

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
    nocodb_row_id INTEGER,
    raw_text TEXT,
    extraction_status TEXT DEFAULT 'extracted',
    is_ausland INTEGER DEFAULT 0
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
CREATE TABLE IF NOT EXISTS favorites (
    id INTEGER PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES profiles(id),
    fingerprint TEXT NOT NULL,
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
CREATE TABLE IF NOT EXISTS feedback_analysis (
    id INTEGER PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES profiles(id),
    cards_json TEXT NOT NULL DEFAULT '{}',
    answers_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'analyzing',
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS insights (
    id INTEGER PRIMARY KEY,
    profile_id INTEGER NOT NULL REFERENCES profiles(id),
    kind TEXT NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'proposed',
    source TEXT NOT NULL DEFAULT 'learned',
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    pw_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member',
    api_token_hash TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    ts INTEGER NOT NULL,
    user_id INTEGER REFERENCES users(id),
    event_type TEXT NOT NULL,
    meta_json TEXT
);
CREATE TABLE IF NOT EXISTS member_feedback (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

_SCHEMA_CUSTOM_PORTALS = """
CREATE TABLE IF NOT EXISTS custom_portals (
    id INTEGER PRIMARY KEY,
    url TEXT NOT NULL,
    typ TEXT NOT NULL CHECK (typ IN ('career_page', 'portal')),
    search_url_template TEXT,
    detail_url_pattern TEXT,
    submitted_by INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'pending_check' CHECK (status IN
        ('pending_check', 'compatible', 'needs_firecrawl_pending', 'active', 'rejected')),
    firecrawl_needed INTEGER DEFAULT 0,
    check_ergebnis_json TEXT,
    created_at TEXT NOT NULL,
    activated_at TEXT
);
"""

_SCHEMA_MEMBER_RESCORE = """
CREATE TABLE IF NOT EXISTS member_rescore_queue (
    profile_id INTEGER NOT NULL REFERENCES profiles(id),
    fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
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
    _conn = sqlite3.connect(path, check_same_thread=False)
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute("PRAGMA busy_timeout=5000")
    _conn.execute("PRAGMA synchronous=NORMAL")
    _conn.row_factory = sqlite3.Row
    _conn.execute(_SCHEMA)
    existing_cols = {row["name"] for row in _conn.execute("PRAGMA table_info(jobs)")}
    if "role" not in existing_cols:
        _conn.execute("ALTER TABLE jobs ADD COLUMN role TEXT")
    if "is_neighbor" not in existing_cols:
        _conn.execute("ALTER TABLE jobs ADD COLUMN is_neighbor INTEGER DEFAULT 0")
    if "raw_text" not in existing_cols:
        _conn.execute("ALTER TABLE jobs ADD COLUMN raw_text TEXT")
    if "extraction_status" not in existing_cols:
        _conn.execute("ALTER TABLE jobs ADD COLUMN extraction_status TEXT DEFAULT 'extracted'")
    if "is_ausland" not in existing_cols:
        _conn.execute("ALTER TABLE jobs ADD COLUMN is_ausland INTEGER DEFAULT 0")
    if "unavailable_strikes" not in existing_cols:
        _conn.execute("ALTER TABLE jobs ADD COLUMN unavailable_strikes INTEGER DEFAULT 0")
    _conn.executescript(_SCHEMA_PROFILES)
    _conn.executescript(_SCHEMA_CUSTOM_PORTALS)
    _conn.executescript(_SCHEMA_MEMBER_RESCORE)
    prof_cols = {row["name"] for row in _conn.execute("PRAGMA table_info(profiles)")}
    if "user_id" not in prof_cols:
        _conn.execute("ALTER TABLE profiles ADD COLUMN user_id INTEGER REFERENCES users(id)")
    if "last_learn_reminder_at" not in prof_cols:
        _conn.execute("ALTER TABLE profiles ADD COLUMN last_learn_reminder_at TEXT")
    user_cols = {row["name"] for row in _conn.execute("PRAGMA table_info(users)")}
    if "api_token_hash" not in user_cols:
        _conn.execute("ALTER TABLE users ADD COLUMN api_token_hash TEXT")
    if "email_verified_at" not in user_cols:
        _conn.execute("ALTER TABLE users ADD COLUMN email_verified_at TEXT")
    if "verify_token" not in user_cols:
        _conn.execute("ALTER TABLE users ADD COLUMN verify_token TEXT")
    if "consent_at" not in user_cols:
        _conn.execute("ALTER TABLE users ADD COLUMN consent_at TEXT")
    if "registered_ip" not in user_cols:
        _conn.execute("ALTER TABLE users ADD COLUMN registered_ip TEXT")
    score_cols = {row["name"] for row in _conn.execute("PRAGMA table_info(job_scores)")}
    if "notified_at" not in score_cols:
        _conn.execute("ALTER TABLE job_scores ADD COLUMN notified_at TEXT")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_extraction_status ON jobs(extraction_status)")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_category ON jobs(category)")
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


def _retry_on_locked(fn):
    """Retry-Netz für 'database is locked' nach dem busy_timeout — 5 Versuche,
    exponentieller Backoff, Rollback vor jedem Retry (räumt die offene TX, sonst
    Doppel-Insert beim Re-Run)."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        for i in range(5):
            try:
                return fn(*args, **kwargs)
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and i < 4:
                    if _conn is not None:
                        _conn.rollback()
                    time.sleep(0.05 * (2 ** i))  # 50, 100, 200, 400 ms
                    continue
                raise
    return wrapper


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000).hex()


@_retry_on_locked
def create_user(email: str, password: str, role: str = "member",
                consent: bool = False, ip: str | None = None) -> int:
    conn = _require_conn()
    salt = os.urandom(16)
    verify_token = secrets.token_urlsafe(32)
    consent_at = conn.execute("SELECT datetime('now')").fetchone()[0] if consent else None
    cur = conn.execute(
        "INSERT INTO users (email, pw_hash, salt, role, created_at, "
        "verify_token, consent_at, registered_ip) "
        "VALUES (?, ?, ?, ?, datetime('now'), ?, ?, ?)",
        (email.strip().lower(), _hash_password(password, salt), salt.hex(), role,
         verify_token, consent_at, ip))
    conn.commit()
    return cur.lastrowid


@_retry_on_locked
def set_password(user_id: int, new_password: str) -> None:
    """Setzt das Passwort eines bestehenden Users neu (neuer Salt + Hash).
    Wiederverwendbar für Self-Service-Änderung und Owner-CLI-Reset."""
    conn = _require_conn()
    salt = os.urandom(16)
    conn.execute(
        "UPDATE users SET pw_hash = ?, salt = ? WHERE id = ?",
        (_hash_password(new_password, salt), salt.hex(), user_id))
    conn.commit()


def get_user(user_id: int) -> dict | None:
    conn = _require_conn()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_email(email: str) -> dict | None:
    conn = _require_conn()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
    return dict(row) if row else None


def verify_password(email: str, password: str) -> dict | None:
    user = get_user_by_email(email)
    if user is None:
        return None
    expected = _hash_password(password, bytes.fromhex(user["salt"]))
    return user if hmac.compare_digest(expected, user["pw_hash"]) else None


@_retry_on_locked
def seed_owner(email: str, password: str) -> int | None:
    """Legt einmalig den Owner-User an, falls noch kein Owner existiert, und ordnet ihm
    alle Profile ohne user_id zu. Idempotent — gibt die vorhandene Owner-Id zurück."""
    conn = _require_conn()
    existing = conn.execute("SELECT id FROM users WHERE role = 'owner' LIMIT 1").fetchone()
    if existing is not None:
        return existing["id"]
    uid = create_user(email, password, role="owner")
    conn.execute("UPDATE profiles SET user_id = ? WHERE user_id IS NULL", (uid,))
    conn.commit()
    return uid


@_retry_on_locked
def ensure_verify_token(user_id: int) -> str | None:
    """Gibt den vorhandenen verify_token zurück oder generiert einen, falls keiner gesetzt ist
    (z.B. Accounts, die vor Einführung der Email-Verifizierung angelegt wurden). Gibt None
    zurück, wenn der User nicht existiert."""
    conn = _require_conn()
    row = conn.execute("SELECT verify_token FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        return None
    token = row["verify_token"]
    if token:
        return token
    token = secrets.token_urlsafe(32)
    conn.execute("UPDATE users SET verify_token = ? WHERE id = ?", (token, user_id))
    conn.commit()
    return token


@_retry_on_locked
def mark_email_verified(user_id: int) -> None:
    conn = _require_conn()
    conn.execute(
        "UPDATE users SET email_verified_at = datetime('now'), verify_token = NULL "
        "WHERE id = ?", (user_id,))
    conn.commit()


def verify_token_owner(token: str) -> dict | None:
    if not token:
        return None
    conn = _require_conn()
    row = conn.execute("SELECT * FROM users WHERE verify_token = ?", (token,)).fetchone()
    return dict(row) if row else None


def list_registrations() -> list[dict]:
    conn = _require_conn()
    rows = conn.execute(
        "SELECT id, email, created_at, email_verified_at, registered_ip "
        "FROM users WHERE role = 'member' ORDER BY id ASC").fetchall()
    return [dict(r) for r in rows]


@_retry_on_locked
def create_api_token(user_id: int) -> str:
    """Erzeugt ein API-Token für den Member-MCP-Zugang und speichert nur den SHA-256-Hash.
    Ersetzt ein evtl. vorhandenes Token (ein Token pro User). Gibt den Klartext zurück —
    der einzige Moment, in dem er existiert (Einmal-Anzeige im UI)."""
    conn = _require_conn()
    token = "bob_" + secrets.token_hex(24)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    conn.execute("UPDATE users SET api_token_hash = ? WHERE id = ?", (token_hash, user_id))
    conn.commit()
    return token


def get_user_by_api_token(token: str) -> dict | None:
    """User-Lookup per Token-Klartext. Bewusst deterministischer SHA-256 statt
    pbkdf2+Salt (pw_hash-Pattern): der Lookup kennt den User nicht vorab und braucht
    eine direkte Hash-Query; 24 Random-Bytes machen Rainbow-Tables irrelevant."""
    if not token:
        return None
    conn = _require_conn()
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    row = conn.execute(
        "SELECT * FROM users WHERE api_token_hash = ?", (token_hash,)).fetchone()
    return dict(row) if row else None


@_retry_on_locked
def upsert_job(job: Job) -> str:
    conn = _require_conn()
    fp = job.fingerprint
    row = conn.execute("SELECT sources_json FROM jobs WHERE fingerprint = ?", (fp,)).fetchone()
    if row is None:
        conn.execute(
            """INSERT INTO jobs (fingerprint, title, company, location, remote_flag,
                   employment_type, language, salary_text, role, is_neighbor, requirements_json,
                   tech_stack_json, sources_json, first_seen, last_seen, archive_path,
                   score, score_reason, category, status, nocodb_row_id, is_ausland)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (fp, job.title, job.company, job.location, job.remote_flag,
             job.employment_type, job.language, job.salary_text, job.role, int(job.is_neighbor),
             json.dumps(job.requirements, ensure_ascii=False),
             json.dumps(job.tech_stack, ensure_ascii=False),
             json.dumps(job.sources, ensure_ascii=False),
             job.first_seen, job.last_seen, job.archive_path,
             job.score, job.score_reason, job.category, job.status, job.nocodb_row_id,
             int(classify_location(job.location))),
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


def _raw_fingerprint(url: str) -> str:
    """Provisorischer Fingerprint für Raw-Jobs vor der Extraktion — URL-basiert, weil
    company/title/location (normale Fingerprint-Basis) erst nach Extraction existieren.
    'url:'-Präfix kann mit normalisierten Content-Fingerprints nie kollidieren (':' wird
    von models._norm entfernt)."""
    return f"url:{hashlib.sha1(url.encode('utf-8')).hexdigest()}"


@_retry_on_locked
def insert_raw_job(url: str, portal: str, raw_text: str, today: str,
                   role: str = "", is_neighbor: bool = False,
                   via: str | None = None) -> str:
    """Speichert einen unextrahierten Job aus der Discover-Phase (kein Groq mehr im Pfad).
    via markiert die Einlieferquelle (z.B. 'member:<user_id>' beim MCP-push_jobs)."""
    conn = _require_conn()
    fp = _raw_fingerprint(url)
    row = conn.execute("SELECT sources_json FROM jobs WHERE fingerprint = ?", (fp,)).fetchone()
    source = {"portal": portal, "url": url, "found_at": today}
    if via:
        source["via"] = via
    if row is None:
        conn.execute(
            """INSERT INTO jobs (fingerprint, title, company, location, remote_flag,
                   employment_type, language, salary_text, role, is_neighbor,
                   requirements_json, tech_stack_json, sources_json, first_seen, last_seen,
                   status, raw_text, extraction_status)
               VALUES (?, '', '', '', 'unknown', '', '', '', ?, ?, '[]', '[]', ?, ?, ?,
                       'neu', ?, 'pending')""",
            (fp, role, int(is_neighbor), json.dumps([source], ensure_ascii=False),
             today, today, raw_text),
        )
    else:
        existing = json.loads(row["sources_json"] or "[]")
        known_urls = {s.get("url") for s in existing}
        merged = existing if url in known_urls else existing + [source]
        conn.execute(
            "UPDATE jobs SET last_seen = ?, sources_json = ? WHERE fingerprint = ?",
            (today, json.dumps(merged, ensure_ascii=False), fp),
        )
    conn.commit()
    return fp


def list_pending_extraction(limit: int | None = None) -> list[dict]:
    """Rohdaten wartender Jobs für den Agent-Batch-Lauf (llm_batch.py list-pending)."""
    conn = _require_conn()
    sql = ("SELECT fingerprint, sources_json, raw_text FROM jobs "
          "WHERE extraction_status = 'pending' AND status != 'expired' ORDER BY id")
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    out = []
    for r in conn.execute(sql):
        sources = json.loads(r["sources_json"] or "[]")
        src = sources[0] if sources else {}
        out.append({"fingerprint": r["fingerprint"], "portal": src.get("portal", ""),
                    "url": src.get("url", ""), "raw_text": r["raw_text"] or ""})
    return out


def list_unscored_extracted(limit: int | None = None) -> list[dict]:
    """Extrahierte, aber nie gescorte Jobs (extraction_status='extracted' AND score IS NULL)
    für den score-only-Zweig des Agent-Batch-Laufs — schließt die Re-Pick-Lücke, die
    entsteht wenn ein Agent-Lauf nach apply_extraction, aber vor dem Scoring abbricht."""
    conn = _require_conn()
    sql = ("SELECT fingerprint, title, company, location, employment_type, "
           "requirements_json, tech_stack_json FROM jobs "
           "WHERE extraction_status = 'extracted' AND score IS NULL "
           "AND status != 'expired' ORDER BY id")
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    out = []
    for r in conn.execute(sql):
        out.append({
            "fingerprint": r["fingerprint"],
            "title": r["title"],
            "company": r["company"],
            "location": r["location"] or "",
            "employment_type": r["employment_type"] or "",
            "requirements": json.loads(r["requirements_json"] or "[]"),
            "tech_stack": json.loads(r["tech_stack_json"] or "[]"),
        })
    return out


def list_unscored_for_profiles(profile_ids: list[int], limit: int | None = None) -> list[dict]:
    """Extrahierte Jobs, denen für mindestens eines der gegebenen Profile der
    job_scores-Eintrag fehlt — der user-scoped to_score-Zweig des MCP-pull_pending_jobs.
    Item-Shape identisch zu list_unscored_extracted."""
    conn = _require_conn()
    if not profile_ids:
        return []
    placeholders = ",".join("?" for _ in profile_ids)
    sql = (
        "SELECT DISTINCT jobs.fingerprint, jobs.title, jobs.company, jobs.location, "
        "jobs.employment_type, jobs.requirements_json, jobs.tech_stack_json "
        "FROM jobs JOIN profiles ON profiles.id IN (" + placeholders + ") "
        "WHERE jobs.extraction_status = 'extracted' "
        "AND jobs.status != 'expired' "
        "AND NOT EXISTS (SELECT 1 FROM job_scores "
        "                WHERE job_scores.profile_id = profiles.id "
        "                AND job_scores.fingerprint = jobs.fingerprint) "
        "ORDER BY jobs.id"
    )
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    out = []
    for r in conn.execute(sql, list(profile_ids)):
        out.append({
            "fingerprint": r["fingerprint"],
            "title": r["title"],
            "company": r["company"],
            "location": r["location"] or "",
            "employment_type": r["employment_type"] or "",
            "requirements": json.loads(r["requirements_json"] or "[]"),
            "tech_stack": json.loads(r["tech_stack_json"] or "[]"),
        })
    return out


@_retry_on_locked
def apply_extraction(raw_fingerprint: str, job: Job) -> str:
    """Schreibt das Agent-Extraktionsergebnis in die Raw-Zeile — merged in eine bestehende
    Zeile, falls derselbe Job über 2 Portale vor der Extraktion gefunden wurde (die
    Content-Fingerprint-Zeile existiert dann schon, unabhängig vom Extraction-Status)."""
    conn = _require_conn()
    new_fp = job.fingerprint
    raw_row = conn.execute(
        "SELECT sources_json FROM jobs WHERE fingerprint = ?", (raw_fingerprint,)).fetchone()
    raw_sources = json.loads(raw_row["sources_json"] or "[]") if raw_row else []
    other = conn.execute(
        "SELECT sources_json FROM jobs WHERE fingerprint = ? AND fingerprint != ?",
        (new_fp, raw_fingerprint)).fetchone()
    if other is not None:
        other_sources = json.loads(other["sources_json"] or "[]")
        known_urls = {s.get("url") for s in other_sources}
        merged = other_sources + [s for s in raw_sources if s.get("url") not in known_urls]
        conn.execute(
            """UPDATE jobs SET title = ?, company = ?, location = ?, remote_flag = ?,
                   employment_type = ?, language = ?, salary_text = ?, requirements_json = ?,
                   tech_stack_json = ?, sources_json = ?, last_seen = ?,
                   extraction_status = 'extracted', is_ausland = ?
               WHERE fingerprint = ?""",
            (job.title, job.company, job.location, job.remote_flag, job.employment_type,
             job.language, job.salary_text, json.dumps(job.requirements, ensure_ascii=False),
             json.dumps(job.tech_stack, ensure_ascii=False),
             json.dumps(merged, ensure_ascii=False), job.last_seen,
             int(classify_location(job.location)), new_fp))
        if raw_fingerprint != new_fp:
            conn.execute("DELETE FROM jobs WHERE fingerprint = ?", (raw_fingerprint,))
    else:
        conn.execute(
            """UPDATE jobs SET fingerprint = ?, title = ?, company = ?, location = ?,
                   remote_flag = ?, employment_type = ?, language = ?, salary_text = ?,
                   requirements_json = ?, tech_stack_json = ?, extraction_status = 'extracted',
                   is_ausland = ?
               WHERE fingerprint = ?""",
            (new_fp, job.title, job.company, job.location, job.remote_flag,
             job.employment_type, job.language, job.salary_text,
             json.dumps(job.requirements, ensure_ascii=False),
             json.dumps(job.tech_stack, ensure_ascii=False),
             int(classify_location(job.location)), raw_fingerprint))
    conn.commit()
    return new_fp


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


@_retry_on_locked
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
        "user_id": row["user_id"],
        "created_at": row["created_at"],
    }


@_retry_on_locked
def create_profile(name: str, data: dict, queries: dict | None = None,
                   is_default: bool = False, user_id: int | None = None) -> int:
    conn = _require_conn()
    cur = conn.execute(
        """INSERT INTO profiles (name, data_json, queries_json, active, is_default, user_id, created_at)
           VALUES (?, ?, ?, 1, ?, ?, date('now'))""",
        (name, json.dumps(data, ensure_ascii=False),
         json.dumps(queries, ensure_ascii=False) if queries else None,
         int(is_default), user_id),
    )
    conn.commit()
    return cur.lastrowid


@_retry_on_locked
def delete_profile(profile_id: int) -> None:
    """Löscht Profil + alle abhängigen Zeilen (SQLite-FKs sind aus, daher manuell)."""
    conn = _require_conn()
    with conn:
        conn.execute("DELETE FROM insights WHERE profile_id = ?", (profile_id,))
        conn.execute("DELETE FROM feedback_analysis WHERE profile_id = ?", (profile_id,))
        conn.execute("DELETE FROM job_scores WHERE profile_id = ?", (profile_id,))
        conn.execute("DELETE FROM favorites WHERE profile_id = ?", (profile_id,))
        conn.execute("DELETE FROM feedback WHERE profile_id = ?", (profile_id,))
        conn.execute("DELETE FROM criteria WHERE profile_id = ?", (profile_id,))
        conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))


@_retry_on_locked
def update_profile(profile_id: int, name: str, data: dict) -> None:
    """Überschreibt Name + data_json eines bestehenden Profils (Wizard-Edit)."""
    conn = _require_conn()
    with conn:
        conn.execute(
            "UPDATE profiles SET name = ?, data_json = ? WHERE id = ?",
            (name, json.dumps(data, ensure_ascii=False), profile_id),
        )


def get_profile(profile_id: int) -> dict | None:
    conn = _require_conn()
    row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    return _row_to_profile(row) if row else None


def get_profile_by_name(name: str) -> dict | None:
    conn = _require_conn()
    row = conn.execute("SELECT * FROM profiles WHERE name = ?", (name,)).fetchone()
    return _row_to_profile(row) if row else None


def list_profiles(active_only: bool = False, user_id: int | None = None) -> list[dict]:
    conn = _require_conn()
    sql = "SELECT * FROM profiles"
    conds, params = [], []
    if active_only:
        conds.append("active = 1")
    if user_id is not None:
        conds.append("user_id = ?")
        params.append(user_id)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    return [_row_to_profile(r) for r in conn.execute(sql + " ORDER BY id", params)]


@_retry_on_locked
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


@_retry_on_locked
def set_criterion_weight(criterion_id: int, weight: int) -> None:
    conn = _require_conn()
    conn.execute("UPDATE criteria SET weight = ? WHERE id = ?", (weight, criterion_id))
    conn.commit()


@_retry_on_locked
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


@_retry_on_locked
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


def list_unnotified_top_matches(profile_id: int) -> list[dict]:
    """Pass-Matches des Profils, die noch nicht gemeldet wurden (notified_at IS NULL).
    Gejoint mit jobs für title/company/score im Digest."""
    conn = _require_conn()
    rows = conn.execute(
        """SELECT job_scores.fingerprint AS fingerprint, jobs.title AS title,
                  jobs.company AS company, job_scores.score AS score
           FROM job_scores JOIN jobs ON jobs.fingerprint = job_scores.fingerprint
           WHERE job_scores.profile_id = ?
             AND job_scores.category = 'Pass'
             AND job_scores.notified_at IS NULL
             AND jobs.status != 'expired'
           ORDER BY job_scores.score DESC""",
        (profile_id,))
    return [dict(r) for r in rows]


@_retry_on_locked
def mark_notified(profile_id: int, fingerprints: list[str]) -> None:
    """Setzt notified_at = now für die genannten Matches des Profils."""
    if not fingerprints:
        return
    conn = _require_conn()
    conn.executemany(
        "UPDATE job_scores SET notified_at = datetime('now') "
        "WHERE profile_id = ? AND fingerprint = ?",
        [(profile_id, fp) for fp in fingerprints])
    conn.commit()


def _row_to_analysis(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "profile_id": row["profile_id"],
        "cards": json.loads(row["cards_json"] or "{}"),
        "answers": json.loads(row["answers_json"] or "{}"),
        "status": row["status"],
        "created_at": row["created_at"],
    }


@_retry_on_locked
def create_analysis(profile_id: int) -> int:
    conn = _require_conn()
    cur = conn.execute(
        """INSERT INTO feedback_analysis (profile_id, cards_json, answers_json, status, created_at)
           VALUES (?, '{}', '{}', 'analyzing', datetime('now'))""",
        (profile_id,))
    conn.commit()
    return cur.lastrowid


def get_analysis(analysis_id: int) -> dict | None:
    conn = _require_conn()
    row = conn.execute(
        "SELECT * FROM feedback_analysis WHERE id = ?", (analysis_id,)).fetchone()
    return _row_to_analysis(row) if row else None


def get_latest_analysis(profile_id: int) -> dict | None:
    conn = _require_conn()
    row = conn.execute(
        "SELECT * FROM feedback_analysis WHERE profile_id = ? ORDER BY id DESC LIMIT 1",
        (profile_id,)).fetchone()
    return _row_to_analysis(row) if row else None


@_retry_on_locked
def save_analysis_cards(analysis_id: int, cards: dict) -> None:
    conn = _require_conn()
    conn.execute("UPDATE feedback_analysis SET cards_json = ? WHERE id = ?",
                 (json.dumps(cards, ensure_ascii=False), analysis_id))
    conn.commit()


@_retry_on_locked
def save_analysis_answers(analysis_id: int, answers: dict) -> None:
    conn = _require_conn()
    conn.execute("UPDATE feedback_analysis SET answers_json = ? WHERE id = ?",
                 (json.dumps(answers, ensure_ascii=False), analysis_id))
    conn.commit()


@_retry_on_locked
def set_analysis_status(analysis_id: int, status: str) -> None:
    conn = _require_conn()
    conn.execute("UPDATE feedback_analysis SET status = ? WHERE id = ?",
                 (status, analysis_id))
    conn.commit()


def _row_to_insight(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "profile_id": row["profile_id"],
        "kind": row["kind"],
        "text": row["text"],
        "payload": json.loads(row["payload_json"] or "{}"),
        "status": row["status"],
        "source": row["source"],
        "created_at": row["created_at"],
    }


@_retry_on_locked
def add_insight(profile_id: int, kind: str, text: str,
                payload: dict | None = None, source: str = "learned") -> int:
    conn = _require_conn()
    cur = conn.execute(
        """INSERT INTO insights (profile_id, kind, text, payload_json, status, source, created_at)
           VALUES (?, ?, ?, ?, 'proposed', ?, datetime('now'))""",
        (profile_id, kind, text, json.dumps(payload or {}, ensure_ascii=False), source))
    conn.commit()
    return cur.lastrowid


def list_insights(profile_id: int, status: str | None = None) -> list[dict]:
    conn = _require_conn()
    sql = "SELECT * FROM insights WHERE profile_id = ?"
    params: list = [profile_id]
    if status is not None:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY id"
    return [_row_to_insight(r) for r in conn.execute(sql, params)]


def _append_preference(conn: sqlite3.Connection, profile_id: int, text: str) -> None:
    row = conn.execute("SELECT data_json FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    data = json.loads(row["data_json"] or "{}") if row else {}
    data.setdefault("preferences", []).append(text)
    conn.execute("UPDATE profiles SET data_json = ? WHERE id = ?",
                 (json.dumps(data, ensure_ascii=False), profile_id))


@_retry_on_locked
def confirm_insight(insight_id: int) -> None:
    """Setzt status=confirmed und wirkt je kind: preference → profiles.data_json['preferences'],
    weight → criteria-Gewicht (per key, chirurgisch). location_boost bleibt no-op (reserviert)."""
    conn = _require_conn()
    row = conn.execute("SELECT * FROM insights WHERE id = ?", (insight_id,)).fetchone()
    if row is None:
        return
    conn.execute("UPDATE insights SET status = 'confirmed' WHERE id = ?", (insight_id,))
    if row["kind"] == "preference":
        _append_preference(conn, row["profile_id"], row["text"])
    elif row["kind"] == "weight":
        payload = json.loads(row["payload_json"] or "{}")
        conn.execute("UPDATE criteria SET weight = ? WHERE profile_id = ? AND key = ?",
                     (payload["new_weight"], row["profile_id"], payload["key"]))
    conn.commit()


@_retry_on_locked
def reject_insight(insight_id: int) -> None:
    conn = _require_conn()
    conn.execute("UPDATE insights SET status = 'rejected' WHERE id = ?", (insight_id,))
    conn.commit()


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


def list_jobs_with_scores(profile_id: int, locations: list[str] | None = None,
                          languages: list[str] | None = None) -> list[dict]:
    """Jobs mit Score/Begründung/Breakdown des gegebenen Profils, höchster Score zuerst
    (ungescorte Jobs ans Ende). Optionale Pool-Filter: Sprache (exakt IN), Standort
    (Substring-OR, LIKE %x%); leere/None-Liste = kein Filter."""
    conn = _require_conn()
    where = ["jobs.extraction_status = 'extracted'", "jobs.status != 'expired'"]
    params: list = [profile_id]
    if languages:
        where.append("jobs.language IN (%s)" % ",".join("?" * len(languages)))
        params += list(languages)
    if locations:
        where.append("(" + " OR ".join("jobs.location LIKE ?" for _ in locations) + ")")
        params += [f"%{loc}%" for loc in locations]
    rows = conn.execute(
        """SELECT jobs.*, job_scores.score AS profile_score,
                  job_scores.reason AS profile_reason,
                  job_scores.category AS profile_category,
                  job_scores.breakdown_json AS profile_breakdown_json
           FROM jobs
           LEFT JOIN job_scores
             ON job_scores.profile_id = ? AND job_scores.fingerprint = jobs.fingerprint
           WHERE """ + " AND ".join(where) + """
           ORDER BY (profile_score IS NULL), profile_score DESC,
                    jobs.first_seen DESC, jobs.id DESC""",
        params)
    return [
        {
            "job": _row_to_job(row),
            "score": row["profile_score"],
            "reason": row["profile_reason"],
            "category": row["profile_category"],
            "breakdown": json.loads(row["profile_breakdown_json"] or "{}"),
            "is_ausland": bool(row["is_ausland"]),
        }
        for row in rows
    ]


def get_feedback_map(profile_id: int) -> dict[str, str]:
    conn = _require_conn()
    rows = conn.execute(
        "SELECT fingerprint, vote FROM feedback WHERE profile_id = ?", (profile_id,))
    return {r["fingerprint"]: r["vote"] for r in rows}


def list_feedback_with_titles(profile_id: int) -> list[dict]:
    """Feedback + Job-Titel für Few-Shot-Beispiele im Scoring-Prompt, neueste zuerst."""
    conn = _require_conn()
    rows = conn.execute(
        """SELECT feedback.vote AS vote, jobs.title AS title
           FROM feedback JOIN jobs ON jobs.fingerprint = feedback.fingerprint
           WHERE feedback.profile_id = ?
           ORDER BY feedback.created_at DESC, feedback.id DESC""", (profile_id,))
    return [dict(r) for r in rows]


@_retry_on_locked
def toggle_favorite(profile_id: int, fingerprint: str) -> bool:
    """Fügt Favorit hinzu (True) oder entfernt ihn (False). Gibt neuen Zustand zurück."""
    conn = _require_conn()
    with conn:
        cur = conn.execute(
            "DELETE FROM favorites WHERE profile_id = ? AND fingerprint = ?",
            (profile_id, fingerprint))
        if cur.rowcount:
            return False
        conn.execute(
            "INSERT INTO favorites (profile_id, fingerprint, created_at) "
            "VALUES (?, ?, datetime('now'))",
            (profile_id, fingerprint))
    return True


def get_favorites_set(profile_id: int) -> set[str]:
    conn = _require_conn()
    rows = conn.execute(
        "SELECT fingerprint FROM favorites WHERE profile_id = ?", (profile_id,))
    return {r["fingerprint"] for r in rows}


def list_favorites_with_scores(profile_id: int, locations: list[str] | None = None,
                               languages: list[str] | None = None) -> list[dict]:
    """Favorisierte Jobs mit Score, Score DESC. Reuse der list_jobs_with_scores-JOIN
    (identische Entry-Struktur fürs Card-Rendering), gefiltert auf favorisierte fingerprints."""
    favs = get_favorites_set(profile_id)
    return [e for e in list_jobs_with_scores(profile_id, locations, languages)
            if e["job"].fingerprint in favs]


def list_favorites_with_titles(profile_id: int) -> list[dict]:
    """Favorisierte Job-Titel als STARKE Positiv-Beispiele fürs Scoring, neueste zuerst."""
    conn = _require_conn()
    rows = conn.execute(
        """SELECT jobs.title AS title
           FROM favorites JOIN jobs ON jobs.fingerprint = favorites.fingerprint
           WHERE favorites.profile_id = ?
           ORDER BY favorites.created_at DESC, favorites.id DESC""", (profile_id,))
    return [dict(r) for r in rows]


def list_feedback_with_jobs(profile_id: int) -> list[dict]:
    """Vote + voller Job-Inhalt für den Analyse-Agent (Muster/Widersprüche), neueste zuerst."""
    conn = _require_conn()
    rows = conn.execute(
        """SELECT feedback.vote AS vote, jobs.fingerprint AS fingerprint, jobs.title AS title,
                  jobs.company AS company, jobs.location AS location,
                  jobs.remote_flag AS remote_flag, jobs.employment_type AS employment_type,
                  jobs.requirements_json AS requirements_json, jobs.tech_stack_json AS tech_stack_json
           FROM feedback JOIN jobs ON jobs.fingerprint = feedback.fingerprint
           WHERE feedback.profile_id = ?
           ORDER BY feedback.created_at DESC, feedback.id DESC""", (profile_id,))
    out = []
    for r in rows:
        out.append({
            "vote": r["vote"], "fingerprint": r["fingerprint"], "title": r["title"],
            "company": r["company"], "location": r["location"] or "",
            "remote_flag": r["remote_flag"] or "", "employment_type": r["employment_type"] or "",
            "requirements": json.loads(r["requirements_json"] or "[]"),
            "tech_stack": json.loads(r["tech_stack_json"] or "[]"),
        })
    return out


_LEARN_REMINDER_THRESHOLD = 10


def learn_reminder_status(profile_id: int) -> dict:
    """Neue Votes seit der letzten Member-Lern-Analyse (profiles.last_learn_reminder_at).
    due=True ab _LEARN_REMINDER_THRESHOLD neuen Votes seit dem letzten touch (oder seit je,
    falls noch nie gelernt wurde)."""
    conn = _require_conn()
    row = conn.execute(
        "SELECT last_learn_reminder_at FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    since = row["last_learn_reminder_at"] if row else None
    if since:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM feedback WHERE profile_id = ? AND created_at > ?",
            (profile_id, since)).fetchone()["c"]
    else:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM feedback WHERE profile_id = ?", (profile_id,)).fetchone()["c"]
    return {"new_votes": count, "due": count >= _LEARN_REMINDER_THRESHOLD}


@_retry_on_locked
def touch_learn_reminder(profile_id: int) -> None:
    conn = _require_conn()
    conn.execute(
        "UPDATE profiles SET last_learn_reminder_at = datetime('now') WHERE id = ?",
        (profile_id,))
    conn.commit()


@_retry_on_locked
def enqueue_jobs_for_rescore(profile_id: int) -> int:
    """Setzt jobs.score=NULL für extrahierte Jobs, damit der Scoring-Agent sie via
    list_unscored_extracted (to_score-Zweig) mit den neuen Präferenzen neu bewertet.
    Gibt die Anzahl betroffener Jobs zurück. profile_id ist Signatur-durchgezogen
    (Default-Profil-Scope; list_unscored_extracted ist global)."""
    conn = _require_conn()
    cur = conn.execute(
        "UPDATE jobs SET score = NULL WHERE extraction_status = 'extracted'")
    conn.commit()
    return cur.rowcount


SPAR_MODUS_DEFAULT = {"max_jobs": None, "neighbor_roles": True, "locations": [], "languages": ["de"]}


def get_spar_modus(profile_data: dict) -> dict:
    """Spar-Modus mit Defaults: max_jobs=None heißt unbegrenzt, neighbor_roles=True
    heißt bob-scan darf Nachbarrollen generieren."""
    return {**SPAR_MODUS_DEFAULT, **(profile_data.get("spar_modus") or {})}


@_retry_on_locked
def set_spar_modus(user_id: int, max_jobs: int | None, neighbor_roles: bool,
                   locations: list[str] | None = None,
                   languages: list[str] | None = None) -> int:
    """Schreibt die Spar-Modus-Einstellung in data_json ALLER Profile des Users
    (Website-Einstellung ist pro User, Persistenz pro Profil — get_my_profile liefert
    sie je Profil an die Skills). Gibt die Anzahl aktualisierter Profile zurück."""
    conn = _require_conn()
    count = 0
    for p in list_profiles(user_id=user_id):
        data = p["data"]
        data["spar_modus"] = {"max_jobs": max_jobs, "neighbor_roles": bool(neighbor_roles),
                              "locations": locations or [], "languages": languages or ["de"]}
        conn.execute("UPDATE profiles SET data_json = ? WHERE id = ?",
                     (json.dumps(data, ensure_ascii=False), p["id"]))
        count += 1
    conn.commit()
    return count


NOTIFY_PREF_DEFAULT = {"email": True}


def get_notify_pref(profile_data: dict) -> dict:
    """Email-Benachrichtigung an/aus; default True (Slot data_json.notifications)."""
    return {**NOTIFY_PREF_DEFAULT, **(profile_data.get("notifications") or {})}


@_retry_on_locked
def set_notify_pref(user_id: int, email_on: bool) -> int:
    """Schreibt data_json.notifications in ALLE Profile des Users (Einstellung pro User,
    Persistenz pro Profil). Gibt die Anzahl aktualisierter Profile zurück."""
    conn = _require_conn()
    count = 0
    for p in list_profiles(user_id=user_id):
        data = p["data"]
        data["notifications"] = {"email": bool(email_on)}
        conn.execute("UPDATE profiles SET data_json = ? WHERE id = ?",
                     (json.dumps(data, ensure_ascii=False), p["id"]))
        count += 1
    conn.commit()
    return count


SCAN_PORTALS_DEFAULT = ["stepstone", "indeed"]


def get_scan_portals(profile_data: dict) -> list[str]:
    """Portal-Auswahl für den residential Browser-Scan (bob-scan). Default = alle;
    leere Liste = bewusstes Opt-out. Unbekannte Namen werden gefiltert."""
    portals = profile_data.get("scan_portals")
    if not isinstance(portals, list):
        return list(SCAN_PORTALS_DEFAULT)
    return [p for p in portals if p in SCAN_PORTALS_DEFAULT]


@_retry_on_locked
def set_scan_portals(user_id: int, portals: list[str]) -> int:
    """Schreibt data_json.scan_portals in ALLE Profile des Users (Einstellung pro
    User, Persistenz pro Profil — Muster set_spar_modus). Gibt Anzahl Profile zurück."""
    conn = _require_conn()
    clean = [p for p in portals if p in SCAN_PORTALS_DEFAULT]
    count = 0
    for p in list_profiles(user_id=user_id):
        data = p["data"]
        data["scan_portals"] = clean
        conn.execute("UPDATE profiles SET data_json = ? WHERE id = ?",
                     (json.dumps(data, ensure_ascii=False), p["id"]))
        count += 1
    conn.commit()
    return count


@_retry_on_locked
def enqueue_member_rescore(profile_id: int, max_jobs: int | None = None,
                           locations: list[str] | None = None,
                           languages: list[str] | None = None) -> int:
    """Merkt die relevantesten gescorten, extrahierten Jobs des Profils für ein
    Member-LLM-Rescore vor: Floor (keine No-Gos) + Rang (Score DESC) + optionaler
    Cap (max_jobs, None = unbegrenzt). Optionale Pool-Filter: Sprache (exakt IN),
    Standort (Substring-OR, LIKE %x%); leere/None-Liste = kein Filter. Idempotent per
    INSERT OR IGNORE; der Cap gilt pro Enqueue. Gibt Anzahl NEU vorgemerkter Jobs zurück."""
    conn = _require_conn()
    where = ["job_scores.profile_id = ?", "jobs.extraction_status = 'extracted'",
             "job_scores.category != 'No-Go'"]
    params: list = [profile_id]
    if languages:
        where.append("jobs.language IN (%s)" % ",".join("?" * len(languages)))
        params += list(languages)
    if locations:
        where.append("(" + " OR ".join("jobs.location LIKE ?" for _ in locations) + ")")
        params += [f"%{loc}%" for loc in locations]
    sql = (
        "INSERT OR IGNORE INTO member_rescore_queue (profile_id, fingerprint, created_at) "
        "SELECT job_scores.profile_id, job_scores.fingerprint, datetime('now') "
        "FROM job_scores JOIN jobs ON jobs.fingerprint = job_scores.fingerprint "
        "WHERE " + " AND ".join(where) + " "
        "ORDER BY job_scores.score DESC"
    )
    if max_jobs is not None:
        sql += " LIMIT ?"
        params.append(int(max_jobs))
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.rowcount


def list_member_rescore(profile_ids: list[int], limit: int | None = None) -> list[dict]:
    """Vorgemerkte Rescore-Jobs der Profile — Item-Shape wie list_unscored_for_profiles
    plus profile_id (der Skill scored gezielt für dieses eine Profil neu)."""
    conn = _require_conn()
    if not profile_ids:
        return []
    placeholders = ",".join("?" for _ in profile_ids)
    sql = (
        "SELECT q.profile_id, jobs.fingerprint, jobs.title, jobs.company, jobs.location, "
        "jobs.employment_type, jobs.requirements_json, jobs.tech_stack_json "
        "FROM member_rescore_queue q JOIN jobs ON jobs.fingerprint = q.fingerprint "
        "WHERE q.profile_id IN (" + placeholders + ") ORDER BY jobs.id"
    )
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    out = []
    for r in conn.execute(sql, list(profile_ids)):
        out.append({
            "profile_id": r["profile_id"],
            "fingerprint": r["fingerprint"],
            "title": r["title"],
            "company": r["company"],
            "location": r["location"] or "",
            "employment_type": r["employment_type"] or "",
            "requirements": json.loads(r["requirements_json"] or "[]"),
            "tech_stack": json.loads(r["tech_stack_json"] or "[]"),
        })
    return out


@_retry_on_locked
def clear_member_rescore(profile_id: int, fingerprint: str) -> None:
    conn = _require_conn()
    conn.execute("DELETE FROM member_rescore_queue WHERE profile_id = ? AND fingerprint = ?",
                 (profile_id, fingerprint))
    conn.commit()


@_retry_on_locked
def set_criterion_weight_by_key(profile_id: int, key: str, weight: int) -> None:
    """Gewicht eines Kriteriums per key setzen (Muster aus confirm_insight)."""
    conn = _require_conn()
    conn.execute("UPDATE criteria SET weight = ? WHERE profile_id = ? AND key = ?",
                 (weight, profile_id, key))
    conn.commit()


@_retry_on_locked
def set_sources(fingerprint: str, sources: list) -> None:
    conn = _require_conn()
    conn.execute("UPDATE jobs SET sources_json = ? WHERE fingerprint = ?",
                 (json.dumps(sources, ensure_ascii=False), fingerprint))
    conn.commit()


@_retry_on_locked
def delete_job(fingerprint: str) -> None:
    """Job inkl. abhängiger Scores/Feedback löschen (Indeed-Dup-Cleanup)."""
    conn = _require_conn()
    conn.execute("DELETE FROM job_scores WHERE fingerprint = ?", (fingerprint,))
    conn.execute("DELETE FROM feedback WHERE fingerprint = ?", (fingerprint,))
    conn.execute("DELETE FROM jobs WHERE fingerprint = ?", (fingerprint,))
    conn.commit()


@_retry_on_locked
def rescore_profile(profile_id: int) -> list[str]:
    """Rechnet alle job_scores des Profils deterministisch aus breakdown_json neu
    (nach Gewichts-Änderung im Feintuning) — kein LLM. Veto-Zeilen (leeres breakdown)
    bleiben unberührt. Aktualisiert bei Default-Profil zusätzlich die jobs-Tabelle.
    Gibt die Fingerprints zurück, deren Score sich geändert hat."""
    conn = _require_conn()
    criteria = list_criteria(profile_id)
    profile = get_profile(profile_id)
    is_default = profile is not None and profile["is_default"]
    changed: list[str] = []
    rows = conn.execute(
        "SELECT fingerprint, score, breakdown_json FROM job_scores WHERE profile_id = ?",
        (profile_id,)).fetchall()
    for r in rows:
        breakdown = json.loads(r["breakdown_json"] or "{}")
        if not breakdown:
            continue
        new_score = scoring.compute_weighted_score(breakdown, criteria)
        if new_score is None:
            continue
        category = scoring.category_for_score(new_score)
        reason = scoring.top_reasons(breakdown, criteria)
        fp = r["fingerprint"]
        conn.execute(
            "UPDATE job_scores SET score = ?, category = ?, reason = ? "
            "WHERE profile_id = ? AND fingerprint = ?",
            (new_score, category, reason, profile_id, fp))
        if is_default:
            conn.execute(
                "UPDATE jobs SET score = ?, category = ?, score_reason = ? WHERE fingerprint = ?",
                (new_score, category, reason, fp))
        if r["score"] != new_score:
            changed.append(fp)
    conn.commit()
    return changed


def score_profile_deterministic(profile_id: int, only_missing: bool = False) -> int:
    """LLM-freies Scoring eines Member-Profils über den kompletten extrahierten Job-Pool:
    wendet den Weights-/No-Go-Katalog (scoring.score_job_deterministic) an und schreibt je Job
    einen job_scores-Eintrag. Gibt die Anzahl bewerteter Jobs zurück. Kein jobs-Tabellen-Update
    (Member-Profile sind nie is_default) und kein LLM-Aufruf.
    only_missing=True bewertet nur Jobs OHNE bestehenden job_scores-Eintrag dieses Profils —
    damit überschreibt das Auto-Scoring nach einem MCP-Extraktion-Push keine per push_batch
    gelieferten Member-LLM-Scores."""
    conn = _require_conn()
    profile = get_profile(profile_id)
    if profile is None:
        return 0
    profile_data = profile["data"]
    active_no_gos = profile_data.get("no_gos", [])
    criteria = list_criteria(profile_id)
    if only_missing:
        rows = conn.execute(
            """SELECT * FROM jobs WHERE extraction_status = 'extracted'
               AND NOT EXISTS (SELECT 1 FROM job_scores
                               WHERE job_scores.profile_id = ?
                               AND job_scores.fingerprint = jobs.fingerprint)""",
            (profile_id,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE extraction_status = 'extracted'").fetchall()
    count = 0
    for row in rows:
        job = _row_to_job(row)
        score, breakdown, category, reason = scoring.score_job_deterministic(
            job, criteria, active_no_gos, profile_data)
        upsert_job_score(profile_id, job.fingerprint, score, reason, category, breakdown)
        count += 1
    return count


@_retry_on_locked
def log_event(event_type: str, user_id: int | None = None, meta: dict | None = None) -> None:
    conn = _require_conn()
    conn.execute(
        "INSERT INTO events (ts, user_id, event_type, meta_json) "
        "VALUES (strftime('%s', 'now'), ?, ?, ?)",
        (user_id, event_type, json.dumps(meta or {}, ensure_ascii=False)))
    conn.commit()


@_retry_on_locked
def create_member_feedback(user_id: int, text: str) -> int:
    conn = _require_conn()
    cur = conn.execute(
        "INSERT INTO member_feedback (user_id, text, created_at) VALUES (?, ?, datetime('now'))",
        (user_id, text),
    )
    conn.commit()
    return cur.lastrowid


def list_member_feedback() -> list[dict]:
    conn = _require_conn()
    rows = conn.execute(
        "SELECT mf.id, mf.text, mf.created_at, u.email AS user_email "
        "FROM member_feedback mf JOIN users u ON u.id = mf.user_id "
        "ORDER BY mf.id DESC"
    ).fetchall()
    return [dict(r) for r in rows]


_FUNNEL_STEPS = ("onboarding_start", "profil_erstellt", "feedback_gegeben")


def get_metrics_summary(days: int = 7) -> dict:
    """Owner-Dashboard-Kennzahlen über die letzten `days` Tage: aktive Member (Rolle
    'member' mit mindestens einem Event im Fenster), Onboarding-Completion (Profil
    erstellt / Onboarding gestartet, im selben Fenster), Sessions heute (Pageviews
    mit heutigem Datum) und rohe Funnel-Counts je Schritt."""
    conn = _require_conn()
    since = f"-{int(days)} days"
    active_members = conn.execute(
        """SELECT COUNT(DISTINCT events.user_id) AS n FROM events
           JOIN users ON users.id = events.user_id
           WHERE users.role = 'member' AND events.ts >= strftime('%s', 'now', ?)""",
        (since,)).fetchone()["n"]
    sessions_today = conn.execute(
        """SELECT COUNT(*) AS n FROM events
           WHERE event_type = 'pageview' AND date(ts, 'unixepoch') = date('now')""",
    ).fetchone()["n"]
    funnel_counts = {}
    for step in _FUNNEL_STEPS:
        row = conn.execute(
            """SELECT COUNT(*) AS n FROM events
               WHERE event_type = ? AND ts >= strftime('%s', 'now', ?)""",
            (step, since)).fetchone()
        funnel_counts[step] = row["n"]
    onboarding_completion_rate = (
        round(funnel_counts["profil_erstellt"] / funnel_counts["onboarding_start"] * 100)
        if funnel_counts["onboarding_start"] else 0)
    return {
        "active_members": active_members,
        "onboarding_completion_rate": onboarding_completion_rate,
        "sessions_today": sessions_today,
        "funnel_counts": funnel_counts,
    }


def get_daily_event_counts(days: int = 14) -> list[dict]:
    """Event-Volumen pro Tag für den Ping-Verlauf, älteste zuerst, Lücken mit count=0
    aufgefüllt (letzter Eintrag ist immer heute)."""
    conn = _require_conn()
    rows = conn.execute(
        """SELECT date(ts, 'unixepoch') AS day, COUNT(*) AS n FROM events
           WHERE ts >= strftime('%s', 'now', ?) GROUP BY day""",
        (f"-{int(days) - 1} days",)).fetchall()
    counts = {r["day"]: r["n"] for r in rows}
    out = []
    for i in range(days - 1, -1, -1):
        day = conn.execute("SELECT date('now', ?) AS d", (f"-{i} days",)).fetchone()["d"]
        out.append({"day": day, "count": counts.get(day, 0)})
    return out


def _row_to_custom_portal(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "url": row["url"],
        "typ": row["typ"],
        "search_url_template": row["search_url_template"],
        "detail_url_pattern": row["detail_url_pattern"],
        "submitted_by": row["submitted_by"],
        "status": row["status"],
        "firecrawl_needed": bool(row["firecrawl_needed"]),
        "check_ergebnis": json.loads(row["check_ergebnis_json"]) if row["check_ergebnis_json"] else None,
        "created_at": row["created_at"],
        "activated_at": row["activated_at"],
    }


@_retry_on_locked
def create_custom_portal(url: str, typ: str, submitted_by: int,
                         search_url_template: str | None = None,
                         detail_url_pattern: str | None = None) -> int:
    conn = _require_conn()
    cur = conn.execute(
        """INSERT INTO custom_portals
           (url, typ, search_url_template, detail_url_pattern, submitted_by, created_at)
           VALUES (?, ?, ?, ?, ?, datetime('now'))""",
        (url, typ, search_url_template, detail_url_pattern, submitted_by))
    conn.commit()
    return cur.lastrowid


def get_custom_portal(portal_id: int) -> dict | None:
    conn = _require_conn()
    row = conn.execute("SELECT * FROM custom_portals WHERE id = ?", (portal_id,)).fetchone()
    return _row_to_custom_portal(row) if row else None


def list_custom_portals(status: str | None = None) -> list[dict]:
    conn = _require_conn()
    sql = "SELECT * FROM custom_portals"
    params: list = []
    if status is not None:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY id DESC"
    return [_row_to_custom_portal(r) for r in conn.execute(sql, params)]


@_retry_on_locked
def save_check_result(portal_id: int, result: dict) -> None:
    conn = _require_conn()
    status = "compatible" if result.get("compatible") else "needs_firecrawl_pending"
    conn.execute(
        "UPDATE custom_portals SET check_ergebnis_json = ?, status = ? WHERE id = ?",
        (json.dumps(result, ensure_ascii=False), status, portal_id))
    conn.commit()


@_retry_on_locked
def activate_custom_portal(portal_id: int) -> None:
    conn = _require_conn()
    row = conn.execute("SELECT status FROM custom_portals WHERE id = ?", (portal_id,)).fetchone()
    if row is None:
        return
    firecrawl_needed = 1 if row["status"] == "needs_firecrawl_pending" else 0
    conn.execute(
        """UPDATE custom_portals SET status = 'active', firecrawl_needed = ?,
           activated_at = datetime('now') WHERE id = ?""",
        (firecrawl_needed, portal_id))
    conn.commit()


def list_availability_candidates(older_than_days: int = 3) -> list[dict]:
    """Nicht-expired Jobs, deren last_seen älter als older_than_days ist (frisch
    re-seene Jobs fallen raus → schont Portal-Requests). Item: fingerprint + erste
    Quell-URL aus sources_json."""
    conn = _require_conn()
    cutoff = (date.today() - timedelta(days=older_than_days)).isoformat()
    rows = conn.execute(
        "SELECT fingerprint, sources_json FROM jobs "
        "WHERE status != 'expired' AND last_seen IS NOT NULL AND last_seen < ? "
        "ORDER BY id", (cutoff,))
    out = []
    for r in rows:
        sources = json.loads(r["sources_json"] or "[]")
        url = sources[0].get("url", "") if sources else ""
        if url:
            out.append({"fingerprint": r["fingerprint"], "url": url})
    return out


@_retry_on_locked
def bump_unavailable_strike(fingerprint: str) -> int:
    conn = _require_conn()
    conn.execute(
        "UPDATE jobs SET unavailable_strikes = unavailable_strikes + 1 "
        "WHERE fingerprint = ?", (fingerprint,))
    conn.commit()
    row = conn.execute(
        "SELECT unavailable_strikes FROM jobs WHERE fingerprint = ?", (fingerprint,)).fetchone()
    return row["unavailable_strikes"]


@_retry_on_locked
def reset_unavailable_strike(fingerprint: str) -> None:
    conn = _require_conn()
    conn.execute("UPDATE jobs SET unavailable_strikes = 0 WHERE fingerprint = ?", (fingerprint,))
    conn.commit()


@_retry_on_locked
def mark_expired(fingerprint: str) -> None:
    conn = _require_conn()
    conn.execute("UPDATE jobs SET status = 'expired' WHERE fingerprint = ?", (fingerprint,))
    conn.commit()
