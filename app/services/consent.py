"""Progressive consent management.

A scope is granted for one purpose, expires, and can be revoked. Every gated
read checks the ledger rather than trusting the client.
"""
from __future__ import annotations

from fastapi import HTTPException

from app import db
from app.seed import CONSENT_CATALOGUE

CATALOGUE = {c["scope"]: c for c in CONSENT_CATALOGUE}
REQUIRED_FOR_ELIGIBILITY = ["paytm.profile", "paytm.income", "paytm.kyc", "bureau.softpull"]


GROUPS = ["identity", "affordability", "credit", "sharing", "documents"]


def catalogue() -> list[dict]:
    return CONSENT_CATALOGUE


def by_group() -> dict:
    out: dict[str, list] = {g: [] for g in GROUPS}
    for item in CONSENT_CATALOGUE:
        out[item.get("group", "other")].append(item)
    return out


def grant(session_id: str, scopes: list[str], purpose: str | None = None,
          shared_with: str | None = None) -> list[dict]:
    unknown = [s for s in scopes if s not in CATALOGUE]
    if unknown:
        raise HTTPException(status_code=400, detail={"error": "unknown_scope", "scopes": unknown})
    out = []
    for scope in scopes:
        p = purpose or CATALOGUE[scope]["purpose"]
        entry = db.grant_consent(session_id, scope, p, shared_with)
        db.audit(session_id, "consent.grant", f"{scope} · {p}", 4)
        out.append(entry)
    return out


def revoke(session_id: str, scope: str) -> None:
    if not db.revoke_consent(session_id, scope):
        raise HTTPException(status_code=404, detail={"error": "scope_not_granted", "scope": scope})
    db.audit(session_id, "consent.revoke", scope, 3)


def require(session_id: str, scope: str) -> None:
    if scope not in db.active_scopes(session_id):
        db.audit(session_id, "consent.denied", scope, 1)
        raise HTTPException(status_code=403, detail={
            "error": "consent_required",
            "missing_scope": scope,
            "purpose": CATALOGUE.get(scope, {}).get("purpose", ""),
            "how_to_grant": f"POST /api/sessions/{session_id}/consent",
        })


def require_recipient(session_id: str, scope: str, lender_name: str) -> None:
    require(session_id, scope)
    ledger = db.consent_ledger(session_id)
    if not any(e["scope"] == scope and e["status"] == "granted" and
               e["shared_with"] == lender_name and scope in db.active_scopes(session_id)
               for e in ledger):
        raise HTTPException(403, detail={"error": "recipient_consent_required", "scope": scope,
                                         "shared_with": lender_name})


def require_all(session_id: str, scopes: list[str]) -> list[str]:
    live = db.active_scopes(session_id)
    missing = [s for s in scopes if s not in live]
    if missing:
        db.audit(session_id, "consent.denied", ",".join(missing), 1)
        raise HTTPException(status_code=403, detail={
            "error": "consent_required",
            "missing_scopes": missing,
            "purpose": [CATALOGUE[s]["purpose"] for s in missing],
            "how_to_grant": f"POST /api/sessions/{session_id}/consent",
        })
    return sorted(live)
