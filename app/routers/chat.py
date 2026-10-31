"""Session lifecycle, the chat turn, and the audit trail."""
from __future__ import annotations

import json
from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, field_validator

from app import db
from app.services import agent, lending, sarvam
from app.security import establish_owner, owner_hash, COOKIE

router = APIRouter(prefix="/api", tags=["chat"])


@router.get("/history")
def history(request: Request):
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "browser_session_required")
    owned = owner_hash(token)
    applications = db.many("SELECT a.* FROM applications a JOIN sessions s ON s.id = a.session_id WHERE s.owner_hash = ? ORDER BY a.created_at DESC", (owned,))
    policies = db.many("SELECT p.* FROM policies p JOIN sessions s ON s.id = p.session_id WHERE s.owner_hash = ? ORDER BY p.created_at DESC", (owned,))
    return {"applications": [dict(a) for a in applications], "policies": [dict(p) for p in policies]}


class NewSession(BaseModel):
    language: str = Field(default="en", pattern="^(en|hi)$")
    product: str = Field(default="loan", pattern="^(loan|insurance)$")


class ChatIn(BaseModel):
    session_id: str
    text: str = Field(default="", max_length=10000)
    choice: str | None = Field(default=None, max_length=200)
    language: str | None = Field(default=None, pattern="^(en|hi)$")

    @field_validator("choice")
    @classmethod
    def validate_choice(cls, value):
        if value and ":" in value:
            prefix, raw = value.split(":", 1)
            if prefix in {"loan", "amount", "tenure", "budget", "sum"}:
                if prefix == "budget" and raw == "any":
                    return value
                if not raw.isascii() or not raw.isdigit():
                    raise ValueError("Choose a valid numeric option")
                number = int(raw)
                if prefix == "tenure" and number not in (12, 24, 36, 48, 60):
                    raise ValueError("Unsupported tenure")
                if prefix == "sum" and number not in (500000, 1000000, 2500000, 5000000):
                    raise ValueError("Unsupported coverage")
                if not 0 < number <= 5000000:
                    raise ValueError("Amount out of range")
        return value


def _session(session_id: str) -> dict:
    s = db.get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail={"error": "session_not_found", "session_id": session_id})
    return s


@router.post("/sessions", status_code=201)
def create_session(request: Request, response: Response, body: NewSession | None = None):
    s = db.create_session((body.language if body else "en"))
    s["product"] = body.product if body else "loan"
    db.save_session(s["id"], product=s["product"])
    db.run("UPDATE sessions SET owner_hash = ? WHERE id = ?", (establish_owner(request, response), s["id"]))
    db.audit(s["id"], "session.create", f"language={s['language']}", 2)
    db.audit(s["id"], "llm.mode", sarvam.status()["mode"], 1)
    out = agent.greeting(s)
    return {"session_id": s["id"], "language": s["language"], **out}


@router.get("/sessions/{session_id}")
def read_session(session_id: str):
    s = _session(session_id)
    return {
        "session": {k: s[k] for k in ("id", "created_at", "language", "product", "step")},
        "slots": s["slots"],
        "tracker": s["tracker"],
        "consents": db.consent_ledger(session_id),
        "applications": [a["id"] for a in _apps(session_id)],
        "resumable": [{"id": a["id"], "reference": a["reference"], "status": a["status"],
                       "lender": a["lender_name"], "amount": a["amount"]}
                      for a in lending.resumable(session_id)],
        "notifications": db.notifications_for(session_id, 10),
        "messages": db.messages(session_id),
        "message_count": db.message_count(session_id),
        "llm": sarvam.status(),
        "last_turn": agent.localize_turn(json.loads(db.one("SELECT last_turn FROM sessions WHERE id = ?", (session_id,))["last_turn"]), s["language"]),
    }


class LanguageIn(BaseModel):
    language: str = Field(pattern="^(en|hi)$")


@router.patch("/sessions/{session_id}/language")
def change_language(session_id: str, body: LanguageIn):
    _session(session_id)
    db.save_session(session_id, language=body.language)
    row = db.one("SELECT last_turn FROM sessions WHERE id = ?", (session_id,))
    turn = agent.localize_turn(json.loads(row["last_turn"]), body.language)
    return turn


@router.get("/sessions/{session_id}/messages")
def read_messages(session_id: str, limit: int = Query(default=200, ge=1, le=200)):
    """Chronological transcript, so a reloaded page can rebuild the conversation."""
    _session(session_id)
    return {"session_id": session_id, "messages": db.messages(session_id, limit)}


def _apps(session_id: str):
    return lending.applications_for(session_id)


@router.post("/chat")
async def chat(body: ChatIn):
    s = _session(body.session_id)
    return await agent.handle(s, body.text, body.choice, body.language)


@router.get("/sessions/{session_id}/audit")
def audit(session_id: str):
    _session(session_id)
    return {"session_id": session_id, "events": db.audit_log(session_id)}


