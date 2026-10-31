"""Mock Paytm data, the lender catalogue and the document requirements.

Nothing here calls a real system. The shapes mirror what a Paytm-internal
service would return, so the adapter layer can be swapped for the real one
without touching the agent.
"""
from __future__ import annotations

PAYTM_USER = {
    "user_id": "ptm_88214471",
    "name": "Arjun Mehta",
    "date_of_birth": "1998-08-14",
    "pan_masked": "XXXXX42F",
    "address": "Indiranagar, Bengaluru, Karnataka 560038",
    "employer": "Razorpay Software Pvt Ltd",
    "email": "arjun.mehta@example.com",
    "phone_masked": "+91 98XXX XX891",
}

PAYTM_KYC = {
    "status": "verified",
    "method": "Aadhaar OTP e-KYC",
    "ckyc_id": "CKYC-4491220",
    "verified_at": "2024-11-02",
    "pan_verified": True,
    "aadhaar_masked": "XXXX XXXX 8891",
}

PAYTM_ACCOUNTS = [
    {"id": "ppb_4471", "type": "savings", "bank": "Paytm Payments Bank",
     "masked": "XXXX4471", "primary": True, "balance": 184320.55},
    {"id": "hdfc_9930", "type": "savings", "bank": "HDFC Bank",
     "masked": "XXXX9930", "primary": False, "balance": 96410.10},
]

PAYTM_INCOME = {
    "monthly_net_salary": 84200,
    "monthly_credits_avg_6m": 82650,
    "salary_credits_6m": 6,
    "income_band": "75k_plus",
    "existing_monthly_obligations": 12400,
    "obligations_breakdown": [
        {"label": "Two-wheeler loan EMI", "lender": "Hero Fincorp", "monthly": 8400, "type": "emi"},
        {"label": "Credit card minimum due", "lender": "HDFC Bank", "monthly": 4000, "type": "card"},
    ],
}

# Monthly spend analysis, used for the financial health snapshot.
PAYTM_EXPENSES = {
    "monthly_total": 38650,
    "categories": [
        {"label": "Rent", "monthly": 22000},
        {"label": "Utilities and bills", "monthly": 4250},
        {"label": "Groceries and food", "monthly": 7400},
        {"label": "Transport", "monthly": 3100},
        {"label": "Subscriptions", "monthly": 900},
        {"label": "Other", "monthly": 1000},
    ],
    "months_analysed": 6,
}

PAYTM_TRANSACTIONS = [
    {"date": "2026-10-28", "merchant": "Salary credit", "amount": 84200, "type": "credit"},
    {"date": "2026-10-27", "merchant": "Swiggy", "amount": -640, "type": "debit"},
    {"date": "2026-10-26", "merchant": "UPI · Kirana", "amount": -2180, "type": "debit"},
    {"date": "2026-10-25", "merchant": "Electricity board", "amount": -1420, "type": "debit"},
    {"date": "2026-10-24", "merchant": "Salary credit", "amount": 84200, "type": "credit"},
]

BUREAU = {
    "score": 762,
    "band": "good",
    "enquiries_90d": 1,
    "active_loans": 1,
    "dpd_last_12m": 0,
    "report_id": "CIBIL-MOCK-88231",
    "provider": "TransUnion CIBIL",
}

PURPOSES = [
    {"id": "personal", "label": "Personal use", "hint": "Anything not covered below"},
    {"id": "education", "label": "Education", "hint": "Tuition, course fees, living costs"},
    {"id": "medical", "label": "Medical", "hint": "Treatment, hospital, procedures"},
    {"id": "travel", "label": "Travel", "hint": "Tickets, visa, holiday"},
    {"id": "wedding", "label": "Wedding", "hint": "Function, venue, catering"},
    {"id": "business", "label": "Business", "hint": "Working capital, stock, equipment"},
    {"id": "home_renovation", "label": "Home renovation", "hint": "Repairs, interiors"},
    {"id": "debt_consolidation", "label": "Debt consolidation", "hint": "Pay off costlier debt"},
]

INCOME_BANDS = [
    {"id": "under_30k", "label": "Under ₹30,000", "midpoint": 25000},
    {"id": "30k_75k", "label": "₹30,000 to ₹75,000", "midpoint": 52000},
    {"id": "75k_plus", "label": "Above ₹75,000", "midpoint": 90000},
]

EMI_BUDGETS = [
    {"id": "5000", "label": "Up to ₹5,000"},
    {"id": "10000", "label": "Up to ₹10,000"},
    {"id": "15000", "label": "Up to ₹15,000"},
    {"id": "25000", "label": "Up to ₹25,000"},
    {"id": "any", "label": "No fixed budget"},
]

