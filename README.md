# PayPilot — conversational financial journeys

A co-pilot that runs inside the Paytm app. Sarvam-105B does the language; a
deterministic engine does the money. Consent-gated data, mock partner APIs, and
an auditable trail behind every number a customer sees.

Two journeys, both complete end to end: **loans** and **health insurance**.

---

## What the loan journey does

**Discovery** — purpose from eight real categories (education, medical, travel,
wedding, business, home renovation, debt consolidation, personal), amount,
preferred tenure 12–60 months, a comfortable EMI budget, and employment type.
Amount and tenure can be changed at the comparison screen without restarting:
consent and answers are kept.

**Financial intelligence** — a health snapshot built from consented Paytm data:
monthly income, spend by category, existing EMIs, disposable income, the EMI that
income actually supports, and the bureau score with its provider. The result is
labelled **pre-eligibility** everywhere, never approval, and every partner states
why it qualifies you or does not.

**Comparison** — interest rate *and* APR, processing fee with GST, stamp duty,
total interest, total repayment, the EMI at 12/24/36/48/60 months, prepayment
terms, and a one-line "why this lender". The set is annotated for lowest rate,
lowest total, zero processing fee and most flexible prepayment. Any two can be
compared side by side, and each offer opens a full amortisation schedule.

**Consent** — four separate asks: Paytm data (profile, income, KYC), a soft
bureau enquiry, sharing with the chosen lender plus document access, and finally
a hard bureau enquiry before submission. Every scope carries its purpose and the
exact fields it exposes; every grant records who receives the data; everything is
revocable, with a full history.

**Conflicts** — where what the customer said disagrees with what Paytm can see
(declared income vs salary credits, business purpose vs no trading receipts), the
journey stops and asks them to correct it before anything is submitted.

**Documents (demo)** — lender-policy-dependent requirements (ABC and Hero:
matched salary slip and bank statement; Tata: matched bank statement; self-employed:
PAN and bank statement). Real PDF text content is validated against the seeded
Paytm demo customer and status/reasons displayed. No independent bank/payroll
issuer authentication is performed; image scans require manual review.

**Review and approval** — a final screen showing exactly what will leave Paytm:
every field, every document, the lender receiving it, the consents in play and
the terms. Nothing is sent until the customer approves.

**Tracking** — a reference number (PP-2026-004821), a five-step timeline,
submitted → under review → documents required / approved / rejected, the lender's
estimated decision time, notifications on every status change, an explanation for
rejections and document requests, a downloadable summary, and resumption of an
incomplete application.

---

> **Demo repairs:** See [DEMO_GUIDE.md](DEMO_GUIDE.md) for the working demonstration and limitations. PDF content matching does not establish bank/payroll authenticity.

## Quickstart

### Docker (recommended)

```bash
docker compose up --build          # app → http://localhost:8000
SARVAM_API_KEY=sk_... docker compose up --build   # with the live model
```

### Local

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

**It runs with no API key.** Without `SARVAM_API_KEY` the deterministic rule
agent handles understanding and every journey still completes; `/api/health`
reports `mode: offline-rule-agent`. With a key the tool-calling agent comes
online. `DEPLOY.md` covers Render, Fly, Railway and a VPS.

---

## What is real and what is mocked

| Piece | Status |
| --- | --- |
| Sarvam-105B chat + tool calling | Real API call when a key is set |
| Flow controller, consent ledger, eligibility, APR, comparison, state machines, notifications, audit | Real, deterministic, tested |
| Paytm profile / income / spend / KYC | Mocked in `app/seed.py`, consent-gated |
| Bureau score | Mocked (`CIBIL-MOCK-88231`, 762, TransUnion CIBIL) |
| Lender quote / submit / decision | Mocked in `app/services/lending.py` |
| Insurer plans / underwriting / issuance | Mocked in `app/services/insurance.py` |
| PDF validation | Extracts real PDF text and checks selected fields against demo Paytm facts; **not issuer authenticity verification** |

Every mock sits behind one module, so replacing a partner is a single-file change.

---

## Architecture

