"""Mock lender APIs, the application lifecycle and the document layer.

Each function stands in for one partner endpoint (quote, submit, decision). The
shapes are what a real adapter would return, so swapping in a live partner means
replacing this module and nothing else.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from fastapi import HTTPException

from app import db
from app.seed import (BUREAU, DOCUMENT_TYPES, LENDERS, PAYTM_INCOME, PAYTM_KYC,
                      PAYTM_USER, TENURES)
from app.services.emi import emi, emi_table, quote_math, schedule

LENDER_BY_ID = {l["id"]: l for l in LENDERS}
DEFAULT_TENURE = 24      # every partner offers it, so the first comparison is like for like
STAMP_DUTY_PCT = 0.001   # illustrative


def catalogue() -> list[dict]:
    return [{k: l[k] for k in ("id", "name", "min_score", "min_amount", "max_amount",
                               "base_rate", "processing_fee_pct", "tenures", "tag",
                               "prepayment")} for l in LENDERS]


def all_tenures() -> list[int]:
    return TENURES


def _jitter(session_id: str, lender_id: str) -> float:
    """Deterministic ±0.20% so a demo replays identically but two lenders differ."""
    h = int(hashlib.sha256(f"{session_id}:{lender_id}".encode()).hexdigest()[:8], 16)
    return round(((h % 400) - 200) / 1000.0, 3)


def _tenure_for(lender: dict, tenure: int | None) -> int | None:
    if tenure:
        return tenure if tenure in lender["tenures"] else None
    if DEFAULT_TENURE in lender["tenures"]:
        return DEFAULT_TENURE
    return max(lender["tenures"])


def _why(offer: dict, highlights: dict, budget: float | None) -> str:
    bits = []
    if highlights.get("lowest_total", {}).get("lender_id") == offer["lender_id"]:
        bits.append("lowest total repayment here")
    if highlights.get("lowest_rate", {}).get("lender_id") == offer["lender_id"]:
        bits.append("lowest interest rate")
    if offer["processing_fee"] == 0:
        bits.append("no processing fee")
    if offer["prepayment_score"] >= 3:
        bits.append("free foreclosure")
    if offer["tenure_months"] == 60:
        bits.append("longest tenure, smallest EMI")
    if budget and offer["emi"] <= budget:
        bits.append(f"fits your ₹{int(budget):,} budget")
    elif budget:
        bits.append(f"₹{int(offer['emi'] - budget):,} above your budget")
    if not bits:
        bits.append(f"{offer['annual_rate']:.2f}% with a {offer['processing_fee_pct']}% fee")
    return "Why: " + ", ".join(bits) + "."


def comparison(session_id: str, amount: float, employment: str = "salaried",
               tenure: int | None = None, emi_budget: float | None = None) -> dict:
    """Every partner quoted on the same amount and, where possible, the same tenure."""
    from app.services.eligibility import health_snapshot
    affordable = health_snapshot()["affordable_emi"]
    emi_budget = min(affordable, emi_budget) if emi_budget is not None else affordable
    raw = []
    for lender in LENDERS:
        if not (lender["min_amount"] <= amount <= lender["max_amount"]):
            continue
        t = _tenure_for(lender, tenure)
        if t is None:
            continue
        rate = round(lender["base_rate"] + _jitter(session_id, lender["id"]), 2)
        principal = amount
        other = round(principal * STAMP_DUTY_PCT, 2)
        math_ = quote_math(principal, rate, t, lender["processing_fee_pct"], other)
        raw.append({
            "simulated": True,
            "offer_id": f"{lender['id']}-{t}-{int(principal)}",
            "lender_id": lender["id"],
            "lender_name": lender["name"],
            "amount": round(principal),
            "tenure_months": t,
            "tenures": lender["tenures"],
            "annual_rate": rate,
            "processing_fee_pct": lender["processing_fee_pct"],
            "prepayment": lender["prepayment"],
            "prepayment_score": lender["prepayment_score"],
            "tag": lender["tag"],
            "decision_sla_hours": lender["decision_sla_hours"],
            "emi_by_tenure": emi_table(principal, rate, lender["tenures"]),
            **math_,
        })
    if not raw:
        return {"offers": [], "highlights": {}, "tenures": TENURES, "amount": amount,
                "note": "No partner lends this amount or tenure."}

    cheapest_total = min(raw, key=lambda o: o["total_payable"])
    cheapest_rate = min(raw, key=lambda o: o["annual_rate"])
    flex = max(raw, key=lambda o: o["prepayment_score"])
    highlights = {
        "lowest_total": {"lender_id": cheapest_total["lender_id"],
                         "lender_name": cheapest_total["lender_name"],
                         "value": cheapest_total["total_payable"]},
        "lowest_rate": {"lender_id": cheapest_rate["lender_id"],
                        "lender_name": cheapest_rate["lender_name"],
                        "value": cheapest_rate["annual_rate"]},
        "zero_fee": [o["lender_name"] for o in raw if o["processing_fee"] == 0],
        "flexible_prepayment": {"lender_id": flex["lender_id"],
                                "lender_name": flex["lender_name"],
                                "value": flex["prepayment"]},
    }

    for o in raw:
        o["within_budget"] = o["emi"] <= emi_budget
        o["why"] = _why(o, highlights, emi_budget)

    raw.sort(key=lambda o: ((0 if o["within_budget"] is not False else 1), o["total_payable"]))
    for i, o in enumerate(raw):
        o["rank"] = i + 1
        o["recommended"] = i == 0 and o["within_budget"]

    worst = max(raw, key=lambda o: o["total_payable"])
    over_budget = [o for o in raw if o["within_budget"] is False]
    budget_note = None
    if len(over_budget) == len(raw):
        budget_note = (f"Every offer's EMI is above your ₹{int(emi_budget):,} budget. "
                       f"The honest options are a smaller amount or a longer tenure.")
    return {
        "simulated": True,
        "offers": raw,
        "highlights": highlights,
        "budget_note": budget_note,
        "tenures": TENURES,
        "amount": amount,
        "tenure": tenure,
        "emi_budget": emi_budget,
        "recommended_offer_id": raw[0]["offer_id"] if raw[0]["recommended"] else None,
        "savings_vs_worst": round(worst["total_payable"] - raw[0]["total_payable"], 2),
        "ranking": "total amount payable including fees and GST for the same requested principal, budget first",
        "disclaimer": "Simulated partner quotes. Rates, fees and eligibility rules are illustrative.",
    }


def quotes(session_id: str, amount: float, employment: str = "salaried",
           tenure_months: int | None = None, emi_budget: float | None = None) -> list[dict]:
    """Backwards-compatible shorthand used by the agent and the tool layer."""
    return comparison(session_id, amount, employment, tenure_months, emi_budget)["offers"]


def get_offer(session_id: str, offer_id: str, amount: float,
              employment: str = "salaried", emi_budget: float | None = None) -> dict | None:
    # Resolve the tenure embedded in the offer ID, never substitute another offer.
    parts = offer_id.rsplit("-", 2)
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        return None
    quoted_tenure = int(parts[1])
    for o in quotes(session_id, amount, employment, quoted_tenure, emi_budget):
        if o["offer_id"] == offer_id:
            return o
    return None


def compare_selected(session_id: str, offer_ids: list[str], amount: float,
                     employment: str = "salaried", tenure: int | None = None) -> dict:
    """Side-by-side for a hand-picked set, with the differences called out.

    Offer ids encode their tenure, so if the caller does not say which tenure the
    offers came from we resolve them by trying the requested tenure, the default,
    then each supported tenure in turn.
    """
    # Resolve each offer by its embedded tenor; don't silently lose cross-tenor choices.
    offers: list[dict] = []
    for offer_id in dict.fromkeys(offer_ids):
        found = get_offer(session_id, offer_id, amount, employment)
        if found:
            offers.append(found)

    if len(offers) < 2:
        return {"offers": offers, "note": "Pick at least two offers to compare."}
    best_total = min(offers, key=lambda o: o["total_payable"])
    best_rate = min(offers, key=lambda o: o["annual_rate"])
    rows = []
    for field, label, fmt in [
        ("annual_rate", "Interest rate", "{:.2f}%"),
        ("apr", "APR", "{:.2f}%"),
        ("emi", "EMI", "₹{:,.0f}"),
        ("processing_fee", "Processing fee", "₹{:,.0f}"),
        ("total_charges", "All charges", "₹{:,.0f}"),
        ("total_interest", "Total interest", "₹{:,.0f}"),
        ("total_payable", "Total repayment", "₹{:,.0f}"),
        ("tenure_months", "Tenure", "{} months"),
    ]:
        rows.append({"field": field, "label": label,
                     "values": [fmt.format(o[field]) for o in offers],
                     "best_index": min(range(len(offers)), key=lambda i: offers[i][field])
                     if field not in ("tenure_months",) else None})
    return {"offers": offers, "rows": rows,
            "cheapest_total": best_total["lender_name"],
            "cheapest_rate": best_rate["lender_name"]}


# ---------------------------------------------------------------- application
def _ref() -> str:
    # A random ID prevents reference collisions after deletions and concurrent requests.
    return f"PP-{datetime.now(timezone.utc).year}-{db.new_id('ref')[4:14].upper()}"


def _event(status: str, note: str) -> dict:
    return {"at": db.now(), "status": status, "note": note}


def create_application(session_id: str, offer: dict, purpose: str,
                       employment: str = "salaried") -> dict:
    from app.services import consent
    consent.require_recipient(session_id, "lender.share", offer["lender_name"])
    canonical = get_offer(session_id, str(offer.get("offer_id", "")), offer["amount"], employment)
    if canonical is None:
        raise HTTPException(422, detail="offer_terms_unavailable_or_expired")
    offer = canonical
    app_id = db.new_id("app")
    ref = _ref()
    events = [_event("created", f"Application created for {offer['lender_name']}")]
    db.run(
        """INSERT INTO applications (id, reference, session_id, lender_id, lender_name, amount,
           tenure_months, apr, emi, processing_fee, total_payable, status, created_at, events)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (app_id, ref, session_id, offer["lender_id"], offer["lender_name"], offer["amount"],
         offer["tenure_months"], offer["annual_rate"], offer["emi"], offer["processing_fee"],
         offer["total_payable"], "created", db.now(), json.dumps(events)),
    )
    db.run("UPDATE applications SET employment = ?, purpose = ?, offer_id = ? WHERE id = ?",
           (employment, purpose, offer["offer_id"], app_id))
    db.audit(session_id, "lender.submit", f"{offer['lender_name']} · {ref}", 118)
    db.notify(session_id, "Application started",
              f"{ref} opened with {offer['lender_name']} for ₹{offer['amount']:,.0f}.",
              app_id, "created")
    return get_application(app_id)


