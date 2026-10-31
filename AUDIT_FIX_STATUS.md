# PayPilot repaired demo - audit disposition

## Follow-up to QA_REVIEW.md

The current workspace already contains fixes and regression tests for the reported demo defects: typed insurance answers, consent checks, policy history, eligibility, simulated-result labels, choice validation, language and product session preservation, mobile layout, and Hindi labels. Browser ownership is scoped to an opaque cookie; it is not verified Paytm identity or production authentication. Existing sessions without an owner cannot be claimed.

On 31 October 2026, `python -m pytest -q` passed **66 tests**. This includes cross-browser access checks and the audit regressions in `tests/test_qa_fixes.py`. The recorded `qa_fixed_results.json` reports an earlier 20-session synthetic run; it was not rerun in this verification. Mobile rendering, complete Hindi coverage, real integrations, and sustained load were not independently revalidated in this follow-up.

The production release restriction below remains in force: cookie possession alone does not establish a real user identity, and the seeded demo data and simulated financial services are not suitable for real users.

## Verified in this build

- **C02**: Removed destructive public admin reset.
- **C03-C05**: Consent refusal no longer grants loan-data, lender-sharing, hard/soft bureau or insurance Paytm data. Affirmative action required.
- **C06, H01-H02**: File mandatory; corrupt/empty/unsupported PDFs rejected; verification route reachable.
- **C07-C10, H04-H08 (demo-only)**: Content-aware PDF field extraction, field matching and mismatch reasons, document hash and current-version selection, account-consent checks, stored employment, fail-closed demo KYC gate, and submission protection. These checks **do not prove issuer authenticity**.
- **C11-C12 (demo isolation)**: Mock payment/insurance and mock lender decisions explicitly labeled; disabled in non-demo mode. Not connected to real payments or lending.
- **C13**: Terminal application decisions cannot be resubmitted.
- **H11-H15 (partial)**: Consent rechecked before submission, recipient bound to selected lender, and data scope gates added. Host Paytm authentication/ownership integration is not included.
- **H16**: Re-consenting creates a new version; earlier grant remains in history.
- **L01-L05**: Corrected minimum amounts/capacity, like-for-like comparison, nondefault tenor selection and invalid offer fallback.
- **L06-L08 (partial)**: Selected offers recomputed against canonical quote and stored application purpose/employment/offer ID; unsupported underwriting integrations remain.
- **L10**: Unverified self-employed income no longer yields a salary-based positive pre-eligibility.
- **L11-L14, L16-L17, L19**: Clarified approved amount; text tenure/budget; conflict confirmation; large request handling; final amortisation installment.
- **I01-I04 (demo)**: Medical declaration persisted with specific PED flag; must be explicit; unsupported sums rejected; quote expiry now tracked.
- **I06**: UI labels monthly premium as a monthly equivalent.
- **D01, D03, D06-D09 (partial), D11, D14-D17 (partial)**: Reset removed, random application references, LLM tool FOIR bug, constrained diagnostics/CORS, HTML summary escaping, config-driven consent TTL, bounded message pagination, new security tests, and workflow guards.

## Not solved without external systems or additional production engineering

- **C01**: Separate PayPilot login intentionally omitted at user request. Paytm-hosted login MUST deliver a verified principal to the backend and enforce object ownership; this demo does not integrate Paytm-issued identity tokens.
- **C07-C11 / H09-H10**: No third-party bank or payroll issuer verification, fraud detection, OCR for image scans, or real KYC provider. The demo PDF parser matches text against seeded fields only. Forged text PDFs can pass; real authenticity requires trusted data sources and manual review.
- **C11-C12 / I07**: No real lender, payment-gateway or insurer integration, real underwriting, live decision webhook, issuance, policy PDF or money movement.
- **H03, H17-H20 / D02, D04-D05, D10, D12-D13**: No encrypted original-document store, regulated data lifecycle, bank-grade authorization, rate limiting, database constraints/migrations at production depth, durable distributed DB, server-owned UI view model or complete monitoring/outbox.
- **L09, L15, L18, L20 / I05**: No partner-specific live underwriting, exact income self-declaration verification, regulator-approved APR/Key Facts Statement methodology, real purpose-specific offers or insurer medical underwriting.

## Test record

`pytest -q tests` -> **45 passed** (29 updated baseline + 16 adversarial regression cases). Tested via FastAPI TestClient with a disposable database. JS parsed by Node `--check`.

## Safety release decision

**Suitable for a clearly labeled LOCAL DEMO with synthetic PDFs. NOT ready for production, public Internet exposure, real Paytm users or financial transactions.** Setting `DEMO_MODE=false` blocks mock submission/issuance instead of converting mocks into live APIs. A production launch still needs verified Paytm identity and external regulated provider integrations.
