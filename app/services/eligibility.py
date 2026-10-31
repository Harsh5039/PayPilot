"""Eligibility pre-check and the financial health snapshot.

A rules engine, not a model: every number here has to be explainable to the
customer and reproducible in an audit. Nothing in this module is an approval —
that comes from the partner, later, and is labelled as such.
"""
from __future__ import annotations

from app.seed import BUREAU, INCOME_BANDS, LENDERS, PAYTM_EXPENSES, PAYTM_INCOME, PAYTM_TRANSACTIONS

MISMATCH_THRESHOLD = 0.40      # declared band vs verified salary credits
MISMATCH_PENALTY = 0.90        # capacity haircut when the two disagree
DISPOSABLE_SHARE = 0.60        # of disposable income we are willing to commit to an EMI

BAND_BY_ID = {b["id"]: b for b in INCOME_BANDS}


def health_snapshot() -> dict:
    """Income, spend, obligations, what is left, and what EMI that supports."""
    income = PAYTM_INCOME["monthly_net_salary"]
    obligations = PAYTM_INCOME["existing_monthly_obligations"]
    spend = PAYTM_EXPENSES["monthly_total"]
    disposable = income - obligations - spend
    affordable = max(min(disposable * DISPOSABLE_SHARE, income * 0.50 - obligations), 0)
    ratio = round(disposable / income, 3)

    if ratio >= 0.30 and BUREAU["score"] >= 750:
        grade, grade_label = "strong", "Strong"
    elif ratio >= 0.20:
        grade, grade_label = "fair", "Fair"
    else:
        grade, grade_label = "stretched", "Stretched"

    return {
        "monthly_income": income,
        "monthly_expenses": spend,
        "expense_breakdown": PAYTM_EXPENSES["categories"],
        "months_analysed": PAYTM_EXPENSES["months_analysed"],
        "existing_obligations": obligations,
        "obligation_breakdown": PAYTM_INCOME["obligations_breakdown"],
        "disposable_income": round(disposable),
        "disposable_ratio": ratio,
        "affordable_emi": round(affordable),
        "credit_score": BUREAU["score"],
        "credit_band": BUREAU["band"],
        "credit_provider": BUREAU["provider"],
        "credit_report_id": BUREAU["report_id"],
        "credit_simulated": True,
        "grade": grade,
        "grade_label": grade_label,
        "basis": "Six months of Paytm salary credits, EMIs and spend. Bureau score from a consented soft enquiry.",
    }