def get_application(app_id: str) -> dict | None:
    row = db.one("SELECT * FROM applications WHERE id = ?", (app_id,))
    if not row:
        return None
    d = dict(row)
    d["events"] = json.loads(d["events"])
    d["reference"] = d.get("reference") or d["id"]
    return d


def applications_for(session_id: str) -> list[dict]:
    rows = db.many("SELECT id FROM applications WHERE session_id = ? ORDER BY created_at DESC",
                   (session_id,))
    return [get_application(r["id"]) for r in rows]


def resumable(session_id: str) -> list[dict]:
    done = ("approved", "rejected")
    return [a for a in applications_for(session_id) if a["status"] not in done]


def _set_status(app_id: str, status: str, note: str) -> dict:
    app = get_application(app_id)
    events = app["events"] + [_event(status, note)]
    db.run("UPDATE applications SET status = ?, events = ? WHERE id = ?",
           (status, json.dumps(events), app_id))
    return get_application(app_id)


# ---------------------------------------------------------------- documents
def required_documents(employment: str = "salaried", lender_id: str | None = None) -> list[str]:
    """Demo lender policy: Tata accepts a bank statement instead of both.

    In production policies must be supplied by the actual lender and versioned.
    """
    if employment == "self_employed":
        return ["pan", "bank_statement"]
    return ["bank_statement"] if lender_id == "tata" else ["salary_slip", "bank_statement"]


