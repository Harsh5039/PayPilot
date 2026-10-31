"""End-to-end tests for the Phase 2 build. Run: pytest -q"""
from __future__ import annotations
from pathlib import Path

SAMPLES = Path(__file__).resolve().parents[1] / "static"

def _doc_payload(t):
    return {"file": (f"demo_{t}.pdf", (SAMPLES / f"demo_{t}.pdf").read_bytes(), "application/pdf")}



def _new(client, lang="en"):
    r = client.post("/api/sessions", json={"language": lang})
    assert r.status_code == 201, r.text
    return r.json()["session_id"]


def _chat(client, sid, text="", choice=None):
    r = client.post("/api/chat", json={"session_id": sid, "text": text, "choice": choice})
    assert r.status_code == 200, r.text
    return r.json()


def _to_offers(client, sid, amount_choice="amount:500000", tenure="tenure:24", band="75k_plus"):
    _chat(client, sid, "I need a loan")
    _chat(client, sid, "", "purpose:personal")
    _chat(client, sid, "", amount_choice)
    _chat(client, sid, "", tenure)
    _chat(client, sid, "", "budget:10000")
    _chat(client, sid, "", band)
    _chat(client, sid, "", "salaried")
    _chat(client, sid, "", "grant")          # data consent
    return _chat(client, sid, "", "grant")   # bureau consent -> offers


