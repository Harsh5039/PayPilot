# PayPilot demo (repaired edition)

## Start

```bash
python -m pip install -r requirements.txt
# Windows: set DEMO_MODE=true  (default true)
# Linux/macOS: export DEMO_MODE=true
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 in a browser. You can demo without Sarvam API credentials.

## 5-minute loan journey
1. Start a loan journey for Rs 500,000, select purpose, tenure 24 months, budget, income 75k+, employment Salaried.
2. At each consent step choose the explicit **Share** / **Run credit check** chip.
3. Select a lender (ABC and Hero require two docs; Tata requires one bank statement in this illustrative lender-policy config).
4. Select **Share with this lender**. In Documents, download the included sample PDFs from the links in the card and upload each required file.
5. Observe validation status `matched_demo` based on extracted PDF contents, the Paytm demo name and salary credits. Try uploading random text or a mismatched PDF to demonstrate rejection.
6. Choose **Check again**, then **Continue to review**, then **Approve and submit**. Check the mock lender status twice.
7. Demonstrate a refusal by typing `I decline` at a consent step: the backend does **not** grant consent.

## What these checks do NOT prove

This is a reproducible demonstration, not a live financial services product. The PDFs are synthetic; parsing and matching them to seeded Paytm data does NOT independently authenticate issuer signatures or detect sophisticated forged statements. Images and unextractable scans require manual review. Paytm identity, bureau score, lenders, insurer quotes and decisions are mocked. The insurer payment step simulates a completed transaction; no money moves and no real policy exists. `DEMO_MODE=false` disables sensitive simulated approval and payment flows rather than pretending they are live.

Paytm login is expected at the host-app boundary; before production, verify Paytm-issued identity server-side and enforce per-user authorization. No standalone PayPilot login UI is introduced. The demo still uses an ID-based local session and is unsuitable for real private financial records.

## Run tests

```bash
python -m pytest -q tests/test_regressions.py
python -m pytest -q tests
```

No production bank/payroll verification, payment processor, or real lender integration is bundled.
