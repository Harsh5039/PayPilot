"""SQLite persistence: sessions, messages, consent ledger, applications, audit trail."""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from app.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'en',
    product TEXT NOT NULL DEFAULT 'loan',
    step TEXT NOT NULL DEFAULT 'intent',
    slots TEXT NOT NULL DEFAULT '{}',
    tracker TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS consents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    scope TEXT NOT NULL,
    purpose TEXT NOT NULL,
    status TEXT NOT NULL,
    granted_at TEXT,
    expires_at TEXT,
    revoked_at TEXT,
    version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS applications (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    lender_id TEXT NOT NULL,
    lender_name TEXT NOT NULL,
    amount REAL NOT NULL,
    tenure_months INTEGER NOT NULL,
    apr REAL NOT NULL,
    emi REAL NOT NULL,
    processing_fee REAL NOT NULL,
    total_payable REAL NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decision_at TEXT,
    events TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS policies (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    insurer TEXT NOT NULL,
    product TEXT NOT NULL,
    sum_insured INTEGER NOT NULL,
    members TEXT NOT NULL,
    annual_premium INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    events TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    filename TEXT,
    confidence REAL,
    extracted TEXT NOT NULL DEFAULT '{}',
    verified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    application_id TEXT,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT,
    read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT NOT NULL,
    ms INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_consent_session ON consents(session_id);
CREATE INDEX IF NOT EXISTS idx_app_session ON applications(session_id);
CREATE INDEX IF NOT EXISTS idx_audit_session ON audit(session_id);
CREATE INDEX IF NOT EXISTS idx_policy_session ON policies(session_id);
CREATE INDEX IF NOT EXISTS idx_document_app ON documents(application_id);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@contextmanager
def conn():
    c = sqlite3.connect(settings.database_path, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


MIGRATIONS = [
    ("sessions", "owner_hash", "TEXT"),
    ("sessions", "last_turn", "TEXT NOT NULL DEFAULT '{}'"),
    ("applications", "nominee", "TEXT"),
    ("applications", "reference", "TEXT"),
    ("consents", "shared_with", "TEXT"),
    ("applications", "employment", "TEXT DEFAULT 'salaried'"),
    ("applications", "purpose", "TEXT DEFAULT 'personal'"),
    ("applications", "offer_id", "TEXT"),
    ("applications", "kyc_verified", "INTEGER NOT NULL DEFAULT 0"),
    ("policies", "ped", "TEXT NOT NULL DEFAULT 'no'"),
    ("policies", "medical_declaration", "TEXT NOT NULL DEFAULT '[]'"),
    ("policies", "quote_expires_at", "TEXT"),
    ("documents", "sha256", "TEXT"),
    ("documents", "verification_status", "TEXT NOT NULL DEFAULT 'pending'"),
    ("documents", "failure_reasons", "TEXT NOT NULL DEFAULT '[]'"),
]


def init_db() -> None:
    with conn() as c:
        c.executescript(SCHEMA)
        # additive migrations, so an existing demo database keeps working
        for table, column, decl in MIGRATIONS:
            cols = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def one(sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    with conn() as c:
        return c.execute(sql, tuple(params)).fetchone()


def many(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    with conn() as c:
        return list(c.execute(sql, tuple(params)).fetchall())


def run(sql: str, params: Iterable[Any] = ()) -> None:
    with conn() as c:
        c.execute(sql, tuple(params))


# ---------------------------------------------------------------- sessions
def create_session(language: str = "en") -> dict:
    sid = new_id("sess")
    with conn() as c:
        c.execute(
            "INSERT INTO sessions (id, created_at, language, step, slots, tracker) VALUES (?,?,?,?,?,?)",
            (sid, now(), language, "intent", "{}", "{}"),
        )
    return get_session(sid)


def get_session(sid: str) -> dict | None:
    row = one("SELECT * FROM sessions WHERE id = ?", (sid,))
    if not row:
        return None
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "language": row["language"],
        "product": row["product"],
        "step": row["step"],
        "slots": json.loads(row["slots"]),
        "tracker": json.loads(row["tracker"]),
    }


def save_session(sid: str, *, language: str | None = None, step: str | None = None,
                 slots: dict | None = None, tracker: dict | None = None,
                 product: str | None = None) -> None:
    sets, params = [], []
    if product is not None:
        sets.append("product = ?"); params.append(product)
    if language is not None:
        sets.append("language = ?"); params.append(language)
    if step is not None:
        sets.append("step = ?"); params.append(step)
    if slots is not None:
        sets.append("slots = ?"); params.append(json.dumps(slots))
    if tracker is not None:
        sets.append("tracker = ?"); params.append(json.dumps(tracker))
    if not sets:
        return
    params.append(sid)
    run(f"UPDATE sessions SET {', '.join(sets)} WHERE id = ?", params)


def add_message(sid: str, role: str, content: str) -> None:
    run("INSERT INTO messages (session_id, role, content, created_at) VALUES (?,?,?,?)",
        (sid, role, content, now()))


def messages(sid: str, limit: int = 200) -> list[dict]:
    """The conversation in chronological order (oldest first)."""
    rows = many("SELECT role, content, created_at FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (sid, limit))
    return [dict(r) for r in reversed(rows)]


def message_count(sid: str) -> int:
    row = one("SELECT COUNT(*) AS c FROM messages WHERE session_id = ?", (sid,))
    return row["c"] if row else 0


# ---------------------------------------------------------------- consent ledger
def grant_consent(sid: str, scope: str, purpose: str, shared_with: str | None = None) -> dict:
    """Keep each grant as a new event: never overwrite an earlier consent."""
    granted_at = now()
    expires_at = (datetime.now(timezone.utc) + timedelta(days=settings.consent_ttl_days)).isoformat(timespec="seconds")
    with conn() as c:
        prev = c.execute("SELECT COALESCE(MAX(version), 0) AS v FROM consents WHERE session_id = ? AND scope = ?",
                         (sid, scope)).fetchone()
        version = prev["v"] + 1
        c.execute("UPDATE consents SET status = 'superseded', revoked_at = ? "
                  "WHERE session_id = ? AND scope = ? AND status = 'granted'", (granted_at, sid, scope))
        c.execute("""INSERT INTO consents (session_id, scope, purpose, status, granted_at,
                  expires_at, version, shared_with) VALUES (?,?,?,'granted',?,?,?,?)""",
                  (sid, scope, purpose, granted_at, expires_at, version, shared_with))
    return {"scope": scope, "purpose": purpose, "status": "granted",
            "granted_at": granted_at, "expires_at": expires_at, "version": version,
            "shared_with": shared_with}


def revoke_consent(sid: str, scope: str) -> bool:
    row = one("SELECT id FROM consents WHERE session_id = ? AND scope = ? AND status = 'granted'", (sid, scope))
    if not row:
        return False
    run("UPDATE consents SET status = 'revoked', revoked_at = ? WHERE id = ?", (now(), row["id"]))
    return True


def active_scopes(sid: str) -> set[str]:
    rows = many("SELECT scope, expires_at FROM consents WHERE session_id = ? AND status = 'granted'", (sid,))
    live = set()
    for r in rows:
        exp = r["expires_at"]
        if exp and datetime.fromisoformat(exp) < datetime.now(timezone.utc):
            continue
        live.add(r["scope"])
    return live


def consent_ledger(sid: str) -> list[dict]:
    rows = many("SELECT scope, purpose, status, granted_at, expires_at, revoked_at, version, shared_with "
                "FROM consents WHERE session_id = ? ORDER BY id", (sid,))
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- audit
def audit(sid: str, kind: str, detail: str, ms: int = 0) -> None:
    run("INSERT INTO audit (session_id, ts, kind, detail, ms) VALUES (?,?,?,?,?)", (sid, now(), kind, detail, ms))


def audit_log(sid: str, limit: int = 200) -> list[dict]:
    rows = many("SELECT ts, kind, detail, ms FROM audit WHERE session_id = ? ORDER BY id LIMIT ?", (sid, limit))
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- documents
def add_document(app_id: str, doc_type: str, filename: str, confidence: float,
                 extracted: dict, sha256: str, verification_status: str,
                 failure_reasons: list[str]) -> dict:
    with conn() as c:
        # The latest document replaces previous evidence of the same type.
        c.execute("DELETE FROM documents WHERE application_id = ? AND doc_type = ?", (app_id, doc_type))
        c.execute("""INSERT INTO documents (application_id, doc_type, filename, confidence,
            extracted, created_at, sha256, verification_status, failure_reasons, verified)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (app_id, doc_type, filename, confidence, json.dumps(extracted), now(),
             sha256, verification_status, json.dumps(failure_reasons),
             int(verification_status == "matched_demo")))
    return {"doc_type": doc_type, "filename": filename, "confidence": confidence,
            "extracted": extracted, "sha256": sha256, "verification_status": verification_status,
            "failure_reasons": failure_reasons, "verified": verification_status == "matched_demo"}


def documents_for(app_id: str) -> list[dict]:
    rows = many("SELECT doc_type, filename, confidence, extracted, verified, created_at, sha256, verification_status, failure_reasons "
                "FROM documents WHERE application_id = ? ORDER BY id", (app_id,))
    out = []
    for r in rows:
        d = dict(r)
        d["extracted"] = json.loads(d["extracted"])
        d["verified"] = bool(d["verified"])
        d["failure_reasons"] = json.loads(d["failure_reasons"] or "[]")
        out.append(d)
    return out


def verify_documents(app_id: str) -> None:
    run("UPDATE documents SET verified = 1 WHERE application_id = ? AND verification_status = 'matched_demo'", (app_id,))


# ---------------------------------------------------------------- notifications
def notify(sid: str, title: str, body: str, app_id: str | None = None,
           status: str | None = None) -> dict:
    run("""INSERT INTO notifications (session_id, application_id, title, body, status, created_at)
           VALUES (?,?,?,?,?,?)""", (sid, app_id, title, body, status, now()))
    return {"title": title, "body": body, "application_id": app_id, "status": status, "read": False}


def notifications_for(sid: str, limit: int = 30) -> list[dict]:
    rows = many("SELECT title, body, application_id, status, read, created_at FROM notifications "
                "WHERE session_id = ? ORDER BY id DESC LIMIT ?", (sid, limit))
    return [dict(r) for r in rows]
