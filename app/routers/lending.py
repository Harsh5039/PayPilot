"""Loan discovery, EMI, comparison, applications, documents and tracking."""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app import db
from app.config import settings
from app.seed import DOCUMENT_TYPES, PURPOSES, TENURES
from app.services import consent, eligibility, lending
from app.services.emi import quote_math, schedule

router = APIRouter(prefix="/api", tags=["loans"])


def _session(session_id: str) -> dict:
    s = db.get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail={"error": "session_not_found"})
    return s


def _app(app_id: str) -> dict:
    a = lending.get_application(app_id)
    if not a:
        raise HTTPException(status_code=404, detail={"error": "application_not_found",
                                                     "application_id": app_id})
    return a


def _require_state(app: dict, allowed: tuple[str, ...], next_step: str) -> None:
    if app["status"] not in allowed:
        raise HTTPException(status_code=409, detail={
            "error": "wrong_state", "status": app["status"], "expected": list(allowed),
            "hint": f"Complete {next_step} first.",
        })


# ---------------------------------------------------------------- discovery
@router.get("/lenders")
def lenders():
    return {"lenders": lending.catalogue(), "tenures": TENURES,
            "note": "Mock partner APIs. Rates and rules are illustrative."}


@router.get("/loan/purposes")
def purposes():
    return {"purposes": PURPOSES, "tenures": TENURES}


# ---------------------------------------------------------------- EMI
@router.get("/loans/emi")
def emi_calculator(
    principal: float = Query(..., gt=0, le=50000000, allow_inf_nan=False),
    annual_rate: float = Query(..., ge=0, le=60, allow_inf_nan=False),
    tenure_months: int = Query(..., gt=0, le=84),
    processing_fee_pct: float = Query(0, ge=0, le=10, allow_inf_nan=False),
):
    if tenure_months > 84:
        raise HTTPException(status_code=400, detail={"error": "tenure_too_long", "max": 84})
    math_ = quote_math(principal, annual_rate, tenure_months, processing_fee_pct)
    return {"principal": principal, "annual_rate": annual_rate,
            "tenure_months": tenure_months, "processing_fee_pct": processing_fee_pct,
            **math_, "schedule": schedule(principal, annual_rate, tenure_months)}


# ---------------------------------------------------------------- health + eligibility
@router.get("/sessions/{session_id}/financial-health")
def financial_health(session_id: str):
    """Income, spend, obligations, disposable income and the EMI that supports."""
    _session(session_id)
    consent.require_all(session_id, ["paytm.income", "bureau.softpull"])
    db.audit(session_id, "health.snapshot", "income + spend analysis", 30)
    return eligibility.health_snapshot()


class EligibilityIn(BaseModel):
    amount: float = Field(..., gt=0, le=50000000, allow_inf_nan=False)
    purpose: str = "personal"
    income_band: str = Field(default="30k_75k", pattern="^(under_30k|30k_75k|75k_plus)$")
    employment: str = Field(default="salaried", pattern="^(salaried|self_employed)$")
    emi_budget: float | None = Field(default=None, gt=0, le=5000000, allow_inf_nan=False)


@router.post("/sessions/{session_id}/loans/eligibility")
def pre_check(session_id: str, body: EligibilityIn):
    _session(session_id)
    consent.require_all(session_id, consent.REQUIRED_FOR_ELIGIBILITY)
    result = eligibility.assess(body.amount, body.purpose, body.income_band,
                                body.employment, body.emi_budget)
    db.audit(session_id, "eligibility.assess",
             f"amount={int(body.amount)} eligible={result['eligible']}", 88)
    return result


@router.get("/sessions/{session_id}/conflicts")
def conflicts(session_id: str, purpose: str = "personal",
              income_band: str = "30k_75k", employment: str = "salaried"):
    """Where what the customer said disagrees with what Paytm can see."""
    _session(session_id)
    consent.require(session_id, "paytm.income")
    found = eligibility.detect_conflicts({"purpose": purpose, "income_band": income_band,
                                          "employment": employment})
    return {"conflicts": found, "count": len(found)}


