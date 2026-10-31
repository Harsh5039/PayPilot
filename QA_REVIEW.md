# PayPilot final QA review — 31 October 2026

Verdict: the guided demo paths work, but the app is not ready for real users. An unscripted demo can still fail on ordinary typed input. Passing the existing suite does not cover the defects below.

## Scope and evidence

- Tested the current local source using a separate `qa_review.db` and server at port 8019. Existing demo data was not changed.
- `python -m pytest -q`: **50 passed in 15.75 seconds**, including guided loan approval, insurance issuance, documents, consent, and persistence checks.
- `python qa_review.py`: **20 concurrent simulated sessions**, 10 loan users reaching offers and 10 insurance users reaching simulated issuance. English and Hindi session settings were mixed. All 20 completed; 210 measured requests; no errors; 11.25 seconds overall. Request median 970 ms, p95 1,948 ms, maximum 2,168 ms. These are one local run's observations, not a capacity guarantee.
- Per-session product, transcript count, and insurance policy ownership checks passed. This checks normal separation; it does not establish access control.
- Browser checks: eligibility button, insurance journey through issuance, Applications panel, language switch, product switch, rapid product toggles, reload, and mobile emulation at 390 × 844.
- Product-specific opening greetings, rapid toggle completion, and insurance selection after reload passed.
- Raw API evidence: `qa_review_results.json`; repeatable exploratory runner: `qa_review.py`. Run the runner against a disposable local server with `DATABASE_PATH=qa_review.db` and `SARVAM_API_KEY` empty.
- The server reported `offline-rule-agent`. Live Sarvam, real payments, real insurers, real Paytm identities, and human usability participants were **not** tested. The 20 users were synthetic sessions backed by the same seeded Arjun persona, not 20 authenticated people.
- Application source was not changed during this audit.

## Confirmed defects

### 1. High — no ownership enforcement for session/policy access

Reproduction: create an insurance policy with client A. Use a separate client B, with no credentials or cookies, to GET A's session and policy, then POST a medical declaration to A's policy. All returned HTTP 200, including the mutation.

Impact: possession of an object's ID is sufficient to read private session details and alter a policy. This is a real-user release blocker. IDs were supplied by the test; this does not demonstrate guessing or enumerating them.

Locations: `app/routers/chat.py:44`, `app/routers/insurance.py:69`, `app/routers/insurance.py:74`.

Fix direction: authenticate users and enforce owner checks on every session, application, document, consent and policy endpoint. Keep public demo mode explicitly isolated.

### 2. High — typing insurance coverage silently switches to loans

Reproduction: select Insurance, select Family of four, then type `10 lakh` at the coverage question. Actual response: `What is the loan for?` The persisted product becomes `loan` and the step becomes `purpose`.

Cause: global amount parsing infers loan intent before insurance routing. Plain text such as `My wife and two children` also fails to advance the family selection, whereas the chip works.

Location: `app/services/agent.py`, amount extraction before product routing at lines 458–462.

Fix direction: interpret answers using the current product and question. Only switch products on explicit switching intent; support ordinary typed insurance answers.

### 3. High — revoked insurance consent does not block proposal creation

Reproduction: reach insurance plans, revoke both `paytm.profile` and `paytm.kyc`, then select a plan through chat. The active permissions list is empty, but the response advances to `ins_declare` and a policy is created, with a proposal using the seeded KYC identity.

Cause: chat calls `insurance.create_policy` directly without the permission checks performed by the separate policy-creation route.

Location: `app/services/agent.py:988`.

Fix direction: enforce required consent at the service boundary immediately before protected operations so API and chat cannot diverge.

### 4. Medium — issued insurance is missing from Applications

Reproduction: complete the insurance flow and open Applications. The policy endpoint contains an issued policy, but the UI says `Your loan applications will appear here once you start applying.`

Location: `static/index.html:844`.

Fix direction: show policies in insurance mode, with a policy-specific empty state, status and reopening action.

### 5. Medium — language switching abandons the current visible journey

Reproduction: after an insurance journey with 15 messages, click Hindi. A different session ID is created and the visible transcript returns to one opening message. Existing records are not deleted, but the UI loses its pointer to that journey. The handler also restarts when clicking the already-selected language.