def _employment(app: dict) -> str:
    return app.get("employment") or "salaried"


def add_document(app_id: str, doc_type: str, filename: str, content: bytes) -> dict:
    if doc_type not in DOCUMENT_TYPES:
        raise KeyError(doc_type)
    from app.services.document_checks import analyse
    result = analyse(doc_type, content, filename)
    doc = db.add_document(app_id, doc_type, filename, result["confidence"],
                          result["extracted"], result["sha256"],
                          result["verification_status"], result["failure_reasons"])
    app = get_application(app_id)
    db.audit(app["session_id"], "document.check",
             f"{doc_type} · {result['verification_status']} · sha256={result['sha256'][:12]}", 35)
    db.notify(app["session_id"], "Document analysed",
              f"{DOCUMENT_TYPES[doc_type]['label']}: {result['verification_status']}", app_id, "documents")
    return {**doc, "simulated": True,
            "note": "Content and demo Paytm fields checked. NOT issuer-authenticated."}


def document_status(app_id: str, employment: str | None = None) -> dict:
    app = get_application(app_id)
    docs = db.documents_for(app_id)
    # Never trust an employment query parameter over the stored applicant category.
    need = required_documents(_employment(app), app["lender_id"])
    passed = {d["doc_type"] for d in docs if d["verified"] and d["verification_status"] == "matched_demo"}
    missing = [t for t in need if t not in passed]
    return {
        "required": [{"doc_type": t, "label": DOCUMENT_TYPES[t]["label"],
                      "purpose": DOCUMENT_TYPES[t]["purpose"]} for t in need],
        "uploaded": docs,
        "missing": [{"doc_type": t, "label": DOCUMENT_TYPES[t]["label"],
                     "purpose": DOCUMENT_TYPES[t]["purpose"]} for t in missing],
        "complete": not missing,
        "verification_basis": "Local PDF field matching with mock Paytm data, not a real fraud/authenticity check",
    }