# ---------------------------------------------------------------- comparison
class CompareIn(BaseModel):
    amount: float = Field(..., gt=0, le=50000000, allow_inf_nan=False)
    employment: str = Field(default="salaried", pattern="^(salaried|self_employed)$")
    tenure_months: int | None = Field(default=None, gt=0, le=84)
    emi_budget: float | None = Field(default=None, gt=0, le=5000000, allow_inf_nan=False)


@router.post("/sessions/{session_id}/loans/compare")
def compare(session_id: str, body: CompareIn):
    _session(session_id)
    comp = lending.comparison(session_id, body.amount, body.employment,
                              body.tenure_months, body.emi_budget)
    if not comp["offers"]:
        raise HTTPException(status_code=422, detail={"error": "no_offers", "amount": body.amount,
                                                     "hint": "Below every partner's minimum, or no partner lends that tenure."})
    return comp


class CompareSelectedIn(BaseModel):
    offer_ids: list[str] = Field(..., min_length=2)
    amount: float = Field(..., gt=0, le=50000000, allow_inf_nan=False)
    employment: str = Field(default="salaried", pattern="^(salaried|self_employed)$")
    tenure_months: int | None = Field(default=None, gt=0, le=84)


@router.post("/sessions/{session_id}/loans/compare-selected")
def compare_selected(session_id: str, body: CompareSelectedIn):
    """Side-by-side for a hand-picked set, with the differences called out."""
    _session(session_id)
    return lending.compare_selected(session_id, body.offer_ids, body.amount,
                                    body.employment, body.tenure_months)


# ---------------------------------------------------------------- applications
class ApplyIn(BaseModel):
    offer_id: str | None = None
    lender_id: str | None = None
    amount: float | None = Field(default=None, gt=0, le=50000000, allow_inf_nan=False)
    tenure_months: int | None = None
    purpose: str = "personal"
    employment: str = "salaried"


@router.post("/sessions/{session_id}/applications", status_code=201)
def apply(session_id: str, body: ApplyIn):
    s = _session(session_id)
    consent.require_all(session_id, ["lender.share", "paytm.profile", "paytm.income", "paytm.kyc"])
    amount = body.amount or s["slots"].get("amount", 500000)
    offer = None
    if body.offer_id:
        offer = lending.get_offer(session_id, body.offer_id, amount, body.employment)
    if body.offer_id and not offer:
        raise HTTPException(status_code=422, detail="invalid_or_expired_offer")
    if not offer and body.lender_id:
        offer = next((o for o in lending.quotes(session_id, amount, body.employment)
                      if o["lender_id"] == body.lender_id), None)
    if not offer and not body.offer_id and not body.lender_id:
        selected = s["slots"].get("selected_offer") or {}
        if selected:
            offer = lending.get_offer(session_id, selected.get("offer_id", ""),
                                      selected.get("amount", amount), body.employment)
    if not offer:
        raise HTTPException(status_code=422, detail={"error": "no_offer_selected",
                                                     "hint": "Call /loans/compare first."})
    consent.require_recipient(session_id, "lender.share", offer["lender_name"])
    app = lending.create_application(session_id, offer, body.purpose, body.employment)
    return {"application": app, "prefill_fields": lending.prefill_fields()}


@router.get("/sessions/{session_id}/applications")
def list_applications(session_id: str, resumable: bool = False):
    _session(session_id)
    apps = lending.resumable(session_id) if resumable else lending.applications_for(session_id)
    return {"applications": apps}


@router.get("/applications/{app_id}")
def track(app_id: str):
    app = _app(app_id)
    return {"application": app,
            "notifications": db.notifications_for(app["session_id"], 10),
            "estimated_decision_hours": None}


@router.post("/applications/{app_id}/advance")
def advance(app_id: str):
    """Simulate the lender moving the file along one step."""
    _app(app_id)
    if not settings.demo_mode:
        raise HTTPException(status_code=404, detail="demo_simulator_disabled")
    return lending.advance(app_id)


# ---------------------------------------------------------------- documents
async def _store_upload(app: dict, doc_type: str, file: UploadFile) -> dict:
    from app.services.document_checks import MAX_BYTES
    consent.require(app["session_id"], "documents.access")
    if doc_type not in DOCUMENT_TYPES:
        raise HTTPException(400, detail={"error": "unknown_document_type", "allowed": sorted(DOCUMENT_TYPES)})
    content = await file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise HTTPException(413, detail="file_too_large_8mb")
    if not content:
        raise HTTPException(422, detail="empty_document")
    try:
        doc = lending.add_document(app["id"], doc_type, file.filename or doc_type, content)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return {"document": doc, "status": lending.document_status(app["id"])}