```
Browser (static/index.html — phone + Tracker / Consent ledger / Audit trail)
   │  POST /api/chat  {session_id, text | choice}
   ▼
FastAPI routers ── chat · data · lending · insurance
   │
   ├── services/agent.py       flow controller + bilingual copy, both journeys
   ├── services/sarvam.py      Sarvam-105B: slot extraction, read-only tool loop
   ├── services/consent.py     progressive consent, enforced on every read
   ├── services/eligibility.py health snapshot, FOIR rules, conflict detection
   ├── services/lending.py     offers, APR, documents, review, lifecycle, notifications
   ├── services/insurance.py   insurer adapters
   ├── services/emi.py         EMI, amortisation, APR
   └── db.py                   SQLite: sessions, consent ledger, applications, policies,
                               documents, notifications, audit
```

**Division of labour.** The model understands language and may call read-only
tools — profile, income, eligibility, offers, EMI, application status, consent
ledger. It cannot create an application, grant consent, upload a document or
approve anything. Those live in the flow controller behind an explicit user
action, and every tool read passes the same consent gate as the REST API.

---

## Endpoints

### Chat
| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/sessions` | Create a session |
| POST | `/api/chat` | One turn — `text` for free text, `choice` for a chip |
| GET | `/api/sessions/{id}` | Step, slots, tracker, messages, applications, notifications |
| GET | `/api/sessions/{id}/messages` | Chronological transcript |
| GET | `/api/sessions/{id}/audit` | Full audit trail |
| GET | `/api/sessions/{id}/notifications` | Status-change notifications |

`POST /api/chat` returns `reply`, `chips`, `cards`, `consent_request`, `tracker`,
`notifications` and `step`. Card types: `snapshot`, `offers`, `conflicts`,
`prefill`, `documents`, `review`, `status`, `plans`, `proposal`, `policy`.

### Consent
| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/consent/catalogue` | Every scope, grouped, with purpose and data fields |
| GET | `/api/sessions/{id}/consent` | Active scopes, ledger and history |
| POST | `/api/sessions/{id}/consent` | Grant, with purpose and `shared_with` |
| DELETE | `/api/sessions/{id}/consent/{scope}` | Revoke |

Scopes: `paytm.profile`, `paytm.income`, `paytm.kyc`, `paytm.transactions`,
`bureau.softpull`, `bureau.hardpull`, `lender.share`, `documents.access`.

### Discovery, money and eligibility
| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/loan/purposes` | Purpose list and supported tenures |
| GET | `/api/lenders` | Partner catalogue and published rules |
| GET | `/api/loans/emi` | EMI, total interest, APR, amortisation schedule |
| GET | `/api/sessions/{id}/financial-health` | Health snapshot (needs `paytm.income`) |
| POST | `/api/sessions/{id}/loans/eligibility` | Pre-eligibility, per-partner reasons |
| GET | `/api/sessions/{id}/conflicts` | Detected mismatches |
| POST | `/api/sessions/{id}/loans/compare` | Offers with APR, charges, EMI by tenure, highlights |
| POST | `/api/sessions/{id}/loans/compare-selected` | Side-by-side for chosen offers |

### Applications
| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/sessions/{id}/applications` | Create (needs `lender.share`) |
| GET | `/api/sessions/{id}/applications?resumable=true` | Resume an incomplete one |
| POST | `/api/applications/{id}/documents/{doc_type}` | Upload + content validation (PDF; PNG/JPEG manual review, ≤8 MB) |
| GET | `/api/applications/{id}/documents` | Required, uploaded and missing |
| GET | `/api/applications/{id}/review` | Exactly what will be shared |
| POST | `/api/applications/{id}/approve` | Explicit approval (needs `bureau.hardpull`) |
| POST | `/api/applications/{id}/advance` | Simulate the lender's next step |
| GET | `/api/applications/{id}` | Tracking: status and event timeline |
| GET | `/api/applications/{id}/summary` | Terms, cost, schedule, documents, timeline |

### Insurance
`GET /api/insurance/plans` · `POST /api/sessions/{id}/insurance/policies` ·
`POST /api/policies/{id}/declare` · `POST /api/policies/{id}/pay`

