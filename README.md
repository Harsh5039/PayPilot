# PayPilot — Conversational Financial Journeys

**An AI-powered financial co-pilot for Paytm.**

PayPilot brings conversational financial services into the Paytm app, helping users explore loans and health insurance through guided, consent-based journeys.

Powered by **Sarvam-105B** for natural language understanding and a deterministic financial engine for calculations, eligibility, consent enforcement and application workflows.

The platform combines AI-driven conversations with transparent financial calculations, progressive consent, mock partner integrations and an auditable activity trail.

## Key Features

PayPilot supports two end-to-end financial journeys:

- **Personal Loans:** Discovery, financial health assessment, pre-eligibility, lender comparison, document verification, consent and application tracking.
- **Health Insurance:** Plan discovery, proposal completion, underwriting simulation and policy issuance.

### 1. Loan Discovery & Personalisation

Users can explore loans based on:

- Eight loan purposes: Education, Medical, Travel, Wedding, Business, Home Renovation, Debt Consolidation and Personal.
- Desired loan amount.
- Preferred tenure (12–60 months).
- Comfortable monthly EMI budget.
- Employment type.

Users can modify their loan amount and tenure during comparison without restarting the journey or losing previously provided information.

### 2. Financial Intelligence

PayPilot generates a financial health snapshot using consented Paytm demo data.

The snapshot includes:

- Monthly income and spending by category.
- Existing EMI obligations.
- Disposable income.
- Affordable EMI estimation.
- Bureau score and its provider.
- Financial eligibility indicators.

**Important:** All eligibility results are labelled as *pre-eligibility*, never as loan approval.

### 3. Intelligent Loan Comparison

Users can compare lender offers based on:

- Interest rate and APR.
- Processing fees and GST.
- Stamp duty.
- Total interest and repayment amount.
- EMI across 12, 24, 36, 48 and 60 months.
- Prepayment conditions.
- Lender-specific eligibility explanations.

Comparison highlights include lowest interest rate, lowest total repayment, zero processing fee and flexible prepayment.

Users can also compare two lenders side by side and explore complete amortisation schedules.

### 4. Consent Management & Data Privacy

PayPilot follows a progressive, purpose-specific consent model.

Four separate consent stages are implemented:

1. **Paytm Data Access:** Profile, income and KYC information.
2. **Soft Bureau Enquiry:** Credit assessment without affecting the credit report.
3. **Lender Data Sharing:** Sharing selected information and documents with the chosen lender.
4. **Hard Bureau Enquiry:** Separate consent before final application submission.

Each consent records:
- Purpose of data access.
- Exact fields being shared.
- Recipient of the information.
- Consent history and revocation status.

Users can revoke active permissions, with all changes recorded in the consent ledger.

### 5. Financial Conflict Detection

PayPilot detects inconsistencies between user-provided information and available financial data.

Examples:
- Declared income versus actual salary credits.
- Business loan purpose versus missing business transaction receipts.

The journey pauses and requests clarification before proceeding.

### 6. Document Verification

Document requirements depend on lender policies and employment type.

| Lender | Demo document requirements |
|---|---|
| ABC | Matched salary slip and bank statement |
| Hero | Matched salary slip and bank statement |
| Tata | Matched bank statement |
| Self-employed | PAN and bank statement |

The system extracts PDF text and validates selected fields against seeded Paytm demo information.

Image-based documents require manual review.

**Limitation:** PDF field matching does not authenticate the document with the issuing bank or payroll provider.

### 7. Application Review & Approval

Before submission, users see exactly what will be shared:

- Personal and financial information.
- Selected lender.
- Uploaded documents.
- Active consent permissions.
- Loan terms and repayment details.

No application is submitted until the user explicitly approves the final review.

### 8. Application Tracking

Every application receives a reference number and a five-step tracking timeline.

Supported statuses include:

- Submitted
- Under Review
- Documents Required
- Approved
- Rejected

Additional capabilities:
- Simulated lender decision timelines.
- Notifications on status changes.
- Explanations for rejections and document requests.
- Downloadable application summaries.
- Resumption of incomplete applications.
- Historical application tracking.

All lender decisions are simulated in this demonstration.

---

## Technology Stack

| Layer | Technology |
|---|---|
| AI / LLM | Sarvam-105B |
| Backend | Python, FastAPI |
| Frontend | HTML, CSS, JavaScript |
| Database | SQLite |
| Financial Engine | Deterministic Python services |
| API | REST APIs |
| Containerisation | Docker, Docker Compose |
| Testing | Pytest, HTTP smoke tests, browser verification |
| AI Integration | Sarvam API with tool calling |

## System Architecture