@router.post("/applications/{app_id}/documents/verify")
def verify_documents(app_id: str):
    app = _app(app_id)
    consent.require(app["session_id"], "documents.access")
    status = lending.mark_documents_verified(app_id)
    if status["complete"]:
        session = _session(app["session_id"])
        if session.get("slots", {}).get("application_id") == app_id:
            from app.services.agent import _advance_tracker
            tracker = _advance_tracker(session, 1, "Demo documents matched")
            db.save_session(app["session_id"], tracker=tracker)
    return {"status": status}


@router.post("/applications/{app_id}/documents/{doc_type}")
async def upload_document(app_id: str, doc_type: str, file: UploadFile = File(...)):
    app = _app(app_id)
    _require_state(app, ("created", "documents_verified", "documents_required"), "document submission")
    return await _store_upload(app, doc_type, file)


@router.post("/applications/{app_id}/documents")
async def upload_legacy(app_id: str, file: UploadFile = File(...), doc_type: str = "salary_slip"):
    app = _app(app_id)
    _require_state(app, ("created", "documents_verified", "documents_required"), "document submission")
    return await _store_upload(app, doc_type, file)


@router.get("/applications/{app_id}/documents")
def documents(app_id: str, employment: str = "salaried"):
    app = _app(app_id)
    consent.require(app["session_id"], "documents.access")
    return lending.document_status(app_id)


@router.post("/applications/{app_id}/kyc")
def kyc(app_id: str):
    a = _app(app_id)
    consent.require(a["session_id"], "paytm.kyc")
    if not settings.demo_mode:
        raise HTTPException(503, detail="paytm_kyc_provider_integration_required")
    from app.seed import PAYTM_KYC
    verified = PAYTM_KYC["status"] == "verified"
    if verified:
        db.run("UPDATE applications SET kyc_verified = 1 WHERE id = ?", (app_id,))
    db.audit(a["session_id"], "kyc.demo_match", app_id, 44)
    return {"application_id": app_id, "status": a["status"], "verified": verified,
            "simulated": True, "source": "mock_paytm_kyc"}


# ---------------------------------------------------------------- review + submit
@router.get("/applications/{app_id}/review")
def review(app_id: str, employment: str = "salaried"):
    """Exactly what the lender will receive, before anything is sent."""
    _app(app_id)
    return lending.review(app_id, employment)


@router.post("/applications/{app_id}/approve")
def approve(app_id: str, employment: str = "salaried"):
    """Explicit customer approval. Nothing leaves Paytm before this call."""
    app = _app(app_id)
    consent.require_all(app["session_id"], ["bureau.hardpull", "lender.share", "documents.access"])
    return lending.approve_and_submit(app_id)


@router.post("/applications/{app_id}/submit")
def submit(app_id: str, employment: str = "salaried"):
    """Alias for approve, kept so older clients keep working."""
    return approve(app_id, employment)


@router.get("/applications/{app_id}/summary")
def application_summary(app_id: str):
    _app(app_id)
    return lending.summary(app_id)


@router.get("/sessions/{session_id}/notifications")
def notifications(session_id: str):
    _session(session_id)
    return {"notifications": db.notifications_for(session_id)}


class NomineeUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


@router.patch("/applications/{app_id}/nominee")
def update_nominee(app_id: str, body: NomineeUpdate):
    app = _app(app_id)
    if app["status"] not in ("created", "documents_required", "documents_verified"):
        raise HTTPException(409, detail="Application can no longer be edited")
    name = body.name.strip()
    if not name or any(ord(c) < 32 for c in name):
        raise HTTPException(422, detail="Enter a valid nominee name")
    db.run("UPDATE applications SET nominee = ? WHERE id = ?", (name, app_id))
    db.audit(app["session_id"], "application.nominee_updated", app_id)
    return {"application": lending.get_application(app_id), "fields": lending.prefill_fields(name)}
