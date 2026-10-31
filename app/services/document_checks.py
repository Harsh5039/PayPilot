"""Content-aware **demo** validation; NOT proof that a document is genuine.

Verifies structure, extracts text from real PDFs, matches fields with the seeded
Paytm account. Production needs bank/issuer checks or trained human review.
Images/scanned PDFs are queued for manual review, never silently verified.
"""
from __future__ import annotations

import hashlib
import io
import re
from datetime import date
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from app.config import settings
from app.seed import PAYTM_USER, PAYTM_INCOME

MAX_BYTES = 8 * 1024 * 1024
MAX_PDF_PAGES = 20


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def analyse(doc_type: str, content: bytes, filename: str) -> dict:
    sha = hashlib.sha256(content).hexdigest()
    if not content or len(content) > MAX_BYTES:
        raise ValueError("empty_or_oversized_file")
    kind = None
    extracted_text = ""
    if content.startswith(b"%PDF-"):
        kind = "pdf"
        try:
            reader = PdfReader(io.BytesIO(content), strict=True)
            if reader.is_encrypted or not (1 <= len(reader.pages) <= MAX_PDF_PAGES):
                raise ValueError("encrypted_or_unsupported_pdf")
            extracted_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:
            raise ValueError("invalid_or_unreadable_pdf") from exc
    elif content.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")):
        kind = "image"
        try:
            with Image.open(io.BytesIO(content)) as im:
                im.verify()
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError("invalid_image") from exc
    else:
        raise ValueError("unsupported_file_signature")

    extracted = {"file_type": kind, "sha256": sha, "authenticity": "not_independently_verified"}
    reasons: list[str] = []
    if kind == "image" or not _clean(extracted_text):
        reasons.append("scanned_or_image_document_requires_manual_review")
    else:
        text = _clean(extracted_text)
        lower = text.lower()
        name = PAYTM_USER["name"].lower()
        if name not in lower:
            reasons.append("account_holder_name_does_not_match_paytm_kyc")
        else:
            extracted["name_match"] = True

        if doc_type == "salary_slip":
            if not re.search(r"salary\s*slip|payslip|pay\s*slip", lower):
                reasons.append("not_identifiable_as_salary_slip")
            m = re.search(r"(?:net\s*(?:pay|salary)|take\s*home)(?:\s*(?:amount|salary))?\s*[:=-]?\s*(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d{1,2})?)", text, re.I)
            if m:
                pay = float(m.group(1).replace(",", ""))
                extracted["net_pay"] = pay
                if not (0.8 * PAYTM_INCOME["monthly_net_salary"] <= pay <= 1.2 * PAYTM_INCOME["monthly_net_salary"]):
                    reasons.append("salary_mismatch_with_paytm_credits")
            else:
                reasons.append("net_salary_not_found")
            if not re.search(r"(?:pay\s*period|month|pay\s*date)\s*[:=-]?\s*(?:20\d\d|[a-z]{3,9})", lower):
                reasons.append("pay_period_not_found")
        elif doc_type == "bank_statement":
            if "statement" not in lower or not re.search(r"bank|account", lower):
                reasons.append("not_identifiable_as_bank_statement")
            # Look for matching salary-credit transactions, not just any amount.
            credits = re.findall(r"salary\s*(?:credit|deposit)?\s*[:=-]?\s*(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d{1,2})?)", text, re.I)
            values = [float(x.replace(",", "")) for x in credits]
            matched = sum(abs(x - PAYTM_INCOME["monthly_net_salary"]) / PAYTM_INCOME["monthly_net_salary"] <= .2 for x in values)
            extracted["matched_salary_credits"] = matched
            if matched < 3:
                reasons.append("insufficient_matching_salary_credits")
            if not re.search(r"(?:statement\s*period|from\s*date|period)\s*[:=-]", lower):
                reasons.append("statement_period_not_found")
        elif doc_type in ("pan", "aadhaar"):
            if doc_type not in lower:
                reasons.append("document_type_not_recognised")
        else:
            reasons.append("unsupported_document_type")
    # A clear demo match is not independent authenticity verification.
    status = ("matched_demo" if settings.demo_mode and not reasons else
              "manual_review" if not reasons or kind == "image" else "rejected")
    if not settings.demo_mode and not reasons:
        reasons.append("independent_issuer_validation_required")
    extracted["checks_passed"] = not any(reasons)
    return {"sha256": sha, "extracted": extracted, "verification_status": status,
            "failure_reasons": reasons, "confidence": 1.0 if not reasons else 0.0}