```text
              User
               |
               v
       Paytm-style Interface
         static/index.html
               |
               v
        POST /api/chat
               |
               v
         FastAPI Backend
               |
       +-------+-------+
       |       |       |
       v       v       v
     Chat    Lending Insurance
     APIs     APIs     APIs
       |       |       |
       +-------+-------+
               |
        Flow Controller
          agent.py
               |
       +-------+--------+
       |       |        |
       v       v        v
    Sarvam  Consent  Financial
     AI     Engine   Intelligence
       |       |        |
       +-------+--------+
               |
               v
         SQLite Database
               |
       Audit / Tracking /
       Consent / Documents
```

### AI and Financial Safety

PayPilot separates language understanding from financial decision-making.

**Sarvam-105B handles:**
- Natural language understanding.
- Slot extraction.
- Conversational responses.
- Read-only tool calling.

**The deterministic engine handles:**
- Financial calculations.
- EMI and APR.
- Eligibility rules.
- Consent enforcement.
- Document validation.
- Application state transitions.
- Audit logging.

The AI agent cannot independently grant consent, create applications, upload documents or approve loans.

Every financial data read passes through the same consent checks used by the REST APIs.

---

## What Is Real vs. Simulated?

Transparency is central to PayPilot.

| Component | Implementation |
|---|---|
| Sarvam-105B integration | Real API calls when configured |
| Conversation and flow controller | Deterministic implementation |
| Consent ledger | Implemented and enforced |
| Financial health calculations | Deterministic |
| EMI, APR and amortisation | Deterministic calculations |
| Eligibility and conflict detection | Implemented |
| Paytm profile, income and transactions | Mock demo data |
| Credit bureau score | Simulated |
| Lender offers and decisions | Mock partner APIs |
| Insurance plans and underwriting | Mock partner APIs |
| PDF text extraction | Real extraction with demo-data matching |
| Application tracking and audit trail | Implemented with simulated partner events |

All mock integrations are isolated behind individual service modules, allowing partner integrations to be replaced independently.

---

## Project Structure

```text
PayPilot/
│
├── app/
│   ├── routers/
│   │   ├── chat.py
│   │   ├── data.py
│   │   ├── lending.py
│   │   └── insurance.py
│   │
│   ├── services/
│   │   ├── agent.py
│   │   ├── sarvam.py
│   │   ├── consent.py
│   │   ├── eligibility.py
│   │   ├── lending.py
│   │   ├── insurance.py
│   │   └── emi.py
│   │
│   ├── seed.py
│   ├── db.py
│   └── main.py
│
├── static/
│   └── index.html
│
├── tests/
│
├── Dockerfile
├── docker-compose.yml
├── render.yaml
├── requirements.txt
├── .env.example
├── smoke.py
├── verify_persist.py
├── DEMO_GUIDE.md
└── README.md
```

## Getting Started

### Prerequisites

- Python 3.10+
- Docker and Docker Compose (recommended)
- Sarvam API key (optional)

### Option 1: Docker (Recommended)

Clone the repository:

```bash
git clone https://github.com/Harsh5039/PayPilot.git
cd PayPilot
```

Start the application:

```bash
docker compose up --build
```

Open:

```text
http://localhost:8000
```

To enable live Sarvam-105B integration, configure `SARVAM_API_KEY` in your environment before starting the application.

### Option 2: Local Setup

Clone the repository and navigate to the project directory.

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it on Windows:

```bash
.venv\Scripts\activate
```

On Linux/macOS:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create your environment configuration:

```bash
cp .env.example .env
```

On Windows, you can copy `.env.example` to `.env` using File Explorer.

Start the application:

```bash
uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000`.

### Running Without an API Key

PayPilot supports offline operation.

Without `SARVAM_API_KEY`, the deterministic rule-based conversational agent handles the journey.

With a valid API key, the Sarvam-105B tool-calling integration becomes available.

Check the application mode:

```text
GET /api/health
```

The offline mode reports:

```json
{
  "mode": "offline-rule-agent"
}
```

---

## API Documentation

FastAPI automatically generates interactive API documentation.

Once the application is running:

- Swagger UI: `http://localhost:8000/docs`
- Health Check: `http://localhost:8000/api/health`

### Core API Endpoints

**Chat & Sessions**

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/sessions` | Create a session |
| POST | `/api/chat` | Send a conversational turn |
| GET | `/api/sessions/{id}` | Retrieve session state |
| GET | `/api/sessions/{id}/messages` | Retrieve conversation history |
| GET | `/api/sessions/{id}/audit` | Retrieve audit trail |
| GET | `/api/sessions/{id}/notifications` | Retrieve notifications |

**Consent Management**

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/consent/catalogue` | View consent scopes |
| GET | `/api/sessions/{id}/consent` | View consent history |
| POST | `/api/sessions/{id}/consent` | Grant consent |
| DELETE | `/api/sessions/{id}/consent/{scope}` | Revoke consent |

