"""Progressive consent, and the mock Paytm data it unlocks.

Every data route checks the ledger. There is no path to customer data that
skips consent, including from the chat agent.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import db
from app.config import settings
from app.seed import PAYTM_ACCOUNTS, PAYTM_INCOME, PAYTM_KYC, PAYTM_TRANSACTIONS, PAYTM_USER
from app.services import consent

router = APIRouter(prefix="/api", tags=["consent", "paytm"])


class GrantIn(BaseModel):
    scopes: list[str]
    purpose: str | None = None
    shared_with: str | None = None


def _session(session_id: str) -> dict:
    s = db.get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail={"error": "session_not_found"})
    return s


@router.get("/consent/catalogue")
def catalogue():
    return {"scopes": consent.catalogue(), "groups": consent.by_group(),
            "ttl_days": settings.consent_ttl_days}


@router.get("/sessions/{session_id}/consent")
def read_consent(session_id: str):
    _session(session_id)
    ledger = db.consent_ledger(session_id)
    history = [{"scope": e["scope"], "status": e["status"], "at": e["granted_at"],
                "revoked_at": e["revoked_at"], "purpose": e["purpose"]} for e in ledger]
    return {
        "session_id": session_id,
        "active": sorted(db.active_scopes(session_id)),
        "ledger": ledger,
        "history": history,
        "groups": consent.by_group(),
    }


@router.post("/sessions/{session_id}/consent", status_code=201)
def grant(session_id: str, body: GrantIn):
    _session(session_id)
    entries = consent.grant(session_id, body.scopes, body.purpose, body.shared_with)
    return {"session_id": session_id, "granted": entries, "active": sorted(db.active_scopes(session_id))}


@router.delete("/sessions/{session_id}/consent/{scope}")
def revoke(session_id: str, scope: str):
    _session(session_id)
    consent.revoke(session_id, scope)
    return {"session_id": session_id, "revoked": scope, "active": sorted(db.active_scopes(session_id))}


# ---------------------------------------------------------------- gated data
GATES = {
    "profile": ("paytm.profile", lambda: PAYTM_USER),
    "income": ("paytm.income", lambda: PAYTM_INCOME),
    "kyc": ("paytm.kyc", lambda: PAYTM_KYC),
    "accounts": ("paytm.profile", lambda: PAYTM_ACCOUNTS),
    "transactions": ("paytm.transactions", lambda: PAYTM_TRANSACTIONS),
}


@router.get("/sessions/{session_id}/paytm/{resource}")
def paytm_data(session_id: str, resource: str):
    _session(session_id)
    if resource not in GATES:
        raise HTTPException(status_code=404, detail={"error": "unknown_resource", "resource": resource,
                                                     "available": sorted(GATES)})
    scope, loader = GATES[resource]
    consent.require(session_id, scope)
    db.audit(session_id, "paytm.read", f"{resource} · scope={scope}", 12)
    return {"resource": resource, "scope": scope, "data": loader()}