# ---------------------------------------------------------------- basics
def test_health_reports_llm_mode(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok"
    assert h["llm"]["model"] == "sarvam-105b"


def test_unknown_session_404(client):
    assert client.post("/api/chat", json={"session_id": "nope", "text": "hi"}).status_code == 404


# ---------------------------------------------------------------- consent
def test_paytm_data_blocked_until_consent(client):
    sid = _new(client)
    r = client.get(f"/api/sessions/{sid}/paytm/profile")
    assert r.status_code == 403
    assert r.json()["detail"]["missing_scope"] == "paytm.profile"
    client.post(f"/api/sessions/{sid}/consent", json={"scopes": ["paytm.profile"]})
    assert client.get(f"/api/sessions/{sid}/paytm/profile").json()["data"]["name"] == "Arjun Mehta"


def test_consent_is_revocable_and_has_history(client):
    sid = _new(client)
    client.post(f"/api/sessions/{sid}/consent", json={"scopes": ["paytm.income"]})
    assert client.get(f"/api/sessions/{sid}/paytm/income").status_code == 200
    assert client.delete(f"/api/sessions/{sid}/consent/paytm.income").status_code == 200
    assert client.get(f"/api/sessions/{sid}/paytm/income").status_code == 403
    hist = client.get(f"/api/sessions/{sid}/consent").json()["history"]
    assert any(h["scope"] == "paytm.income" and h["status"] == "revoked" for h in hist)


def test_consent_catalogue_is_grouped_with_data_lists(client):
    cat = client.get("/api/consent/catalogue").json()
    groups = cat["groups"]
    assert set(groups) >= {"identity", "affordability", "credit", "sharing", "documents"}
    credit = {s["scope"] for s in groups["credit"]}
    assert credit == {"bureau.softpull", "bureau.hardpull"}     # separate consents
    for scope in cat["scopes"]:
        assert scope["purpose"] and scope["data"]


def test_consent_records_who_receives_the_data(client):
    sid = _new(client)
    client.post(f"/api/sessions/{sid}/consent",
                json={"scopes": ["lender.share"], "shared_with": "HDFC Bank"})
    ledger = client.get(f"/api/sessions/{sid}/consent").json()["ledger"]
    entry = next(e for e in ledger if e["scope"] == "lender.share")
    assert entry["shared_with"] == "HDFC Bank"


# ---------------------------------------------------------------- money
def test_emi_and_apr(client):
    r = client.get("/api/loans/emi", params={"principal": 500000, "annual_rate": 12.75,
                                             "tenure_months": 36, "processing_fee_pct": 1.5}).json()
    assert 16700 < r["emi"] < 16900
    assert r["apr"] > 12.75                      # the fee pushes the real cost above the headline rate
    assert r["gst_on_fee"] == round(r["processing_fee"] * 0.18, 2)
    assert len(r["schedule"]) == 36 and r["schedule"][-1]["balance"] == 0

    zero = client.get("/api/loans/emi", params={"principal": 500000, "annual_rate": 12.75,
                                                "tenure_months": 36, "processing_fee_pct": 0}).json()
    assert abs(zero["apr"] - 12.75) < 0.05       # no fee, APR equals the rate


def test_financial_health_snapshot(client):
    sid = _new(client)
    assert client.get(f"/api/sessions/{sid}/financial-health").status_code == 403
    client.post(f"/api/sessions/{sid}/consent", json={"scopes": ["paytm.income", "bureau.softpull"]})
    h = client.get(f"/api/sessions/{sid}/financial-health").json()
    assert h["monthly_income"] == 84200
    assert h["disposable_income"] == h["monthly_income"] - h["existing_obligations"] - h["monthly_expenses"]
    assert h["affordable_emi"] > 0
    assert h["credit_score"] == 762 and h["grade"] in ("strong", "fair", "stretched")
    assert h["expense_breakdown"]


# ---------------------------------------------------------------- comparison
def test_comparison_has_every_comparison_field(client):
    sid = _new(client)
    comp = client.post(f"/api/sessions/{sid}/loans/compare",
                       json={"amount": 500000, "tenure_months": 24}).json()
    assert len(comp["offers"]) == 3
    o = comp["offers"][0]
    for field in ("apr", "annual_rate", "processing_fee", "total_charges", "total_interest",
                  "total_payable", "emi", "emi_by_tenure", "prepayment", "why"):
        assert field in o
    assert set(o["emi_by_tenure"]) <= {"12", "24", "36", "48", "60"}
    assert o["why"].startswith("Why:")
    hl = comp["highlights"]
    assert hl["lowest_total"]["lender_name"] and hl["lowest_rate"]["lender_name"]
    assert "Tata Capital" in hl["zero_fee"]           # zero processing fee is surfaced
    assert hl["flexible_prepayment"]["lender_name"]
    assert all(o["tenure_months"] == 24 for o in comp["offers"])


def test_budget_marks_offers_over_it(client):
    sid = _new(client)
    comp = client.post(f"/api/sessions/{sid}/loans/compare",
                       json={"amount": 500000, "tenure_months": 24, "emi_budget": 5000}).json()
    assert all(o["within_budget"] is False for o in comp["offers"])
    assert "budget" in comp["ranking"]


def test_compare_selected_side_by_side(client):
    sid = _new(client)
    comp = client.post(f"/api/sessions/{sid}/loans/compare",
                       json={"amount": 500000, "tenure_months": 24}).json()
    ids = [o["offer_id"] for o in comp["offers"][:2]]
    r = client.post(f"/api/sessions/{sid}/loans/compare-selected",
                    json={"offer_ids": ids, "amount": 500000}).json()
    assert len(r["offers"]) == 2
    assert any(row["field"] == "apr" for row in r["rows"])
    assert r["cheapest_total"]


# ---------------------------------------------------------------- journey
def test_guided_loan_journey_to_approval(client):
    sid = _new(client)
    r = _chat(client, sid, "I need a 5 lakh loan")
    assert r["step"] == "purpose"
    assert len(r["chips"]) == 8                       # every purpose, not just personal/business

    r = _chat(client, sid, "", "purpose:education")
    assert r["step"] == "amount"
    r = _chat(client, sid, "", "amount:500000")
    assert r["step"] == "tenure"
    r = _chat(client, sid, "", "tenure:24")
    assert r["step"] == "budget"
    r = _chat(client, sid, "", "budget:15000")
    assert r["step"] == "income"
    r = _chat(client, sid, "", "75k_plus")
    assert r["step"] == "employment"
    r = _chat(client, sid, "", "salaried")
    assert r["step"] == "consent_data"                 # no conflict for a matching band
    assert [s["scope"] for s in r["consent_request"]["items"]] == \
        ["paytm.profile", "paytm.income", "paytm.kyc"]

    r = _chat(client, sid, "", "grant")
    assert r["step"] == "consent_bureau"
    assert r["consent_request"]["scopes"] == ["bureau.softpull"]     # asked separately

    r = _chat(client, sid, "", "grant")
    assert r["step"] == "offers"
    types = [c["type"] for c in r["cards"]]
    assert types == ["snapshot", "offers"]
    snapshot = r["cards"][0]["data"]
    assert snapshot["stage"] == "pre_eligibility"
    assert snapshot["health"]["affordable_emi"] > 0
    offers = r["cards"][1]["data"]
    budget = 15000
    assert all(o["within_budget"] == (o["emi"] <= budget) for o in offers)
    assert all(o["within_budget"] is False for o in offers)      # 5L over 24m cannot fit ₹15,000

    r = _chat(client, sid, "", f"offer:{offers[0]['offer_id']}")
    assert r["step"] == "consent_share"
    assert set(r["consent_request"]["scopes"]) == {"lender.share", "documents.access"}
    assert r["consent_request"]["shared_with"] == offers[0]["lender_name"]

    r = _chat(client, sid, "", "grant")
    assert r["step"] == "prefill"
    prefill = r["cards"][0]["data"]
    app_id = prefill["application_id"]
    assert prefill["reference"].startswith("PP-2026-")
    assert sum(1 for f in prefill["fields"] if f["source"] != "needs you") >= 6

    r = _chat(client, sid, "", "continue")
    assert r["step"] == "docs"
    docs = r["cards"][0]["data"]
    assert docs["complete"] is False
    assert {m["doc_type"] for m in docs["missing"]} == {"salary_slip", "bank_statement"}

    for doc_type in ("salary_slip", "bank_statement"):
        up = client.post(f"/api/applications/{app_id}/documents/{doc_type}",
                         files=_doc_payload(doc_type))
        assert up.status_code == 200
        assert up.json()["document"]["confidence"] > 0.9

    r = _chat(client, sid, "", "refresh_docs")
    assert r["cards"][0]["data"]["complete"] is True

    r = _chat(client, sid, "", "continue")
    assert r["step"] == "review"
    review = r["cards"][0]["data"]
    assert review["shared_with"] and review["documents"] and review["fields"]
    assert r["consent_request"]["scopes"] == ["bureau.hardpull"]     # the one that hits the report

    r = _chat(client, sid, "", "grant")
    assert r["step"] == "submitted"
    assert r["cards"][0]["type"] == "status"
    assert r["notifications"]

    r = _chat(client, sid, "", "check_status")
    assert r["step"] == "submitted"                    # under review
    r = _chat(client, sid, "", "check_status")
    assert r["step"] == "done"
    assert r["tracker"]["status"] == "complete"

    app = client.get(f"/api/applications/{app_id}").json()["application"]
    assert app["status"] in ("approved", "rejected")
    assert app["reference"].startswith("PP-2026-")
    assert [e["status"] for e in app["events"]][0] == "created"


def test_change_amount_and_tenure_without_restarting(client):
    sid = _new(client)
    r = _to_offers(client, sid)
    assert r["step"] == "offers"

    r = _chat(client, sid, "", "change_amount")
    assert r["step"] == "amount"
    r = _chat(client, sid, "", "amount:300000")
    assert r["step"] == "offers"                        # straight back, consent kept
    assert all(o["amount"] == 300000 for o in r["cards"][0]["data"])

    r = _chat(client, sid, "", "change_tenure")
    assert r["step"] == "tenure"
    r = _chat(client, sid, "", "tenure:60")
    assert r["step"] == "offers"
    assert all(o["tenure_months"] == 60 for o in r["cards"][0]["data"])
    assert len(r["cards"][0]["data"]) == 1              # only Hero lends 60 months


def test_conflict_detection_and_resolution(client):
    sid = _new(client)
    _chat(client, sid, "I need a loan")
    _chat(client, sid, "", "purpose:business")
    _chat(client, sid, "", "amount:500000")
    _chat(client, sid, "", "tenure:24")
    _chat(client, sid, "", "budget:any")
    _chat(client, sid, "", "under_30k")
    r = _chat(client, sid, "", "salaried")

    assert r["step"] == "conflicts"
    found = r["cards"][0]["data"]
    fields = {c["field"] for c in found}
    assert fields == {"income_band", "purpose"}         # both conflicts surfaced

    r = _chat(client, sid, "", "conflict:paytm")
    assert r["step"] == "consent_data"
    session = client.get(f"/api/sessions/{sid}").json()
    assert session["slots"]["income_band"] == "75k_plus"
    assert session["slots"]["purpose"] == "personal"


# ---------------------------------------------------------------- application API
def _app_with_consent(client):
    sid = _new(client)
    client.post(f"/api/sessions/{sid}/consent",
                json={"scopes": ["lender.share", "documents.access", "bureau.hardpull",
                                 "paytm.profile", "paytm.income", "paytm.kyc", "bureau.softpull"],
                      "shared_with": "Aditya Birla Capital"})
    app = client.post(f"/api/sessions/{sid}/applications",
                      json={"lender_id": "abc", "amount": 400000}).json()["application"]
    return sid, app["id"]


def test_documents_required_then_resume(client):
    sid, app_id = _app_with_consent(client)
    res = client.post(f"/api/applications/{app_id}/approve").json()
    assert res["decision"] == "documents_required"
    assert {m["doc_type"] for m in res["missing"]} == {"salary_slip", "bank_statement"}
    assert client.get(f"/api/applications/{app_id}").json()["application"]["status"] == "documents_required"

    resumable = client.get(f"/api/sessions/{sid}/applications", params={"resumable": True}).json()
    assert any(a["id"] == app_id for a in resumable["applications"])

    for doc_type in ("salary_slip", "bank_statement"):
        client.post(f"/api/applications/{app_id}/documents/{doc_type}",
                    files=_doc_payload(doc_type))
    assert client.post(f"/api/applications/{app_id}/documents/verify").status_code == 200
    assert client.post(f"/api/applications/{app_id}/kyc").json()["verified"] is True
    assert client.post(f"/api/applications/{app_id}/approve").json()["decision"] == "submitted"
    assert client.post(f"/api/applications/{app_id}/advance").json()["decision"] == "under_review"
    final = client.post(f"/api/applications/{app_id}/advance").json()
    assert final["decision"] in ("approved", "rejected")
    assert final["decided_by"] == "partner"

    notes = client.get(f"/api/sessions/{sid}/notifications").json()["notifications"]
    assert len(notes) >= 3
    assert {n["status"] for n in notes} >= {"created", "documents_required", "submitted"}


def test_upload_rejects_wrong_file_type(client):
    sid, app_id = _app_with_consent(client)
    r = client.post(f"/api/applications/{app_id}/documents/salary_slip",
                    files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 422
    r = client.post(f"/api/applications/{app_id}/documents/unknown_type",
                    files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")})
    assert r.status_code == 400


def test_review_and_summary(client):
    sid, app_id = _app_with_consent(client)
    review = client.get(f"/api/applications/{app_id}/review").json()
    assert review["stage"] == "awaiting_your_approval"
    assert review["terms"]["emi"] > 0
    for doc_type in ("salary_slip", "bank_statement"):
        client.post(f"/api/applications/{app_id}/documents/{doc_type}",
                    files=_doc_payload(doc_type))
    client.post(f"/api/applications/{app_id}/documents/verify")
    client.post(f"/api/applications/{app_id}/kyc")
    client.post(f"/api/applications/{app_id}/approve")
    client.post(f"/api/applications/{app_id}/advance")
    client.post(f"/api/applications/{app_id}/advance")
    s = client.get(f"/api/applications/{app_id}/summary").json()
    assert s["reference"].startswith("PP-2026-")
    assert len(s["schedule"]) == s["tenure_months"]
    assert s["total_payable"] > s["principal"]
    assert s["documents"] and s["events"]


def test_approval_requires_hard_bureau_consent(client):
    sid = _new(client)
    client.post(f"/api/sessions/{sid}/consent", json={"scopes": ["lender.share",
      "paytm.profile", "paytm.income", "paytm.kyc", "bureau.softpull"],
      "shared_with": "Aditya Birla Capital"})
    app_id = client.post(f"/api/sessions/{sid}/applications",
                         json={"lender_id": "abc", "amount": 300000}).json()["application"]["id"]
    r = client.post(f"/api/applications/{app_id}/approve")
    assert r.status_code == 403
    assert "bureau.hardpull" in r.json()["detail"]["missing_scopes"]


# ---------------------------------------------------------------- other journeys
def test_insurance_journey_end_to_end(client):
    sid = _new(client)
    r = _chat(client, sid, "I need health insurance for my family")
    assert r["step"] == "ins_cover"
    _chat(client, sid, "", "family")
    _chat(client, sid, "", "sum:1000000")
    _chat(client, sid, "", "ped:no")
    r = _chat(client, sid, "", "grant")
    assert r["step"] == "ins_plans"
    plans = r["cards"][0]["data"]
    r = _chat(client, sid, "", f"plan:{plans[0]['plan_id']}")
    assert r["step"] == "ins_declare"
    _chat(client, sid, "", "declare")
    r = _chat(client, sid, "", "pay")
    assert r["step"] == "ins_done"
    assert r["cards"][0]["data"]["status"] == "issued"


def test_hindi_conversation(client):
    sid = _new(client, lang="hi")
    r = _chat(client, sid, "मुझे 5 लाख का लोन चाहिए")
    assert r["language"] == "hi"
    assert r["step"] == "purpose"
    assert any("\u0900" <= ch <= "\u097f" for ch in r["reply"])


def test_tool_layer_enforces_consent(client):
    import asyncio
    from app.services.sarvam import _run_tool

    sid = _new(client)
    out = asyncio.run(_run_tool("get_paytm_profile", {}, sid))
    assert out["error"] == "consent_required"
    client.post(f"/api/sessions/{sid}/consent", json={"scopes": ["paytm.profile"]})
    assert asyncio.run(_run_tool("get_paytm_profile", {}, sid))["profile"]["name"] == "Arjun Mehta"


# ---------------------------------------------------------------- persistence & history
def test_session_returns_chronological_messages(client):
    sid = _new(client)
    _chat(client, sid, "I need a loan")
    _chat(client, sid, "", "purpose:education")

    body = client.get(f"/api/sessions/{sid}").json()
    msgs = body["messages"]
    assert len(msgs) >= 3
    assert msgs[0]["role"] == "assistant"          # the greeting comes first
    assert msgs[1]["role"] == "user"
    assert all(msgs[i]["created_at"] <= msgs[i + 1]["created_at"] for i in range(len(msgs) - 1))
    assert body["message_count"] == len(msgs)

    dedicated = client.get(f"/api/sessions/{sid}/messages").json()["messages"]
    assert [m["content"] for m in dedicated] == [m["content"] for m in msgs]


def test_application_history_keeps_every_application(client):
    sid = _new(client)
    client.post(f"/api/sessions/{sid}/consent",
                json={"scopes": ["lender.share", "documents.access", "bureau.hardpull",
                                 "paytm.profile", "paytm.income", "paytm.kyc", "bureau.softpull"],
                      "shared_with": "Aditya Birla Capital"})

    first = client.post(f"/api/sessions/{sid}/applications",
                        json={"lender_id": "abc", "amount": 300000}).json()["application"]
    for dt in ("salary_slip", "bank_statement"):
        client.post(f"/api/applications/{first['id']}/documents/{dt}",
                    files=_doc_payload(dt))
    client.post(f"/api/applications/{first['id']}/documents/verify")
    client.post(f"/api/applications/{first['id']}/kyc")
    client.post(f"/api/applications/{first['id']}/approve")
    client.post(f"/api/applications/{first['id']}/advance")
    client.post(f"/api/applications/{first['id']}/advance")

    # a second loan, left pending — the first must survive
    client.post(f"/api/sessions/{sid}/consent",
                json={"scopes": ["lender.share"], "shared_with": "Hero Fincorp"})
    second = client.post(f"/api/sessions/{sid}/applications",
                         json={"lender_id": "hero", "amount": 200000}).json()["application"]
    assert first["reference"] != second["reference"]
    assert first["reference"].startswith("PP-2026-") and second["reference"].startswith("PP-2026-")

    apps = client.get(f"/api/sessions/{sid}/applications").json()["applications"]
    by_id = {a["id"]: a for a in apps}
    assert first["id"] in by_id and second["id"] in by_id
    assert by_id[first["id"]]["status"] in ("approved", "rejected")
    assert by_id[second["id"]]["status"] == "created"

    # history is everything; resumable is only the unfinished ones
    resumable = client.get(f"/api/sessions/{sid}/applications",
                           params={"resumable": True}).json()["applications"]
    resumable_ids = [a["id"] for a in resumable]
    assert second["id"] in resumable_ids
    assert first["id"] not in resumable_ids


def test_data_survives_a_restart(client):
    """init_db() runs on every startup; it must migrate, never wipe."""
    from app import db as dbmod

    sid = _new(client)
    before = dbmod.get_session(sid)
    dbmod.init_db()                                   # what a process restart does
    assert dbmod.get_session(sid) == before

    from app.config import settings
    assert __import__("pathlib").Path(settings.database_path).is_absolute()      # stable, independent of CWD


def test_unaffordable_application_is_blocked(client):
    sid = _new(client)
    client.post(f"/api/sessions/{sid}/consent", json={"scopes": [
        "lender.share", "documents.access", "bureau.hardpull", "paytm.profile",
        "paytm.income", "paytm.kyc", "bureau.softpull"],
        "shared_with": "Aditya Birla Capital"})
    app = client.post(f"/api/sessions/{sid}/applications",
                      json={"lender_id": "abc", "amount": 1400000}).json()["application"]
    for dt in ("salary_slip", "bank_statement"):
        client.post(f"/api/applications/{app['id']}/documents/{dt}", files=_doc_payload(dt))
    client.post(f"/api/applications/{app['id']}/documents/verify")
    client.post(f"/api/applications/{app['id']}/kyc")
    res = client.post(f"/api/applications/{app['id']}/approve")
    assert res.status_code == 422
    assert res.json()["detail"] == "requested_terms_not_pre_eligible_for_lender"


# ---------------------------------------------------------------- financial safety
def test_budget_guard_does_not_push_submission(client):
    sid = _new(client)
    _chat(client, sid, "I need a loan")
    _chat(client, sid, "", "purpose:personal")
    _chat(client, sid, "", "amount:500000")
    _chat(client, sid, "", "tenure:24")
    _chat(client, sid, "", "budget:5000")          # nothing can fit this
    _chat(client, sid, "", "75k_plus")
    _chat(client, sid, "", "salaried")
    _chat(client, sid, "", "grant")
    r = _chat(client, sid, "", "grant")

    assert r["step"] == "offers"
    assert "₹5,000" in r["reply"] and "smaller amount" in r["reply"]
    values = [c["value"] for c in r["chips"]]
    assert not any(v.startswith("offer:") for v in values)     # no one-tap apply
    assert "change_amount" in values and "change_tenure" in values
    assert r["cards"][1]["data"][0]["within_budget"] is False

    # the offers are still reachable, just not pushed
    r2 = _chat(client, sid, "", "show_offers")
    assert any(c["value"].startswith("offer:") for c in r2["chips"])


def test_simulated_results_are_labelled(client):
    sid = _new(client)
    comp = client.post(f"/api/sessions/{sid}/loans/compare", json={"amount": 300000}).json()
    assert comp["simulated"] is True
    assert all(o["simulated"] for o in comp["offers"])
    assert "Simulated" in comp["disclaimer"]

    client.post(f"/api/sessions/{sid}/consent",
                json={"scopes": ["paytm.profile", "paytm.income", "paytm.kyc",
                                 "bureau.softpull", "lender.share", "documents.access"],
                      "shared_with": "Aditya Birla Capital"})
    el = client.post(f"/api/sessions/{sid}/loans/eligibility",
                     json={"amount": 300000, "income_band": "75k_plus"}).json()
    assert el["bureau_simulated"] is True
    assert el["health"]["credit_simulated"] is True
    assert el["stage"] == "pre_eligibility"

    app = client.post(f"/api/sessions/{sid}/applications",
                      json={"lender_id": "abc", "amount": 300000}).json()["application"]
    up = client.post(f"/api/applications/{app['id']}/documents/salary_slip",
                     files=_doc_payload("salary_slip")).json()
    assert up["document"]["simulated"] is True
    assert "NOT issuer-authenticated" in up["document"]["note"]

    client.post(f"/api/applications/{app['id']}/documents/bank_statement",
                files=_doc_payload("bank_statement"))
    client.post(f"/api/sessions/{sid}/consent", json={"scopes": ["bureau.hardpull"]})
    client.post(f"/api/applications/{app['id']}/documents/verify")
    client.post(f"/api/applications/{app['id']}/kyc")
    client.post(f"/api/applications/{app['id']}/approve")
    client.post(f"/api/applications/{app['id']}/advance")
    final = client.post(f"/api/applications/{app['id']}/advance").json()
    assert final["simulated"] is True
    assert "mock partner" in final["decision_source"]


def test_soft_and_hard_enquiry_are_separate(client):
    cat = client.get("/api/consent/catalogue").json()["groups"]["credit"]
    by_scope = {c["scope"]: c for c in cat}
    assert by_scope["bureau.softpull"]["affects_credit_report"] is False
    assert by_scope["bureau.hardpull"]["affects_credit_report"] is True


def test_conflicts_must_be_confirmed_before_consent(client):
    sid = _new(client)
    _chat(client, sid, "I need a loan")
    _chat(client, sid, "", "purpose:business")
    _chat(client, sid, "", "amount:500000")
    _chat(client, sid, "", "tenure:24")
    _chat(client, sid, "", "budget:any")
    _chat(client, sid, "", "under_30k")
    r = _chat(client, sid, "", "salaried")
    assert r["step"] == "conflicts"
    assert r["consent_request"] is None          # nothing is asked for until this is settled
    r = _chat(client, sid, "", "conflict:mine")
    assert r["step"] == "consent_data"