Location: `static/index.html:1036`.

Fix direction: update language within the current session and preserve answers, applications and progress.

### 6. Medium — changing product and returning does not resume progress

Reproduction: select Just me in Insurance, switch to Loans, then back to Insurance. The previous coverage question is replaced by the initial member question, with another new session ID.

This is a tradeoff introduced by the preceding product-greeting fix: correct initial greetings now come from a fresh session on each switch. There is no indication that a tab switch abandons the visible conversation, and no UI to recover it.

Location: `static/index.html:1043`.

Fix direction: retain a separate active session per product, or provide explicit resume/start-over behavior.

### 7. Medium — mobile layout overflows and leaves little chat space

Reproduction: emulate 390 × 844 mobile viewport. The document expands to approximately 489 CSS pixels; header controls extend beyond the requested viewport. The phone is only 286 pixels tall and the chat area approximately 164 pixels tall, while the progress panel is 440 pixels tall. Full-page screenshot visually confirmed the oversized layout.

Cause: fixed 378-pixel phone width, header controls without a small-screen layout, and the single breakpoint at `static/index.html:191`.

Fix direction: use a full-width chat on phones, wrap or simplify header controls, and put progress/permissions/history behind mobile tabs or a drawer. Avoid rendering a decorative phone inside an actual phone screen.

### 8. Medium — eligibility shortcut does not start eligibility

Reproduction: click `Am I eligible?`. Actual response: `What do you need today?`, followed by Personal loan/Business loan. The step remains `intent`.

Cause: the `eligibility` chip is classified as a generic choice, but the entry handler expects `check_eligibility` or a loan-prefixed choice.

Location: `app/services/agent.py:345` and the entry branch in `handle`.

Fix direction: route that chip to the intended eligibility discovery flow.

### 9. Medium — tracker claims payment and a PDF that do not exist

Reproduction: complete simulated insurance issuance and open progress. It states `Paid by UPI` and `PDF in vault, card on home`. The policy event explicitly states `DEMO issuance only: no real payment, insurer policy or PDF`.

Location: `app/services/agent.py:1020`–1021.

Fix direction: consistently label tracker steps as simulated and remove references to nonexistent files or provide an explicitly marked demo summary.

### 10. Medium — malformed chat choices produce server errors

Reproduction A: POST `/api/chat` with `choice: "loan:abc"` for a new session returns 500.

Reproduction B: in insurance coverage selection, `choice: "sum:123"` is accepted with 200; continue with `ped:no` and `grant`, and the grant turn returns 500.

These were direct API boundary probes; normal UI chips do not emit those values.

Fix direction: validate choice types and allowed values before mutating state. Return a useful 4xx or conversational correction rather than a crash or a broken session.

### 11. Low/Medium — Hindi localization is incomplete

Reproduction: choose Hindi in Insurance. The opening question is Hindi, but all member chips remain English (`Just me`, `Me and my spouse`, `Family of four`), as do global controls and several subsequent actions. Browser snapshot confirmed this.

Fix direction: localize labels, errors, consent and status messages together; retain machine choice values separately from display text.

## Additional UX recommendations

- Increase chat and financial-detail text sizes; the current chat uses 12px and several terms/badges use 7.5–10px. The screenshot's wide empty space would be better used for readable content.
- Add an accessible name to the icon-only Send button. The browser accessibility snapshot reports it as an unnamed button.
- Explain what remains to finish an application, and allow editing previous answers without restarting.
- Provide one clear history/resume area covering both products, with visibly separate loan and insurance records.
- Keep demo claims consistent across welcome copy, quotes, progress and final results.

## Recommended fix order

1. Before an unscripted demo: fix typed insurance routing, revoked-consent bypass, missing policy history, eligibility shortcut and misleading tracker text.
2. Next: preserve progress across language/product changes, repair mobile layout, and complete Hindi labels.
3. Before real users: implement authentication/ownership enforcement and robust input validation, then repeat cross-user negative tests and a larger sustained load test. Replace the shared demo identity and test real integrations separately.

No claim is made that this audit found every defect. It found 11 reproducible issues beyond the existing green test suite.
