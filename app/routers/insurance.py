"""Health insurance: plan comparison, proposal and issuance."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app import db
from app.config import settings
from app.services.insurance import SUM_INSURED_FACTOR
from app.services import consent, insurance

router = APIRouter(prefix="/api", tags=["insurance"])


def _session(session_id: str) -> dict:
    s = db.get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail={"error": "session_not_found"})
    return s


def _policy(policy_id: str) -> dict:
    p = insurance.get_policy(policy_id)
    if not p:
        raise HTTPException(status_code=404, detail={"error": "policy_not_found", "policy_id": policy_id})
    return p


@router.get("/insurance/plans")
def plans(session_id: str = Query("demo"),
          members: str = Query("self", pattern="^(self|couple|family)$"),
          sum_insured: int = Query(1000000, gt=0),
          ped: str = Query("no", pattern="^(yes|no)$")):
    """Public comparison — no customer data, so no consent needed."""
    if sum_insured not in SUM_INSURED_FACTOR:
        raise HTTPException(422, detail="unsupported_sum_insured")
    return {"plans": insurance.plans(session_id, members, sum_insured, ped),
            "members": members, "sum_insured": sum_insured, "ped": ped}


class PolicyIn(BaseModel):
    plan_id: str
    members: str = Field(default="self", pattern="^(self|couple|family)$")
    sum_insured: int = Field(default=1000000, gt=0)
    ped: str = Field(default="no", pattern="^(yes|no)$")


@router.post("/sessions/{session_id}/insurance/policies", status_code=201)
def create(session_id: str, body: PolicyIn):
    _session(session_id)
    if body.sum_insured not in SUM_INSURED_FACTOR:
        raise HTTPException(422, detail="unsupported_sum_insured")
    consent.require_all(session_id, ["paytm.profile", "paytm.kyc"])
    plan = next((p for p in insurance.plans(session_id, body.members, body.sum_insured, body.ped)
                 if p["plan_id"] == body.plan_id), None)
    if not plan:
        raise HTTPException(status_code=422, detail={"error": "plan_not_available",
                                                     "hint": "Run GET /api/insurance/plans first."})
    return {"policy": insurance.create_policy(session_id, plan, body.members, body.ped), "plan": plan}


@router.get("/sessions/{session_id}/policies")
def list_policies(session_id: str):
    _session(session_id)
    return {"policies": insurance.policies_for(session_id)}


@router.get("/policies/{policy_id}")
def read_policy(policy_id: str):
    return {"policy": _policy(policy_id)}


@router.post("/policies/{policy_id}/declare")
def declare(policy_id: str, conditions: list[str] | None = None):
    p = _policy(policy_id)
    if p["status"] != "quoted":
        raise HTTPException(status_code=409, detail={"error": "wrong_state", "status": p["status"]})
    try:
        return {"policy": insurance.declare(policy_id, conditions)}
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc


@router.post("/policies/{policy_id}/pay")
def pay(policy_id: str):
    p = _policy(policy_id)
    if p["status"] != "proposal_complete":
        raise HTTPException(status_code=409, detail={"error": "wrong_state", "status": p["status"],
                                                     "hint": "Declare first."})
    if not settings.demo_mode:
        raise HTTPException(503, detail="real_payment_provider_not_configured")
    try:
        policy = insurance.pay_and_issue(policy_id)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return {"policy": policy, "simulated": True,
            "notice": "DEMO ONLY: no payment captured, no real insurance issued"}