TENURES = [12, 24, 36, 48, 60]

# Document requirements. Aadhaar and PAN are skipped when KYC is already verified.
DOCUMENT_TYPES = {
    "aadhaar": {"label": "Aadhaar", "required": False, "ocr": True,
                "purpose": "Identity, verified by OCR and matched to your KYC record."},
    "pan": {"label": "PAN card", "required": False, "ocr": True,
            "purpose": "Identity and tax status, matched to the PAN on file."},
    "salary_slip": {"label": "Salary slip", "required": True, "ocr": True,
                    "purpose": "Income verification for the last month."},
    "bank_statement": {"label": "Bank statement", "required": True, "ocr": True,
                       "purpose": "Six months of credits and debits, for affordability."},
}

LENDERS = [
    {
        "id": "abc",
        "name": "Aditya Birla Capital",
        "min_score": 700,
        "max_amount": 1500000,
        "min_amount": 50000,
        "base_rate": 12.75,
        "processing_fee_pct": 1.5,
        "tenures": [12, 24, 36, 48],
        "min_monthly_income": 25000,
        "max_foir": 0.50,
        "tag": "best value",
        "decision_sla_hours": 2,
        "prepayment": "3 free part-payments a year · 2% foreclosure after 12 EMIs",
        "prepayment_score": 2,
    },
    {
        "id": "hero",
        "name": "Hero Fincorp",
        "min_score": 680,
        "max_amount": 1000000,
        "min_amount": 40000,
        "base_rate": 14.50,
        "processing_fee_pct": 2.0,
        "tenures": [12, 24, 36, 48, 60],
        "min_monthly_income": 20000,
        "max_foir": 0.48,
        "tag": "longest tenure",
        "decision_sla_hours": 4,
        "prepayment": "Foreclosure after 6 EMIs at 4% of principal",
        "prepayment_score": 1,
    },
    {
        "id": "tata",
        "name": "Tata Capital",
        "min_score": 720,
        "max_amount": 800000,
        "min_amount": 50000,
        "base_rate": 15.90,
        "processing_fee_pct": 0.0,
        "tenures": [12, 24, 36],
        "min_monthly_income": 30000,
        "max_foir": 0.45,
        "tag": "zero fee",
        "decision_sla_hours": 1,
        "prepayment": "Zero foreclosure charges after 6 EMIs",
        "prepayment_score": 3,
    },
]

CONSENT_CATALOGUE = [
    {"scope": "paytm.profile", "group": "identity", "required": True,
     "purpose": "Name, date of birth, address and masked PAN already held by Paytm, so you do not retype them.",
     "data": ["Full name", "Date of birth", "Address", "PAN (masked)"]},
    {"scope": "paytm.income", "group": "affordability", "required": True,
     "purpose": "Salary credits, existing EMIs and monthly spend, to work out what you can actually repay.",
     "data": ["Monthly net salary", "Existing EMI obligations", "Six months of spend by category"]},
    {"scope": "paytm.kyc", "group": "identity", "required": True,
     "purpose": "Your verified KYC status, so Aadhaar and PAN do not have to be uploaded again.",
     "data": ["KYC status", "CKYC id", "PAN verified flag"]},
    {"scope": "bureau.softpull", "group": "credit", "required": True, "affects_credit_report": False,
     "purpose": "A soft credit enquiry that shows your score to you and does not affect it.",
     "data": ["Credit score", "Enquiries in 90 days", "Active loans"]},
    {"scope": "bureau.hardpull", "group": "credit", "required": False, "affects_credit_report": True,
     "purpose": "A formal bureau enquiry, which lenders require before sanction. This one is recorded on your report.",
     "data": ["Full credit report shared with the chosen lender"]},
    {"scope": "lender.share", "group": "sharing", "required": False,
     "purpose": "Share your application and the consented data with the lender you pick. Nobody else receives it.",
     "data": ["Application form", "Income summary", "Credit report", "Uploaded documents"]},
    {"scope": "documents.access", "group": "documents", "required": False,
     "purpose": "Read the documents you upload, so the numbers can be extracted without you typing them.",
     "data": ["Salary slip", "Bank statement", "Aadhaar", "PAN"]},
    {"scope": "paytm.transactions", "group": "affordability", "required": False,
     "purpose": "Optional: recent transactions, used only for spend analysis.",
     "data": ["Recent transactions"]},
]
