"""Sarvam-105B integration.

The model does two jobs and only two:
  1. understand free text (slots + intent) in English or Hindi;
  2. answer off-script small talk in the customer's language.
It never prices a loan, checks eligibility, or approves anything — those are
deterministic services, so every number stays explainable and auditable.

With no SARVAM_API_KEY set, the deterministic rule parser in agent.py takes
over and the whole flow still works. That is deliberate: a demo that dies when
a key is missing is not a demo.
"""
from __future__ import annotations

import json
import logging

import httpx

from app.config import settings

log = logging.getLogger("paypilot.sarvam")

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": ["start_loan", "check_eligibility", "give_purpose", "give_amount",
                     "give_income", "give_employment", "compare", "apply", "track",
                     "greeting", "off_topic", "insurance"],
        },
        "amount": {"type": ["number", "null"], "description": "Loan amount in rupees, e.g. 500000"},
        "purpose": {"type": ["string", "null"], "enum": ["personal", "business", None]},
        "income_band": {"type": ["string", "null"], "enum": ["under_30k", "30k_75k", "75k_plus", None]},
        "employment": {"type": ["string", "null"], "enum": ["salaried", "self_employed", None]},
        "language": {"type": "string", "enum": ["en", "hi"]},
    },
    "required": ["intent", "language"],
}

SYSTEM_PROMPT = (
    "You are PayPilot, a financial co-pilot inside the Paytm app for Indian customers. "
    "You help with personal and business loans. You are warm, brief and concrete. "
    "You answer in the language the customer writes in: Hindi in Devanagari if they write Hindi, "
    "English if they write English, and you mirror Hinglish naturally. "
    "Never invent interest rates, fees, eligibility or approval outcomes — those come from the system. "
    "Never claim a loan is approved. You explain and guide; regulated partners decide."
)


def enabled() -> bool:
    return settings.llm_enabled


def status() -> dict:
    return {
        "provider": "sarvam",
        "model": settings.sarvam_model,
        "endpoint": f"{settings.sarvam_base_url}/chat/completions",
        "enabled": enabled(),
        "mode": "llm+nlu" if enabled() else "offline-rule-agent",
    }


def _headers() -> dict:
    return {"api-subscription-key": settings.sarvam_api_key, "Content-Type": "application/json"}


async def _post(payload: dict) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=settings.sarvam_timeout) as client:
            r = await client.post(f"{settings.sarvam_base_url}/chat/completions",
                                  headers=_headers(), json=payload)
        if r.status_code != 200:
            log.warning("sarvam %s: %s", r.status_code, r.text[:200])
            return None
        return r.json()
    except Exception as exc:  # network, timeout, DNS — all non-fatal by design
        log.warning("sarvam call failed: %s", exc)
        return None


async def extract(text: str, language: str, slots: dict) -> dict | None:
    """Structured understanding of one customer message."""
    if not enabled():
        return None
    payload = {
        "model": settings.sarvam_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT + " Return only the JSON object."},
            {"role": "user", "content":
                f"Conversation so far (known slots): {json.dumps(slots)}\n"
                f"Customer message: {text!r}\n"
                f"Extract the intent and any slots present. Amounts like '5 lakh' mean 500000."},
        ],
        "temperature": 0.1,
        "max_tokens": 300,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "nlu", "schema": EXTRACTION_SCHEMA, "strict": True}},
    }
    data = await _post(payload)
    if not data:
        return None
    try:
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception:
        log.warning("could not parse NLU output")
        return None


async def smalltalk(text: str, language: str, history: list[dict]) -> str | None:
    """Off-script reply, in the customer's language."""
    if not enabled():
        return None
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    msgs += [{"role": m["role"], "content": m["content"]} for m in history[-6:]]
    msgs.append({"role": "user", "content": text})
    data = await _post({"model": settings.sarvam_model, "messages": msgs,
                        "temperature": 0.3, "max_tokens": 220})
    if not data:
        return None
    try:
        return data["choices"][0]["message"]["content"].strip()
    except Exception:
        return None

# ---------------------------------------------------------------- tools
# Read-only by design. The model may look and compute; it may not create an
# application, grant consent, or move money. Those stay in the flow controller,
# behind an explicit user action.
TOOLS = [
    {"type": "function", "function": {
        "name": "get_paytm_profile",
        "description": "The customer's name, date of birth, address and masked PAN. Requires consent scope paytm.profile.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "get_income",
        "description": "Verified salary credits and existing monthly obligations. Requires scope paytm.income.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "check_eligibility",
        "description": "Run the eligibility pre-check for a loan amount. Returns which partners would accept and why.",
        "parameters": {"type": "object", "properties": {
            "amount": {"type": "number", "description": "Loan amount in rupees"},
            "employment": {"type": "string", "enum": ["salaried", "self_employed"]},
            "purpose": {"type": "string", "enum": ["personal", "business"]}},
            "required": ["amount"]}}},
    {"type": "function", "function": {
        "name": "get_offers",
        "description": "Partner loan offers for an amount, ranked by total amount payable including fees.",
        "parameters": {"type": "object", "properties": {
            "amount": {"type": "number"},
            "tenure_months": {"type": "integer", "description": "Optional: restrict to this tenure"},
            "employment": {"type": "string", "enum": ["salaried", "self_employed"]}},
            "required": ["amount"]}}},
    {"type": "function", "function": {
        "name": "calculate_emi",
        "description": "EMI, total interest and total payable for any principal, rate and tenure.",
        "parameters": {"type": "object", "properties": {
            "principal": {"type": "number"},
            "annual_rate": {"type": "number"},
            "tenure_months": {"type": "integer"},
            "processing_fee_pct": {"type": "number"}},
            "required": ["principal", "annual_rate", "tenure_months"]}}},
    {"type": "function", "function": {
        "name": "get_application_status",
        "description": "Current status and event timeline for an application id.",
        "parameters": {"type": "object", "properties": {
            "application_id": {"type": "string"}}, "required": ["application_id"]}}},
    {"type": "function", "function": {
        "name": "get_consent_ledger",
        "description": "What the customer has consented to, with purposes and expiry.",
        "parameters": {"type": "object", "properties": {}}}},
]

