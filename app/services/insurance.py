"""Health insurance: plans, underwriting rules and policy issuance.

Same shape as lending.py — a mock partner layer behind a stable interface, so a
real insurer API replaces this module and nothing else.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from app import db
from app.services import consent

BASE_PLANS = [
    {
        "id": "star", "name": "Star Health", "product": "Family Health Optima",
        "base_premium_10l": 14880, "network": 14000, "ped_waiting_years": 4,
        "features": ["No room-rent cap", "20% no-claim bonus a year", "Restore once a year"],
        "tag": "widest network", "max_sum_insured": 2500000,
    },
    {
        "id": "hdfc", "name": "HDFC ERGO", "product": "Optima Secure",
        "base_premium_10l": 16100, "network": 13000, "ped_waiting_years": 3,
        "features": ["Cover doubles in year 2", "No room-rent cap", "Unlimited restore"],
        "tag": "best cover", "max_sum_insured": 5000000,
    },
    {
        "id": "niva", "name": "Niva Bupa", "product": "ReAssure 2.0",
        "base_premium_10l": 13450, "network": 10000, "ped_waiting_years": 3,
        "features": ["Unlimited restore", "Zero deduction on claims", "Lock the clock on PED"],
        "tag": "cheapest", "max_sum_insured": 2500000,
    },
]

MEMBERS_MULTIPLIER = {"self": 1.0, "couple": 1.72, "family": 2.58}
SUM_INSURED_FACTOR = {500000: 0.62, 1000000: 1.0, 2500000: 1.92, 5000000: 3.1}
MEMBERS_LABEL = {"self": "1 adult", "couple": "2 adults", "family": "2 adults + 2 children"}


def _jitter(session_id: str, plan_id: str) -> float:
    h = int(hashlib.sha256(f"{session_id}:{plan_id}".encode()).hexdigest()[:8], 16)
    return 1 + ((h % 90) - 45) / 1000.0      # ±4.5%


def plans(session_id: str, members: str = "self", sum_insured: int = 1000000,
          ped: str = "no") -> list[dict]:
    """GET /insurer/quote for every partner, normalised into one comparison set."""
    if sum_insured not in SUM_INSURED_FACTOR:
        raise ValueError("unsupported_sum_insured")
    mult = MEMBERS_MULTIPLIER.get(members, 1.0)
    factor = SUM_INSURED_FACTOR.get(sum_insured, 1.0)
    out = []
    for plan in BASE_PLANS:
        if sum_insured > plan["max_sum_insured"]:
            continue
        if ped == "yes" and plan["ped_waiting_years"] > 3:
            continue                          # filtered out: waiting period too long
        premium = plan["base_premium_10l"] * mult * factor * _jitter(session_id, plan["id"])
        if ped == "yes":
            premium *= 1.12                   # loading for a declared condition
        premium = int(round(premium / 10) * 10)
        out.append({
            "simulated": True,
            "plan_id": plan["id"],
            "insurer": plan["name"],
            "product": plan["product"],
            "label": f"{plan['name']} · {plan['product']}",
            "sum_insured": sum_insured,
            "members": members,
            "members_label": MEMBERS_LABEL.get(members, "1 adult"),
            "annual_premium": premium,
            "monthly_premium": int(round(premium / 12)),
            "network_hospitals": plan["network"],
            "ped_waiting_years": plan["ped_waiting_years"],
            "features": plan["features"],
            "tag": plan["tag"],
            "cashless": True,
        })
    out.sort(key=lambda p: p["annual_premium"])
    for i, p in enumerate(out):
        p["rank"] = i + 1
        p["recommended"] = i == 0
    return out


def _event(status: str, note: str) -> dict:
    return {"at": db.now(), "status": status, "note": note}


def create_policy(session_id: str, plan: dict, members: str, ped: str) -> dict:
    consent.require_all(session_id, ["paytm.profile", "paytm.kyc"])
    policy_id = db.new_id("pol")
    events = [_event("quote_locked", f"Premium held for 72 hours · {plan['insurer']}")]
    db.run(
        """INSERT INTO policies (id, session_id, plan_id, insurer, product, sum_insured, members,
           annual_premium, status, created_at, events) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (policy_id, session_id, plan["plan_id"], plan["insurer"], plan["product"],
         plan["sum_insured"], members, plan["annual_premium"], "quoted", db.now(), json.dumps(events)),
    )
    expires = (datetime.now(timezone.utc) + timedelta(hours=72)).isoformat(timespec="seconds")
    db.run("UPDATE policies SET ped = ?, quote_expires_at = ? WHERE id = ?", (ped, expires, policy_id))
    db.audit(session_id, "insurer.quote", f"{plan['insurer']} · {policy_id}", 118)
    return get_policy(policy_id)


def get_policy(policy_id: str) -> dict | None:
    row = db.one("SELECT * FROM policies WHERE id = ?", (policy_id,))
    if not row:
        return None
    d = dict(row)
    d["events"] = json.loads(d["events"])
    d["medical_declaration"] = json.loads(d.get("medical_declaration") or "[]")
    return d


def policies_for(session_id: str) -> list[dict]:
    rows = db.many("SELECT id FROM policies WHERE session_id = ? ORDER BY created_at DESC", (session_id,))
    return [get_policy(r["id"]) for r in rows]


def _set_status(policy_id: str, status: str, note: str) -> dict:
    p = get_policy(policy_id)
    db.run("UPDATE policies SET status = ?, events = ? WHERE id = ?",
           (status, json.dumps(p["events"] + [_event(status, note)]), policy_id))
    return get_policy(policy_id)


def declare(policy_id: str, conditions: list[str] | None = None) -> dict:
    p = get_policy(policy_id)
    consent.require_all(p["session_id"], ["paytm.profile", "paytm.kyc"])
    if p["status"] != "quoted":
        raise ValueError("wrong_policy_state")
    if p["quote_expires_at"] and datetime.fromisoformat(p["quote_expires_at"]) < datetime.now(timezone.utc):
        raise ValueError("quote_expired")
    conditions = conditions or []
    if not conditions or not all(isinstance(c, str) and 0 < len(c.strip()) <= 120 for c in conditions):
        raise ValueError("explicit_medical_declaration_required")
    if p["ped"] == "yes" and [c.strip().lower() for c in conditions] == ["none"]:
        raise ValueError("pre_existing_condition_details_required")
    db.run("UPDATE policies SET medical_declaration = ? WHERE id = ?", (json.dumps(conditions), policy_id))
    _set_status(policy_id, "proposal_complete",
                "Medical declaration accepted" + (f" · {', '.join(conditions)}" if conditions else ""))
    return get_policy(policy_id)


def pay_and_issue(policy_id: str) -> dict:
    from app.config import settings
    if not settings.demo_mode:
        raise ValueError("real_payment_and_insurer_confirmation_required")
    p = get_policy(policy_id)
    consent.require_all(p["session_id"], ["paytm.profile", "paytm.kyc"])
    if p["status"] != "proposal_complete":
        raise ValueError("wrong_policy_state")
    if p["quote_expires_at"] and datetime.fromisoformat(p["quote_expires_at"]) < datetime.now(timezone.utc):
        raise ValueError("quote_expired")
    db.audit(p["session_id"], "insurer.demo_payment", f"{policy_id} · {p['annual_premium']}", 132)
    _set_status(policy_id, "issued",
                "DEMO issuance only: no real payment, insurer policy or PDF")
    db.audit(p["session_id"], "insurer.issue", policy_id, 210)
    return get_policy(policy_id)