def assess(amount: float, purpose: str, income_band: str, employment: str,
           emi_budget: float | None = None) -> dict:
    """FOIR pre-check against every partner's published rules.

    The result is explicitly a *pre-eligibility* — an indicative view. It is not
    a sanction, and the response says so.
    """
    income = PAYTM_INCOME
    monthly_income = income["monthly_net_salary"]
    obligations = income["existing_monthly_obligations"]
    score = BUREAU["score"]
    health = health_snapshot()

    declared = BAND_BY_ID.get(income_band, BAND_BY_ID["30k_75k"])["midpoint"]
    mismatch = abs(declared - monthly_income) / monthly_income > MISMATCH_THRESHOLD
    capacity_factor = MISMATCH_PENALTY if mismatch else 1.0
    notes = []
    if mismatch:
        notes.append(
            f"You said {BAND_BY_ID[income_band]['label']}, but Paytm sees ₹{monthly_income:,} of salary "
            f"credits. The verified figure is used and capacity is reduced by 10%.")

    partners, reasons = [], []
    for lender in LENDERS:
        cap = lender["max_foir"] if employment == "salaried" else lender["max_foir"] - 0.05
        headroom = max(monthly_income * cap - obligations, 0)
        longest = max(lender["tenures"])
        r = lender["base_rate"] / 12 / 100
        max_by_income = (headroom * ((1 + r) ** longest - 1) / (r * (1 + r) ** longest)
                         if r else headroom * longest) * capacity_factor

        checks = {
            "bureau_score": score >= lender["min_score"],
            "monthly_income": monthly_income >= lender["min_monthly_income"],
            "amount_within_cap": lender["min_amount"] <= amount <= lender["max_amount"],
            "repayment_capacity": max_by_income >= amount,
        }
        failed = [k for k, ok in checks.items() if not ok]
        entry = {
            "lender_id": lender["id"],
            "lender_name": lender["name"],
            "eligible": not failed,
            "checks": checks,
            "failed_checks": failed,
            "max_amount_by_income": round(max_by_income / 1000) * 1000,
            "cap": min(lender["max_amount"], round(max_by_income / 1000) * 1000),
            "min_score": lender["min_score"],
            "foir_cap": cap,
            "explain": _explain(lender, checks, score, monthly_income, max_by_income),
        }
        partners.append(entry)
        if failed:
            reasons.extend(f"{lender['name']}: {f}" for f in failed)

    if employment == "self_employed":
        # The fixture has salary credits, not verified trading income.
        for partner in partners:
            partner["checks"]["business_income_verified"] = False
            partner["eligible"] = False
            partner["failed_checks"].append("business_income_verified")
        reasons.append("Self-employed income is not verified: provide business banking/ITR evidence.")
    eligible = [p for p in partners if p["eligible"]]
    approved_amount = amount if eligible else 0

    return {
        "stage": "pre_eligibility",
        "stage_label": "Indicative only — a lender has not seen this yet",
        "eligible": bool(eligible),
        "eligible_partner_count": len(eligible),
        "approved_amount": round(approved_amount),
        "requested_amount": amount,
        "purpose": purpose,
        "employment": employment,
        "income_band": income_band,
        "monthly_income": monthly_income,
        "declared_income_band": income_band,
        "declared_monthly_income": declared,
        "income_mismatch": mismatch,
        "capacity_factor": capacity_factor,
        "notes": notes,
        "existing_obligations": obligations,
        "affordable_emi": health["affordable_emi"],
        "emi_budget": emi_budget,
        "bureau_score": score,
        "bureau_band": BUREAU["band"],
        "bureau_simulated": True,
        "partners": partners,
        "reasons": reasons,
        "health": health,
        "basis": "FOIR rules per partner, consented soft bureau pull, Paytm income and spend.",
        "disclaimer": "Pre-eligibility only. The credit score is simulated and no lender has reviewed this.",
    }


def _explain(lender: dict, checks: dict, score: int, income: float, max_by_income: float) -> str:
    if all(checks.values()):
        return (f"Score {score} clears their floor of {lender['min_score']} and ₹{max_by_income:,.0f} "
                f"of repayment capacity covers this amount.")
    if not checks["bureau_score"]:
        return f"Your score of {score} is below their floor of {lender['min_score']}."
    if not checks["monthly_income"]:
        return f"They need a monthly income of at least ₹{lender['min_monthly_income']:,}."
    if not checks["amount_within_cap"]:
        return f"Their maximum ticket is ₹{lender['max_amount']:,}."
    return "Your existing obligations leave too little room for this EMI."


def detect_conflicts(slots: dict) -> list[dict]:
    """Where what the customer told us disagrees with what Paytm can see."""
    out = []
    band = slots.get("income_band")
    if band:
        declared = BAND_BY_ID.get(band, {}).get("midpoint", 0)
        verified = PAYTM_INCOME["monthly_net_salary"]
        if abs(declared - verified) / verified > MISMATCH_THRESHOLD:
            out.append({
                "id": "income_band",
                "field": "income_band",
                "label": "Monthly income",
                "yours": BAND_BY_ID[band]["label"],
                "paytm": f"₹{verified:,} net salary credited monthly",
                "question": "Which should the application use?",
                "options": [{"value": "use_paytm", "label": "Use the Paytm figure"},
                            {"value": "use_mine", "label": "Keep what I said"}],
            })

    if slots.get("purpose") == "business":
        business_credits = [t for t in PAYTM_TRANSACTIONS
                            if t["type"] == "credit" and "salary" not in t["merchant"].lower()]
        if not business_credits:
            out.append({
                "id": "purpose_business",
                "field": "purpose",
                "label": "Loan purpose",
                "yours": "Business",
                "paytm": "Only salary credits in the last six months",
                "question": "Business loans usually need trading receipts. Which is right?",
                "options": [{"value": "use_paytm", "label": "It's a personal loan actually"},
                            {"value": "use_mine", "label": "It is for my business"}],
            })
    return out