def mark_documents_verified(app_id: str, employment: str | None = None) -> dict:
    app = get_application(app_id)
    if app["status"] not in ("created", "documents_required", "documents_verified"):
        raise HTTPException(409, detail="cannot_verify_documents_in_this_state")
    st = document_status(app_id)
    if not st["complete"]:
        return st
    from app.config import settings
    if not settings.demo_mode:
        raise HTTPException(503, detail="independent_document_verification_not_configured")
    _set_status(app_id, "documents_verified", "Documents matched against mock Paytm records (DEMO)")
    return document_status(app_id)


def prefill_fields(nominee: str | None = None) -> list[dict]:
    """What the application form looks like when Paytm data fills it in."""
    return [
        {"label": "Full name", "value": PAYTM_USER["name"], "source": "Paytm KYC"},
        {"label": "PAN", "value": PAYTM_USER["pan_masked"], "source": "Paytm KYC"},
        {"label": "Date of birth", "value": PAYTM_USER["date_of_birth"], "source": "Paytm KYC"},
        {"label": "Address", "value": PAYTM_USER["address"], "source": "Paytm"},
        {"label": "Employer", "value": PAYTM_USER["employer"], "source": "Paytm"},
        {"label": "Monthly income", "value": f"₹{PAYTM_INCOME['monthly_net_salary']:,}", "source": "Paytm"},
        {"label": "Bank account", "value": "Paytm Payments Bank ••4471", "source": "Paytm"},
        {"label": "Nominee", "value": nominee or "Not on file", "source": "You" if nominee else "needs you"},
    ]


def review(app_id: str, employment: str = "salaried") -> dict:
    """Exactly what the lender will receive, before anything is sent."""
    app = get_application(app_id)
    docs = db.documents_for(app_id)
    return {
        "application": app,
        "reference": app["reference"],
        "lender": app["lender_name"],
        "fields": prefill_fields(app.get("nominee")),
        "documents": [{"doc_type": d["doc_type"], "label": DOCUMENT_TYPES[d["doc_type"]]["label"],
                       "filename": d["filename"], "confidence": d["confidence"]} for d in docs],
        "missing_documents": document_status(app_id, employment)["missing"],
        "shared_with": app["lender_name"],
        "consents": ["lender.share", "bureau.hardpull", "documents.access"],
        "terms": {"amount": app["amount"], "tenure_months": app["tenure_months"],
                  "annual_rate": app["apr"], "emi": app["emi"],
                  "processing_fee": app["processing_fee"], "total_payable": app["total_payable"]},
        "stage": "awaiting_your_approval",
    }


