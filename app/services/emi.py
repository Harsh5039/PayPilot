"""EMI, APR and amortisation. One implementation, so the calculator, the
offers and the lender quotes can never disagree."""
from __future__ import annotations


def emi(principal: float, annual_rate: float, tenure_months: int) -> float:
    if tenure_months <= 0 or principal <= 0:
        raise ValueError("principal and tenure must be positive")
    r = annual_rate / 12 / 100
    if r == 0:
        return principal / tenure_months
    f = (1 + r) ** tenure_months
    return principal * r * f / (f - 1)


def schedule(principal: float, annual_rate: float, tenure_months: int) -> list[dict]:
    """Month-by-month amortisation, rounded to the paisa like a lender would."""
    monthly = emi(principal, annual_rate, tenure_months)
    r = annual_rate / 12 / 100
    balance = principal
    rows = []
    for m in range(1, tenure_months + 1):
        interest = round(balance * r, 2)
        principal_part = round(monthly - interest, 2)
        payment = round(monthly, 2)
        if m == tenure_months:
            principal_part = round(balance, 2)
            payment = round(principal_part + interest, 2)
        balance = round(balance - principal_part, 2)
        rows.append({"month": m, "emi": payment, "interest": interest,
                     "principal": principal_part, "balance": max(balance, 0.0)})
    return rows


def _npv(rate: float, principal: float, monthly: float, months: int) -> float:
    return -principal + sum(monthly / ((1 + rate) ** m) for m in range(1, months + 1))


def apr(principal: float, annual_rate: float, tenure_months: int,
        fee_pct: float = 0.0, other_charges: float = 0.0) -> float:
    """Effective annual cost of credit, fee included.

    The customer receives principal minus upfront charges and pays the EMI for
    the full tenure; the rate that makes those cash flows net to zero is the
    APR. Two offers with the same headline rate and different fees do not have
    the same APR, which is the point of showing it.
    """
    fee = principal * fee_pct / 100
    net = principal - fee - other_charges
    if net <= 0:
        return 0.0
    monthly = emi(principal, annual_rate, tenure_months)
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if _npv(mid, net, monthly, tenure_months) > 0:
            lo = mid
        else:
            hi = mid
    # Nominal annualisation (monthly IRR x 12) so it lines up with the quoted
    # rate: with no fee the APR equals the rate, and every rupee of fee adds to it.
    return round((lo + hi) / 2 * 12 * 100, 2)


def quote_math(principal: float, annual_rate: float, tenure_months: int, fee_pct: float,
               other_charges: float = 0.0) -> dict:
    """Everything a comparison needs: EMI, charges, all-in cost and the APR."""
    monthly = emi(principal, annual_rate, tenure_months)
    fee = round(principal * fee_pct / 100, 2)
    gst_on_fee = round(fee * 0.18, 2)
    total_repayment = round(monthly * tenure_months, 2)
    total_interest = round(total_repayment - principal, 2)
    charges = round(fee + gst_on_fee + other_charges, 2)
    return {
        "emi": round(monthly, 2),
        "processing_fee": fee,
        "gst_on_fee": gst_on_fee,
        "other_charges": round(other_charges, 2),
        "total_charges": charges,
        "total_interest": total_interest,
        "total_repayment": total_repayment,
        "total_payable": round(total_repayment + charges, 2),
        "apr": apr(principal, annual_rate, tenure_months, fee_pct, other_charges + gst_on_fee),
    }


def emi_table(principal: float, annual_rate: float, tenures: list[int]) -> dict:
    """The EMI at every tenure a lender offers, so comparison needs no clicks."""
    return {str(t): round(emi(principal, annual_rate, t)) for t in tenures}