TOOL_SYSTEM_PROMPT = (
    SYSTEM_PROMPT + " You have tools that read consented Paytm data and compute loan numbers. "
    "Use them instead of guessing. If a tool reports consent_required, tell the customer which "
    "consent is missing and why it is needed — do not invent the data. Keep answers under 90 words."
)


async def _run_tool(name: str, args: dict, session_id: str) -> dict:
    """Execute one tool. Every read goes through the same consent gate as the REST API."""
    from fastapi import HTTPException

    from app import db
    from app.seed import PAYTM_INCOME, PAYTM_KYC, PAYTM_USER
    from app.services import consent, eligibility, lending
    from app.services.emi import quote_math

    try:
        if name == "get_paytm_profile":
            consent.require(session_id, "paytm.profile")
            return {"profile": PAYTM_USER}
        if name == "get_income":
            consent.require(session_id, "paytm.income")
            return {"income": PAYTM_INCOME}
        if name == "get_consent_ledger":
            return {"ledger": db.consent_ledger(session_id)}
        if name == "check_eligibility":
            consent.require_all(session_id, consent.REQUIRED_FOR_ELIGIBILITY)
            r = eligibility.assess(float(args.get("amount", 0)),
                                   args.get("purpose", "personal"),
                                   "75k_plus",
                                   args.get("employment", "salaried"))
            return {"eligible": r["eligible"], "approved_amount": r["approved_amount"],
                    "bureau_score": r["bureau_score"], "foir": max((p["foir_cap"] for p in r["partners"]), default=0),
                    "partners": [{k: p[k] for k in ("lender_name", "eligible", "cap", "failed_checks")}
                                 for p in r["partners"]], "reasons": r["reasons"][:4]}
        if name == "get_offers":
            offers = lending.quotes(session_id, float(args.get("amount", 0)),
                                    args.get("employment", "salaried"),
                                    args.get("tenure_months"))
            return {"offers": [{k: o[k] for k in ("lender_name", "emi", "annual_rate", "tenure_months",
                                                  "processing_fee", "total_payable", "rank")}
                               for o in offers[:4]]}
        if name == "calculate_emi":
            m = quote_math(float(args["principal"]), float(args["annual_rate"]),
                           int(args["tenure_months"]), float(args.get("processing_fee_pct", 0)))
            return m
        if name == "get_application_status":
            app = lending.get_application(args["application_id"])
            if not app:
                return {"error": "not_found"}
            return {"status": app["status"], "lender": app["lender_name"], "amount": app["amount"],
                    "events": [{"status": e["status"], "note": e["note"]} for e in app["events"]]}
        return {"error": "unknown_tool", "name": name}
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail)}
        return {"error": "consent_required", **detail}
    except Exception as exc:  # a bad argument must not kill the turn
        return {"error": "tool_failed", "detail": str(exc)[:120]}


async def run_tools(text: str, language: str, history: list[dict], session_id: str,
                    max_rounds: int = 4) -> str | None:
    """A real tool-calling loop. Returns the model's final answer, or None."""
    if not enabled():
        return None
    msgs = [{"role": "system", "content": TOOL_SYSTEM_PROMPT}]
    msgs += [{"role": m["role"], "content": m["content"]} for m in history[-6:]]
    msgs.append({"role": "user", "content": text})

    for _ in range(max_rounds):
        data = await _post({"model": settings.sarvam_model, "messages": msgs,
                            "tools": TOOLS, "tool_choice": "auto",
                            "temperature": 0.2, "max_tokens": 500})
        if not data:
            return None
        msg = data["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        if not calls:
            return (msg.get("content") or "").strip() or None

        msgs.append({"role": "assistant", "content": msg.get("content") or "",
                     "tool_calls": calls})
        for call in calls:
            fn = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except Exception:
                args = {}
            result = await _run_tool(fn, args, session_id)
            log.info("tool %s -> %s", fn, list(result)[:4])
            msgs.append({"role": "tool", "tool_call_id": call["id"],
                         "content": json.dumps(result)[:2000]})
    return None