### State machines

```
loan:    created → documents_verified → submitted → under_review
                → approved | rejected | documents_required
policy:  quoted → proposal_complete → issued
```

Out-of-order transitions return **409**. `decided_by` is always `"partner"` —
the agent has no path to an approval.

---

## Persistence

The session id lives in `localStorage`, so a reload resumes the conversation
instead of starting a new one. On boot the page calls `GET /api/sessions/{id}`,
rebuilds the transcript from the server's messages, restores language, product,
step, slots and tracker, and re-renders the current turn's cards and chips. A
stale id falls back to a fresh session; **New Session** clears it deliberately.

`GET /api/sessions/{id}` returns `messages` (chronological) and `message_count`;
`GET /api/sessions/{id}/messages` returns the transcript alone.

`GET /api/sessions/{id}/applications` returns **every** application for the
session — approved, rejected, pending and in progress — newest first. The
`resumable=true` flag narrows that to the unfinished ones. The **Applications**
tab lists them all and opens any one of them to its terms, reference, documents
and timeline. Starting another loan never removes an earlier application.

The database path is resolved against the project root, not the process working
directory, so the same SQLite file is found however the server is started.
`init_db()` only creates tables and applies additive column migrations — it never
drops or recreates anything, so data survives restarts and redeploys.

## Financial safety

- If every offer's EMI is above the declared budget, the agent says so, does not
  offer a one-tap apply, and points at a smaller amount or a longer tenure.
- Declared income is checked against Paytm salary credits and any mismatch must
  be confirmed before consent is requested.
- Soft and hard bureau enquiries are separate scopes; `bureau.softpull` carries
  `affects_credit_report: false`, `bureau.hardpull` carries `true`.
- Submission is refused (403) without `bureau.hardpull`, and an application
  cannot be created without `lender.share`.
- Credit scores, lender quotes, decisions and disbursal timings all
  carry `simulated: true`, and the UI labels them as simulated. An approval is
  never presented as a real sanction.

## Frontend

`static/index.html` — one file, no build step, no framework.

- Phone frame with chat, chips and typed cards
- **Tracker** — live application state and step timeline
- **Consent ledger** — every scope with purpose, expiry, recipient and a working **Revoke**
- **Audit trail** — request-level log
- Health snapshot, conflict resolution, tenure bar, EMI-by-tenure, "why this lender"
- Repayment schedule and side-by-side comparison in modals
- Per-document PDF field matching and manual-review/rejection reasons shown inline
- Final review card and explicit approval
- Status timeline with reference number and **Download summary** (printable HTML)
- Voice input through the Web Speech API (Chrome/Edge), Hindi or English

---

## Tests

```bash
pytest -q          # 29 tests, no network needed
```

Covers the consent gate and revocation history, grouped catalogue and
`shared_with`, EMI and APR (including the zero-fee case where APR equals the
rate), the health snapshot arithmetic, comparison fields and highlights, budget
flagging, side-by-side, the full journey to approval, amount and tenure changes
without restart, conflict detection and resolution, documents required → resume →
decision, file-type rejection, review and summary, hard-consent enforcement,
insurance end to end, Hindi input, and the tool layer refusing to read without
consent.

`python smoke.py` boots the real server and walks both journeys over HTTP.
`python verify_persist.py` drives a real browser through the section-7 checks:
complete a loan, reload, restart the server, start a second loan, and read the
history.

---

## Configuration

| Variable | Default | Notes |
| --- | --- | --- |
| `SARVAM_API_KEY` | *(blank)* | Blank ⇒ offline rule agent |
| `SARVAM_BASE_URL` | `https://api.sarvam.ai/v1` | |
| `SARVAM_MODEL` | `sarvam-105b` | `sarvam-105b-conversations` also works |
| `SARVAM_TIMEOUT` | `20` | Seconds |
| `DATABASE_PATH` | `paypilot.db` | `/data/paypilot.db` under Docker |
| `CONSENT_TTL_DAYS` | `30` | Consent expiry |

Never commit `.env`. The key is read from the environment only.