**Loan & Financial Intelligence**

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/loan/purposes` | Retrieve loan categories |
| GET | `/api/lenders` | Retrieve lender catalogue |
| GET | `/api/loans/emi` | Calculate EMI and amortisation |
| GET | `/api/sessions/{id}/financial-health` | Financial health snapshot |
| POST | `/api/sessions/{id}/loans/eligibility` | Check pre-eligibility |
| GET | `/api/sessions/{id}/conflicts` | Retrieve financial conflicts |
| POST | `/api/sessions/{id}/loans/compare` | Compare lender offers |
| POST | `/api/sessions/{id}/loans/compare-selected` | Compare selected lenders |

**Applications & Documents**

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/sessions/{id}/applications` | Create application |
| GET | `/api/sessions/{id}/applications` | Retrieve applications |
| POST | `/api/applications/{id}/documents/{doc_type}` | Upload document |
| GET | `/api/applications/{id}/documents` | Retrieve document status |
| GET | `/api/applications/{id}/review` | Review application data |
| POST | `/api/applications/{id}/approve` | Explicit approval |
| POST | `/api/applications/{id}/advance` | Simulate partner progression |
| GET | `/api/applications/{id}` | Track application |
| GET | `/api/applications/{id}/summary` | Downloadable summary |

**Health Insurance**

```text
GET  /api/insurance/plans
POST /api/sessions/{id}/insurance/policies
POST /api/policies/{id}/declare
POST /api/policies/{id}/pay
```

---

## State Management

Loan application lifecycle:

```text
Created
   |
   v
Documents Verified
   |
   v
Submitted
   |
   v
Under Review
   |
   +------> Approved
   |
   +------> Rejected
   |
   +------> Documents Required
```

Insurance policy lifecycle:

```text
Quoted
   |
   v
Proposal Complete
   |
   v
Issued
```

Out-of-order state transitions are rejected.

Partner decisions are explicitly marked as simulated, and the AI agent has no direct approval capability.

## Persistence

PayPilot uses SQLite to maintain:

- User sessions.
- Conversation history.
- Consent records.
- Loan applications.
- Insurance policies.
- Uploaded document metadata.
- Notifications.
- Audit events.

The frontend stores the session ID in local storage and restores the conversation from the backend after a page reload.

Existing applications remain accessible even when users start a new loan journey.

The database initialization uses additive migrations rather than dropping and recreating existing tables.

**Deployment note:** Configure persistent storage for SQLite in production. Temporary container filesystems may lose data after restarts or redeployments.

## Financial Safety & Guardrails

PayPilot incorporates several safeguards:

- Pre-eligibility is never represented as loan approval.
- EMI affordability is checked against the declared budget.
- Income discrepancies must be resolved before proceeding.
- Soft and hard bureau enquiries require separate consent.
- Application creation requires lender-sharing consent.
- Final submission requires hard bureau consent and explicit user approval.
- Consent revocation is recorded.
- Financial calculations are handled by deterministic services.
- Credit scores, lender decisions and disbursal timelines are labelled as simulated.

## Testing

Run the test suite:

```bash
pytest -q
```

The project includes 29 tests covering:

- Consent enforcement and revocation.
- Financial health calculations.
- EMI and APR calculations.
- Lender comparisons.
- Budget validation.
- Conflict detection.
- Document validation.
- Application lifecycle.
- Explicit approval requirements.
- Insurance workflows.
- Hindi conversational input.
- Tool-level consent restrictions.

Additional verification scripts:

```bash
python smoke.py
python verify_persist.py
```

`smoke.py` exercises both journeys over HTTP.

`verify_persist.py` checks browser-level persistence across page reloads and server restarts.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `SARVAM_API_KEY` | Blank | Sarvam API authentication |
| `SARVAM_BASE_URL` | `https://api.sarvam.ai/v1` | API base URL |
| `SARVAM_MODEL` | `sarvam-105b` | Language model |
| `SARVAM_TIMEOUT` | `20` | API timeout in seconds |
| `DATABASE_PATH` | `paypilot.db` | SQLite database path |
| `CONSENT_TTL_DAYS` | `30` | Consent validity period |

**Security:** Never commit `.env`, API keys, credentials or real customer financial documents to GitHub.

---

## Demo & Deployment

For the working demonstration, demo data and known limitations, see:

- [`DEMO_GUIDE.md`](DEMO_GUIDE.md)
- [`DEPLOY.md`](DEPLOY.md)

The application supports Docker-based deployment and can be configured for platforms such as Render, Fly.io and Railway.

## Important Disclaimer

PayPilot is a demonstration prototype built using mock financial institutions, simulated credit bureau information and seeded customer data.

It is not connected to live Paytm customer accounts, actual credit bureaus, banks or insurance providers.

It does not issue real loans, approve credit applications, authenticate financial documents with their issuers or issue actual insurance policies.

All financial information and partner decisions in the demonstration must be treated as simulated.

## Vision

**Making financial services conversational, transparent and consent-driven.**

PayPilot demonstrates how conversational AI and deterministic financial systems can work together to make complex financial journeys easier to understand while keeping users in control of their data and decisions.

---

**Built with Python, FastAPI, Sarvam-105B and a consent-first financial engine.**