def approve_and_submit(app_id: str, employment: str | None = None) -> dict:
    from app.config import settings
    from app.services import consent
    app = get_application(app_id)
    if app["status"] in ("submitted", "under_review", "approved", "rejected"):
        raise HTTPException(409, detail="application_already_submitted_or_final")
    if not settings.demo_mode:
        raise HTTPException(503, detail="real_lender_and_document_kyc_verification_not_configured")
    consent.require_all(app["session_id"], ["lender.share", "documents.access", "bureau.hardpull",
                                                "paytm.profile", "paytm.income", "paytm.kyc", "bureau.softpull"])
    consent.require_recipient(app["session_id"], "lender.share", app["lender_name"])
    st = document_status(app_id)
    if not st["complete"]:
        _set_status(app_id, "documents_required",
                    "Missing or unverified: " + ", ".join(m["label"] for m in st["missing"]))
        db.notify(app["session_id"], "Documents needed",
                  "Validate " + ", ".join(m["label"] for m in st["missing"]) + " to continue.",
                  app_id, "documents_required")
        return {"decision": "documents_required", "missing": st["missing"],
                "simulated": True, "application": get_application(app_id)}
    if app["status"] != "documents_verified":
        raise HTTPException(409, detail="verify_documents_before_submission")
    if not app.get("kyc_verified"):
        raise HTTPException(409, detail="kyc_verification_required")
    from app.services.eligibility import assess
    session = db.get_session(app["session_id"])
    band = (session["slots"].get("income_band") or "75k_plus") if session else "75k_plus"
    elig = assess(app["amount"], app.get("purpose") or "personal", band,
                  app.get("employment") or "salaried")
    if not any(x["eligible"] and x["lender_id"] == app["lender_id"] for x in elig["partners"]):
        raise HTTPException(422, detail="requested_terms_not_pre_eligible_for_lender")
    _set_status(app_id, "submitted", f"Submitted to MOCK {app['lender_name']} after explicit approval")
    db.notify(app["session_id"], "Application submitted",
              f"{app['reference']} submitted to the demo lender simulator.", app_id, "submitted")
    db.audit(app["session_id"], "lender.submit", f"{app_id} · explicit approval", 60)
    return {"decision": "submitted", "simulated": True, "application": get_application(app_id),
            "estimated_decision_hours": LENDER_BY_ID[app["lender_id"]]["decision_sla_hours"],
            "note": "Mock lender only. No real application, sanction or money transfer."}


def advance(app_id: str) -> dict:
    """Simulates the lender moving the file along. Each call moves one step."""
    app = get_application(app_id)
    lender = LENDER_BY_ID[app["lender_id"]]
    status = app["status"]

    if status == "submitted":
        _set_status(app_id, "under_review", f"{lender['name']} has picked up the file")
        db.notify(app["session_id"], "Under review",
                  f"{lender['name']} is reviewing {app['reference']}.", app_id, "under_review")
        return {"application": get_application(app_id), "decision": "under_review",
                "simulated": True, "decided_by": "mock partner"}

    if status == "under_review":
        score = BUREAU["score"]
        if score < lender["min_score"]:
            decision, note = "rejected", f"Score {score} is below their floor of {lender['min_score']}"
        elif app["amount"] > lender["max_amount"] * 0.9:
            decision, note = "rejected", "Amount above 90% of the partner's cap"
        else:
            decision, note = "approved", f"Sanctioned by {lender['name']} at {app['apr']}% p.a."
        _set_status(app_id, decision, note)
        db.run("UPDATE applications SET decision_at = ? WHERE id = ?", (db.now(), app_id))
        db.notify(app["session_id"], decision.title(), note, app_id, decision)
        db.audit(app["session_id"], "lender.decision", f"{app_id} · {decision}", 240)
        return {"application": get_application(app_id), "decision": decision, "reason": note,
                "decided_by": "partner", "decision_source": "mock partner (simulated)",
                "simulated": True, "lender": lender["name"],
                "disbursal_eta_hours": lender["decision_sla_hours"],
                "note": "Simulated decision. No sanction letter exists and no money moves."}

    return {"application": app, "decision": status, "note": "Nothing further to do."}


def summary(app_id: str) -> dict:
    """One page: terms, cost, amortisation, documents and the timeline."""
    app = get_application(app_id)
    lender = LENDER_BY_ID[app["lender_id"]]
    rows = schedule(app["amount"], app["apr"], app["tenure_months"])
    fee = app["processing_fee"]
    return {
        "application_id": app["id"],
        "reference": app["reference"],
        "status": app["status"],
        "lender": app["lender_name"],
        "lender_decision_sla_hours": lender["decision_sla_hours"],
        "principal": app["amount"],
        "annual_rate": app["apr"],
        "tenure_months": app["tenure_months"],
        "emi": app["emi"],
        "processing_fee": fee,
        "gst_on_fee": round(fee * 0.18, 2),
        "total_payable": app["total_payable"],
        "total_interest": round(app["emi"] * app["tenure_months"] - app["amount"], 2),
        "schedule": rows,
        "documents": [{"label": DOCUMENT_TYPES[d["doc_type"]]["label"], "filename": d["filename"],
                       "confidence": d["confidence"]} for d in db.documents_for(app_id)],
        "events": app["events"],
        "generated_at": db.now(),
        "simulated": True,
        "disclaimer": "Simulated lender, simulated decision. For demonstration only.",
    }
